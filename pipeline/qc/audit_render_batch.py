#!/usr/bin/env python3
"""audit_render_batch.py — render one studio view of every training-candidate
GLB so each can be audited INDIVIDUALLY.

Owner instruction 2026-07-27: gather every GLB across waves 1-4 plus the
catalogue's audited set and audit each one, not in aggregate.

Design notes earned the hard way in this session:
  * results upload to Supabase as they complete. The scratchpad has been wiped
    three times today; anything held only on local disk is assumed lost.
  * resumable — an asset whose PNG already exists in the bucket is skipped, so
    a killed run costs nothing to restart.
  * a fixed azimuth does NOT give a consistent view: source GLBs arrive in
    whatever orientation their author used (the test render at az=35 produced a
    REAR three-quarter for an Audi S1). One view is enough to catch the main
    cull criteria — wrong vehicle, junk, scan mush, broken geometry — and
    ambiguous cars get extra views in a second pass rather than paying for two
    views across the whole set up front.

Env: RUNPOD_API_KEY, SB_KEY. No secrets in this file.
Usage: python3 pipeline/qc/audit_render_batch.py MANIFEST.json [--limit N] [--workers 2]
"""
import argparse, base64, json, os, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

EP = os.environ.get("RENDER_ENDPOINT", "ng8oiz4p2l0xa0")
SUPA = "https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object"
OUTP = "car-meshes/audit/glb"


def rp(url, key, body=None, timeout=180):
    rq = urllib.request.Request(
        url, data=json.dumps(body).encode() if body else None,
        method="POST" if body else "GET",
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    for attempt in range(4):
        try:
            return json.loads(urllib.request.urlopen(rq, timeout=timeout).read())
        except Exception:
            time.sleep(3 * (attempt + 1))
    return {}


def exists(sb, name):
    rq = urllib.request.Request(f"{SUPA}/list/car-meshes", method="POST",
                                data=json.dumps({"prefix": f"audit/glb/{name}",
                                                 "limit": 1}).encode())
    for h, v in (("apikey", sb), ("Authorization", "Bearer " + sb),
                 ("Content-Type", "application/json")):
        rq.add_header(h, v)
    try:
        return bool(json.loads(urllib.request.urlopen(rq, timeout=30).read()))
    except Exception:
        return False


def upload(sb, name, data):
    rq = urllib.request.Request(f"{SUPA}/car-meshes/audit/glb/{name}",
                                data=data, method="POST")
    for h, v in (("apikey", sb), ("Authorization", "Bearer " + sb),
                 ("Content-Type", "image/png"), ("x-upsert", "true")):
        rq.add_header(h, v)
    urllib.request.urlopen(rq, timeout=120).read()


def render_one(row, key, sb, az):
    name = row["file"].replace(".glb", "") + ".png"
    if exists(sb, name):
        return ("skip", row["file"])
    j = rp(f"https://api.runpod.ai/v2/{EP}/run", key, {"input": {
        "glb_url": row["glb"], "recolour": "off", "studio": True,
        "az": az, "elev": 0.06, "samples": 64, "width": 480, "height": 360}})
    jid = j.get("id")
    if not jid:
        return ("nojob", row["file"])
    for _ in range(100):
        st = rp(f"https://api.runpod.ai/v2/{EP}/status/{jid}", key)
        s = st.get("status")
        if s == "COMPLETED":
            b = (st.get("output") or {}).get("png_b64")
            if not b:
                return ("noimg", row["file"])
            try:
                upload(sb, name, base64.b64decode(b))
                return ("ok", row["file"])
            except Exception as e:
                return (f"upfail:{type(e).__name__}", row["file"])
        if s in ("FAILED", "CANCELLED"):
            return ("failed", row["file"])
        time.sleep(4)
    return ("timeout", row["file"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=2, help="match the endpoint's workersMax")
    ap.add_argument("--az", type=int, default=35)
    a = ap.parse_args()
    key, sb = os.environ.get("RUNPOD_API_KEY"), os.environ.get("SB_KEY")
    if not key or not sb:
        sys.exit("RUNPOD_API_KEY / SB_KEY missing from env")

    rows = [r for r in json.load(open(a.manifest)) if not r.get("image")]
    if a.limit:
        rows = rows[:a.limit]
    print(f"{len(rows)} GLBs to render (catalogue rows already have posters)", flush=True)

    t0, done = time.time(), {}
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = [ex.submit(render_one, r, key, sb, a.az) for r in rows]
        for i, f in enumerate(futs, 1):
            status, fn = f.result()
            done[status] = done.get(status, 0) + 1
            if i % 25 == 0 or i == len(futs):
                el = time.time() - t0
                rate = i / el
                print(f"  {i}/{len(rows)} | {dict(done)} | {rate*60:.1f}/min | "
                      f"ETA {((len(rows)-i)/rate)/60:.0f} min", flush=True)
    print(f"\nDONE in {(time.time()-t0)/60:.0f} min: {dict(done)}", flush=True)


if __name__ == "__main__":
    main()
