#!/usr/bin/env python3
"""generate_and_render.py — join the two halves of the pipeline.

Until now generation and rendering were separate systems that only met because
a human passed URLs between them: the Alam-3D pod exported a GLB and uploaded
it, and a separate script later handed that URL to the render endpoint. There
was no path from "images of a car" to "studio frames the app can serve".

This is that path:

    images -> [generation pod, A100 + alam3d-data volume] -> GLB
                                                              |
                                                              v
                     [render-v2 serverless, 4090, no volume] -> PNG frames
                                                              |
                                                              v
                                              car-renders/<make>/<model>/

WHY THE CREDENTIALS STAY HERE
The obvious design is to let the pod call the render endpoint itself, but that
requires a RUNPOD_API_KEY inside the container — and that key can create pods,
delete pods, and read the whole account. A render job needs none of that.
Least privilege: the orchestrator holds the account key, and the pod continues
to receive only SB_KEY and HF_TOKEN, exactly what it had before. The cost is
one extra hop; the benefit is that a training container can never spend money.

Two modes:
  --from-run RUNID    render GLBs an earlier generation run already uploaded
                      (cheap: no generation pod, renders only)
  --case NAME         full path — launch generation, wait, then render

Env: RUNPOD_API_KEY, SB_KEY. No secrets in this file.
"""
import argparse, base64, json, os, subprocess, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

EP = os.environ.get("RENDER_ENDPOINT", "ng8oiz4p2l0xa0")
SUPA = "https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object"
PUB = SUPA + "/public"


def rp(url, key, body=None, timeout=240):
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


def sb_list(key, bucket, prefix):
    rq = urllib.request.Request(f"{SUPA}/list/{bucket}", method="POST",
                                data=json.dumps({"prefix": prefix, "limit": 1000,
                                                 "sortBy": {"column": "name", "order": "asc"}}).encode())
    for h, v in (("apikey", key), ("Authorization", "Bearer " + key),
                 ("Content-Type", "application/json")):
        rq.add_header(h, v)
    return json.loads(urllib.request.urlopen(rq, timeout=60).read())


def sb_put(key, bucket, path, data, ctype):
    rq = urllib.request.Request(f"{SUPA}/{bucket}/{path}", data=data, method="POST")
    for h, v in (("apikey", key), ("Authorization", "Bearer " + key),
                 ("Content-Type", ctype), ("x-upsert", "true")):
        rq.add_header(h, v)
    urllib.request.urlopen(rq, timeout=180).read()


def render_frame(glb_url, az, key, samples, w, h):
    """One studio frame. Returns PNG bytes or None — never raises, so one bad
    frame cannot lose a whole turntable."""
    j = rp(f"https://api.runpod.ai/v2/{EP}/run", key, {"input": {
        "glb_url": glb_url, "recolour": "off", "studio": True,
        "az": az, "elev": 0.06, "samples": samples, "width": w, "height": h}})
    jid = j.get("id")
    if not jid:
        return None
    for _ in range(120):
        st = rp(f"https://api.runpod.ai/v2/{EP}/status/{jid}", key)
        s = st.get("status")
        if s == "COMPLETED":
            b = (st.get("output") or {}).get("png_b64")
            return base64.b64decode(b) if b else None
        if s in ("FAILED", "CANCELLED"):
            return None
        time.sleep(4)
    return None


