#!/usr/bin/env python3
"""mk_keep_csv.py — turn a wave's <MARQUE>_CLEAN.json into the two CSVs
publish_batch expects.

Every wave so far has built these by hand, which is how a truncated 8-character
uid once reached publish_batch and came back as an opaque HTTP 400. The uid
length is asserted here instead.

The sha256 is not cosmetic: publish_batch gate G1 re-downloads the staged GLB and
refuses the car if the hash disagrees with the one reviewed. So it MUST be
computed from the bucket object the reviewer actually looked at, never from a
local copy that may have been re-fetched since.

Deliberately omitted fields:
  body_style — CLAUDE.md: a single-cab Hilux was titled "Double Cab", so body
    style comes from the render, not the title. Left blank rather than guessed.
  year_end   — a single sourced mesh is one car, not a production range.

Usage:
  python3 pipeline/publish/mk_keep_csv.py jaguar --clean pipeline/ingest/JAGUAR_CLEAN.json
"""
import argparse, concurrent.futures as cf, csv, datetime, hashlib, json, os, sys
import urllib.request, urllib.error

SB_BASE = "https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object"
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SB = os.environ.get("SB_KEY") or sys.exit("FATAL: SB_KEY env var required")


def sb_get(path, tries=4):
    for a in range(tries):
        rq = urllib.request.Request(f"{SB_BASE}/{path}")
        # apikey AND Authorization — with Bearer alone Supabase storage returns
        # "403 Invalid Compact JWS", which reads exactly like an expired key.
        for h, v in (("apikey", SB), ("Authorization", "Bearer " + SB)):
            rq.add_header(h, v)
        try:
            return urllib.request.urlopen(rq, timeout=300).read()
        except urllib.error.HTTPError:
            raise                       # a real status: 404 means not staged
        except Exception:
            if a == tries - 1:
                raise
            import time
            time.sleep(2 * (a + 1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("marque")
    ap.add_argument("--clean", required=True)
    ap.add_argument("--manifest", help="wave manifest, for licence/author (default /tmp/<marque>/manifest.filtered.json)")
    ap.add_argument("--staging-prefix", help="default staging/<marque>")
    ap.add_argument("--suffix", default="1")
    ap.add_argument("--parallel", type=int, default=6)
    a = ap.parse_args()

    marque = a.marque.lower()
    stage = a.staging_prefix or f"staging/{marque}"
    mpath = a.manifest or f"/tmp/{marque}/manifest.filtered.json"
    rows = json.load(open(a.clean))
    lic = {}
    if os.path.exists(mpath):
        lic = {r["uid"]: r for r in json.load(open(mpath))}
    else:
        print(f"WARNING: no manifest at {mpath} — every licence will be 'unverified'")

    for r in rows:
        uid = (r.get("uid") or "").strip()
        assert len(uid) == 32, f"uid must be the full 32 characters, got {len(uid)}: {uid!r}"

    today = datetime.date.today().isoformat()

    def hash_one(r):
        uid = r["uid"].strip()
        try:
            blob = sb_get(f"car-meshes/{stage}/{uid}.glb")
        except Exception as e:
            return (r, None, f"{type(e).__name__}: {e}")
        return (r, hashlib.sha256(blob).hexdigest(), None)

    out, bad = [], []
    with cf.ThreadPoolExecutor(a.parallel) as ex:
        for i, (r, sha, err) in enumerate(ex.map(hash_one, rows), 1):
            if err:
                bad.append((r["uid"], err))
                print(f"  [{i}/{len(rows)}] MISSING {r['uid'][:8]}  {err}", flush=True)
                continue
            out.append({
                "uid": r["uid"].strip(),
                "glb_sha256": sha,
                "make": marque,
                "model": (r.get("model") or "").strip(),
                "reviewed_at": today,
                "year_start": str(r.get("year") or "").strip(),
                "year_end": "",
                "body_style": "",
                "trim": (r.get("trim") or "").strip(),
            })
            print(f"  [{i}/{len(rows)}] {sha[:12]}  {r['uid'][:8]}  {r.get('model','')}", flush=True)

    U = marque.upper().replace("-", "")
    kp = os.path.join(REPO, "pipeline", "publish", f"{U}_KEEP_{a.suffix}.csv")
    lp = os.path.join(REPO, "pipeline", "publish", f"{U}_LICENCES_{a.suffix}.csv")
    with open(kp, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)
    with open(lp, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["uid", "licence"])
        for r in out:
            w.writerow([r["uid"], (lic.get(r["uid"], {}).get("licence") or "unverified")])
    print(f"\n{kp}: {len(out)} rows")
    print(f"{lp}: {len(out)} rows")
    if bad:
        print(f"\nNOT STAGED — these cannot be published until re-staged ({len(bad)}):")
        for uid, err in bad:
            print(f"  {uid}  {err}")


main()
