"""Fetch the best Sketchfab candidate for named target cars and stage it.

Pairs with gap_search.py: gap_search RANKS candidates for one nameplate, this
DOWNLOADS the winners and puts them somewhere durable. Kept separate because
searching is cheap and repeatable while downloading burns rate limit.

Design notes, all learned the hard way on this project:

* Supabase FIRST, local disk second. A generation job succeeded on 2026-07-31
  and was then lost because the script wrote to a full disk before uploading.
  Every blob that validates goes to the bucket immediately; the local copy is a
  convenience that can vanish with the container.
* Resumable. Re-running skips anything already in the bucket, so a rollback
  mid-wave costs only the item in flight.
* Token rotation on 429/403, with a cooldown after repeated 429s - the same
  storm handling wave7_download.py needed.
* Integrity is checked before anything is stored: magic bytes plus the GLB
  header's own total-length field against the real byte count. A truncated
  download that still "looks like" a GLB is the classic silent failure.

Usage:
  target_fetch.py "Porsche Taycan" "Toyota Yaris" [--years 2025,2024] [--per 1]
  target_fetch.py --manifest targets.json      # {"Porsche Taycan": "<uid>", ...}
"""
import argparse, json, os, struct, subprocess, sys, time, urllib.error, urllib.parse, urllib.request
from itertools import cycle

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gap_search import face_score, search, toks  # noqa: E402

API = "https://api.sketchfab.com/v3"
SB = "https://tfkvthprsntexrcuqpyd.supabase.co"
BUCKET = "car-meshes"
PREFIX = "staging/targets"
MAX_OBJ = 48_000_000          # Supabase per-object ceiling
REPO = "/home/user/triposr-runpod-worker"
CAT = f"{REPO}/platform/catalogue/catalogue.v2.json"


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def sb_key():
    k = os.environ.get("SB_KEY")
    if not k:
        sys.exit("FATAL: SB_KEY not set")
    return k


def sb_put(path, blob, ctype="model/gltf-binary"):
    r = urllib.request.Request(f"{SB}/storage/v1/object/{path}", data=blob, method="POST",
        headers={"Authorization": f"Bearer {sb_key()}", "apikey": sb_key(),
                 "Content-Type": ctype, "x-upsert": "true"})
    return urllib.request.urlopen(r, timeout=600).status


def sb_list(prefix):
    body = json.dumps({"prefix": prefix, "limit": 1000}).encode()
    r = urllib.request.Request(f"{SB}/storage/v1/object/list/{BUCKET}", data=body,
        headers={"Authorization": f"Bearer {sb_key()}", "apikey": sb_key(),
                 "Content-Type": "application/json"})
    try:
        return {o["name"] for o in json.load(urllib.request.urlopen(r, timeout=120))}
    except Exception as e:
        log(f"warn: bucket list failed ({e}); resume disabled")
        return set()


def valid_glb(b):
    """Magic bytes AND the header's own length field. Either alone lets a
    truncated download through."""
    return len(b) > 20 and b[:4] == b"glTF" and struct.unpack("<I", b[8:12])[0] == len(b)


def known_uids():
    """Every uid already judged - approved or quarantined. Re-fetching one wastes
    a download on a decision the owner already made."""
    try:
        return {e["sourceReferenceId"] for e in json.load(open(CAT))
                if e.get("sourceReferenceId")}
    except Exception as e:
        log(f"warn: catalogue unreadable ({e}); dedup disabled")
        return set()


def pick(nameplate, years, tok, known, per):
    """Best in-serving-band candidates for one nameplate, newest generation first."""
    import re
    queries = [f"{nameplate} {y}" for y in years if y] + [nameplate, f"{nameplate} facelift"]
    want = re.sub(r"[^a-z0-9]+", " ", nameplate.lower()).split()
    found = {}
    for q in queries:
        try:
            for r in search(tok, q):
                found.setdefault(r["uid"], r)
        except Exception as e:
            log(f"  query failed [{q}]: {type(e).__name__}")
    rows = []
    for uid, r in found.items():
        nm = r.get("name", "")
        low = re.sub(r"[^a-z0-9]+", " ", nm.lower())
        if not all(w in low for w in want) or uid in known:
            continue
        fc = r.get("faceCount") or 0
        if not face_score(fc):
            continue                      # outside the band the pipeline serves
        yr = max([int(y) for y in re.findall(r"\b((?:19|20)\d{2})\b", nm)] or [0])
        rows.append({"uid": uid, "name": nm, "year": yr, "faces": fc,
                     "likes": r.get("likeCount", 0),
                     "licence": (r.get("license") or {}).get("label", "?"),
                     "author": (r.get("user") or {}).get("displayName", ""),
                     "nameplate": nameplate,
                     "score": (yr / 2030.0) * 3.0 + face_score(fc) * 2.0
                              + min(r.get("likeCount", 0), 200) / 200.0})
    rows.sort(key=lambda x: -x["score"])
    return rows[:per]