def turntable(glb_url, name, key, sb, frames, samples, w, h, workers, out_prefix):
    """Render `frames` evenly spaced angles and publish them. Returns a manifest
    the app (or the catalogue builder) can consume."""
    azs = [round(360 * i / frames) for i in range(frames)]
    print(f"  {name}: {frames} frames at {samples} samples, {w}x{h}", flush=True)
    urls, missing = [], []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for az, png in zip(azs, ex.map(lambda a: render_frame(glb_url, a, key, samples, w, h), azs)):
            if not png:
                missing.append(az)
                continue
            path = f"{out_prefix}/{name}/az{az:03d}.png"
            sb_put(sb, "car-renders", path, png, "image/png")
            urls.append({"az": az, "url": f"{PUB}/car-renders/{path}"})
    if missing:
        print(f"    WARNING: {len(missing)} frame(s) failed: {missing}", flush=True)
    return {"name": name, "glb": glb_url, "frames": urls,
            "frame_count": len(urls), "failed_azimuths": missing}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-run", help="eval RUNID whose GLBs are already in car-meshes/eval/")
    ap.add_argument("--case", help="case name to generate first (needs eval inputs uploaded)")
    ap.add_argument("--tags", default="", help="restrict to these GLB variants, e.g. cd,base")
    ap.add_argument("--frames", type=int, default=8)
    ap.add_argument("--samples", type=int, default=128)
    ap.add_argument("--width", type=int, default=800)
    ap.add_argument("--height", type=int, default=600)
    ap.add_argument("--workers", type=int, default=2, help="match the endpoint's workersMax")
    ap.add_argument("--out-prefix", default="generated")
    a = ap.parse_args()

    key, sb = os.environ.get("RUNPOD_API_KEY"), os.environ.get("SB_KEY")
    if not key or not sb:
        sys.exit("RUNPOD_API_KEY / SB_KEY missing from env")

    if a.case and not a.from_run:
        # generation half: the pod needs the volume, so it is a pod, not
        # serverless. It uploads GLBs and exits; we pick them up below.
        env = dict(os.environ, EVAL_CASES=a.case, EVAL_PIPE="1024_cascade", EVAL_ISOLATE="1")
        print(f"launching generation for case '{a.case}' ...", flush=True)
        r = subprocess.run([sys.executable, "-u", "pipeline/finetune/launch_pod.py",
                            "--script", "stage_c_eval_pod.sh", "--name", f"alam3d-gen-{a.case}",
                            "--tier", "render", "--hours", "2", "--hunt-hours", "1"],
                           env=env, capture_output=True, text=True)
        print(r.stdout[-2000:], flush=True)
        rid = None
        for line in r.stdout.splitlines():
            if "EVAL_RUN_ID" in line:
                rid = line.split()[-1]
        if not rid:
            sys.exit("generation finished but no EVAL_RUN_ID — nothing to render")
        a.from_run = rid
        print(f"generation produced run {rid}", flush=True)

    if not a.from_run:
        sys.exit("give --from-run RUNID or --case NAME")

    rows = [r for r in sb_list(sb, "car-meshes", f"eval/{a.from_run}")
            if r.get("id") is not None and r["name"].endswith(".glb")]
    want = [t for t in a.tags.split(",") if t]
    if want:
        rows = [r for r in rows if any(r["name"].endswith(f"_{t}.glb") for t in want)]
    if not rows:
        sys.exit(f"no GLBs under car-meshes/eval/{a.from_run}" + (f" matching {want}" if want else ""))
    print(f"rendering {len(rows)} GLB(s) from run {a.from_run}", flush=True)

    manifests, t0 = [], time.time()
    for r in rows:
        name = r["name"].replace(".glb", "")
        glb = f"{PUB}/car-meshes/eval/{a.from_run}/{r['name']}"
        manifests.append(turntable(glb, name, key, sb, a.frames, a.samples,
                                   a.width, a.height, a.workers, f"{a.out_prefix}/{a.from_run}"))

    man = {"run": a.from_run, "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "frames_per_model": a.frames, "models": manifests}
    sb_put(sb, "car-renders", f"{a.out_prefix}/{a.from_run}/manifest.json",
           json.dumps(man, indent=1).encode(), "application/json")
    ok = sum(m["frame_count"] for m in manifests)
    print(f"\nDONE in {(time.time()-t0)/60:.1f} min — {ok} frames across {len(manifests)} model(s)")
    print(f"manifest: {PUB}/car-renders/{a.out_prefix}/{a.from_run}/manifest.json")


if __name__ == "__main__":
    main()
