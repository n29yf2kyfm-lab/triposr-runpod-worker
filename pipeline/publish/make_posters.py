"""Render the hero poster a published entry needs to be visible.

publish_batch sets `posterUrl: None` deliberately -- the poster is a GPU render
and does not belong inside the publish transaction. Nothing else fills it in,
so an entry published and colour-baked still has no image, and
`pipeline/qc/review_sheets.py` filters on `e.get("posterUrl")`, which means a
posterless car is invisible to the very tool the owner reviews the library
with. build_index.py also carries posterUrl straight through to the app.

Path and framing follow what the library already uses
(platform/pipeline/ingest_commit.py): `car-renders/finished/<make>/<assetId>/
hero.jpg`, rendered az=40 elev=0.13 at 110 samples, saved as JPEG q88. Keeping
the same numbers means a new poster sits beside the existing ones without a
visible break in a contact sheet.

Renders the NEUTRAL published GLB, not a colour variant, so the poster shows
the car as shipped rather than implying a colour it may not default to.

Usage:
    make_posters.py --wave vw2 [--assets a,b] [--parallel 3] [--dry-run]
"""
import argparse, base64, io, json, os, sys, time, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CAT = os.path.join(REPO, "platform", "catalogue", "catalogue.v2.json")
SB = "https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object"
EP = os.environ.get("RENDER_ENDPOINT", "ng8oiz4p2l0xa0")
AZ, ELEV, SAMPLES, W, H = 40, 0.13, 110, 1200, 700


def load_env(path="/root/.alam3d_env"):
    try:
        body = open(path).read()
    except OSError:
        return
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        line = line[7:].lstrip() if line.startswith("export ") else line
        n, sep, v = line.partition("=")
        if sep and not os.environ.get(n.strip()):
            os.environ[n.strip()] = v.strip().strip("'\"")


load_env()
KEY = os.environ.get("SB_KEY") or sys.exit("FATAL: SB_KEY not set")
RP = os.environ.get("RUNPOD_API_KEY") or sys.exit("FATAL: RUNPOD_API_KEY not set")
HDR = {"apikey": KEY, "Authorization": "Bearer " + KEY}


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def sb_put(path, blob, ctype):
    rq = urllib.request.Request(f"{SB}/{path}", data=blob, method="POST",
        headers={**HDR, "Content-Type": ctype, "x-upsert": "true"})
    return urllib.request.urlopen(rq, timeout=600).status


def render(glb_url):
    body = {"input": {"glb_url": glb_url, "recolour": "off", "studio": True,
                      "az": AZ, "elev": ELEV, "samples": SAMPLES,
                      "width": W, "height": H}}
    jid = None
    for _ in range(10):
        try:
            rq = urllib.request.Request(f"https://api.runpod.ai/v2/{EP}/run",
                data=json.dumps(body).encode(),
                headers={"Authorization": "Bearer " + RP,
                         "Content-Type": "application/json"})
            jid = json.load(urllib.request.urlopen(rq, timeout=90))["id"]
            break
        except urllib.error.HTTPError:
            time.sleep(15)
    if not jid:
        raise RuntimeError("submit failed")
    t0 = time.time()
    while time.time() - t0 < 1200:
        try:
            d = json.load(urllib.request.urlopen(urllib.request.Request(
                f"https://api.runpod.ai/v2/{EP}/status/{jid}",
                headers={"Authorization": "Bearer " + RP}), timeout=60))
        except Exception:
            time.sleep(6); continue
        st = d.get("status")
        if st == "COMPLETED":
            png = (d.get("output") or {}).get("png_b64")
            if not png:
                raise RuntimeError("no image in output")
            return base64.b64decode(png)
        if st in ("FAILED", "CANCELLED"):
            raise RuntimeError(str(d.get("error"))[:110])
        time.sleep(6)
    raise TimeoutError


def poster_path(entry):
    return f"car-renders/finished/{entry['make']}/{entry['assetId']}/hero.jpg"


def one(entry, dry):
    from PIL import Image
    src = entry.get("desktopGlbUrl")
    if not src:
        return entry["assetId"], None, "no desktopGlbUrl"
    try:
        # cache-bust so the worker never serves a stale copy of a re-uploaded GLB
        png = render(src + f"?cb={int(time.time())}")
    except Exception as e:
        return entry["assetId"], None, f"{type(e).__name__}: {str(e)[:70]}"
    buf = io.BytesIO()
    Image.open(io.BytesIO(png)).convert("RGB").save(buf, "JPEG", quality=88)
    p = poster_path(entry)
    if not dry:
        sb_put(p, buf.getvalue(), "image/jpeg")
    return entry["assetId"], f"{SB}/public/{p}", None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wave", default="")
    ap.add_argument("--assets", default="")
    ap.add_argument("--parallel", type=int, default=3)
    ap.add_argument("--force", action="store_true", help="re-render even if a poster exists")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    cat = json.load(open(CAT))
    entries = cat if isinstance(cat, list) else cat.get("entries", cat)
    want = {s for s in a.assets.split(",") if s}
    todo = [e for e in entries
            if e.get("publicationStatus") == "approved"
            and (a.force or not e.get("posterUrl"))
            and (e.get("assetId") in want if want else
                 (a.wave and (e.get("assetId") or "").endswith(f"-{a.wave}-v1")))]
    if not todo:
        sys.exit("nothing to do")
    log(f"{len(todo)} poster(s)" + ("  [DRY RUN]" if a.dry_run else ""))

    by_id = {e["assetId"]: e for e in entries}
    ok = fail = 0
    with ThreadPoolExecutor(max_workers=a.parallel) as ex:
        for aid, url, err in ex.map(lambda e: one(e, a.dry_run), todo):
            if err:
                log(f"  FAIL {aid}: {err}"); fail += 1; continue
            if not a.dry_run:
                by_id[aid]["posterUrl"] = url
            ok += 1
            log(f"  OK   {aid}")

    if ok and not a.dry_run:
        json.dump(cat, open(CAT, "w"), indent=1, ensure_ascii=False)
        log(f"catalogue.v2.json updated — {ok} poster(s), {fail} failed. Gate then serve.")
    else:
        log(f"{ok} would render, {fail} failed")


if __name__ == "__main__":
    main()