def fetch_one(row, tok, staged):
    uid = row["uid"]
    key = f"{PREFIX}/{uid}.glb"
    if f"{uid}.glb" in staged:
        log(f"  already staged {row['nameplate']} {uid[:8]}")
        row["staged"] = True
        return row
    rq = urllib.request.Request(f"{API}/models/{uid}/download",
        headers={"Authorization": f"Token {next(tok)}", "User-Agent": "Mozilla/5.0"})
    dl = json.load(urllib.request.urlopen(rq, timeout=90))
    url = (dl.get("glb") or {}).get("url")
    if not url:
        log(f"  SKIP no-glb-format {row['nameplate']} {uid[:8]}")
        row["staged"] = False; row["skip"] = "no-glb"
        return row
    blob = urllib.request.urlopen(url, timeout=900).read()
    if not valid_glb(blob):
        log(f"  SKIP bad/truncated ({len(blob)}B) {row['nameplate']} {uid[:8]}")
        row["staged"] = False; row["skip"] = "bad-glb"
        return row
    if len(blob) > MAX_OBJ:
        # Over the bucket ceiling: Draco the geometry rather than drop the car.
        # Draco is lossless-enough for our purposes and does not touch materials.
        tmp = f"/tmp/_tf_{uid}.glb"; out = f"/tmp/_tf_{uid}_dr.glb"
        open(tmp, "wb").write(blob)
        subprocess.run(["npx", "--yes", "@gltf-transform/cli@4", "draco", tmp, out],
                       capture_output=True, timeout=900)
        if os.path.exists(out) and 0 < os.path.getsize(out) <= MAX_OBJ:
            blob = open(out, "rb").read()
            log(f"  draco {row['nameplate']}: {len(blob)/1e6:.1f}MB")
        else:
            log(f"  SKIP too-big {len(blob)/1e6:.1f}MB {row['nameplate']}")
            row["staged"] = False; row["skip"] = "too-big"
            for p in (tmp, out):
                if os.path.exists(p):
                    os.remove(p)
            return row
        for p in (tmp, out):
            if os.path.exists(p):
                os.remove(p)
    sb_put(f"{BUCKET}/{key}", blob)       # durable BEFORE anything local
    row["staged"] = True
    row["bytes"] = len(blob)
    row["glb_url"] = f"{SB}/storage/v1/object/public/{BUCKET}/{key}"
    log(f"  staged {row['nameplate']:26} {len(blob)/1e6:6.1f}MB  {row['name'][:44]}")
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("nameplates", nargs="*")
    ap.add_argument("--years", default="2025,2024,2023")
    ap.add_argument("--per", type=int, default=1, help="candidates per nameplate")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    if not a.nameplates:
        sys.exit("give at least one nameplate")
    tok = toks()
    known = known_uids()
    staged = {n.split("/")[-1] for n in sb_list(PREFIX + "/")}
    log(f"{len(known)} uids already judged; {len(staged)} already staged")

    picks = []
    for np in a.nameplates:
        rows = pick(np, a.years.split(","), tok, known, a.per)
        if not rows:
            log(f"{np}: NO in-band candidate - nothing premium on Sketchfab")
            continue
        for r in rows:
            log(f"{np}: -> {r['year'] or '----'} {r['name'][:44]} "
                f"{r['faces']:,}f ♥{r['likes']} [{r['licence']}]")
        picks += rows
        time.sleep(2)

    results, consec429 = [], 0
    for r in picks:
        for attempt in range(4):
            try:
                results.append(fetch_one(r, tok, staged))
                consec429 = 0
                break
            except urllib.error.HTTPError as e:
                if e.code in (429, 403):
                    consec429 += 1
                    wait = 1800 if consec429 >= 3 else 60 * (attempt + 1)
                    log(f"  {e.code} on {r['nameplate']}; rotating token, waiting {wait}s")
                    if consec429 >= 3:
                        consec429 = 0
                    time.sleep(wait)
                else:
                    log(f"  http-{e.code} {r['nameplate']}"); break
            except Exception as e:
                log(f"  {type(e).__name__} {r['nameplate']}: {str(e)[:80]}")
                time.sleep(10 * (attempt + 1))
        time.sleep(3)

    got = [r for r in results if r.get("staged")]
    log(f"DONE: {len(got)}/{len(picks)} staged under {BUCKET}/{PREFIX}/")
    if a.out:
        json.dump(results, open(a.out, "w"), indent=1)
        log(f"wrote {a.out}")


if __name__ == "__main__":
    main()
