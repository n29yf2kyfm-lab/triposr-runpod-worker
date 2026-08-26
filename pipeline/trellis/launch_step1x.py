#!/usr/bin/env python3
"""launch_step1x.py — launch + monitor a Step1X-3D GEOMETRY pod.

Same hardened pattern as launch_pilot5h: upload artefacts, reset the job log,
PREFLIGHT the bootstrap URL before renting a GPU, monitor the BUCKET LOG (never
desiredStatus), delete the pod on any terminal marker and verify it is gone.

Step1X-3D is stepfun-ai's Apache-2.0 image-to-3D model with PUBLIC ungated
weights (verified: the HF API reports gated=False, private=False, and ranged
reads of the real weight paths return 206).

BASE IMAGE IS A STOCK runpod/pytorch DEVEL IMAGE, not our trellis2 worker. This
model needs none of the TRELLIS.2 CUDA extensions, and it wants torch 2.5.1 while
that image ships 2.6.0 — the torch_cluster wheel index is per-torch-build, so
matching the pin matters more than reusing our extensions. devel is required
because `diso` may compile.

GEOMETRY ONLY. The texture stage is what drags in pytorch3d and nvdiffrast from
git (two source builds) plus kaolin and Hunyuan3D's custom rasterizer; the import
graph shows all four are referenced exclusively by step1x3d_texture. We have our
own material chain, so none of it is wanted.

Usage: set -a; . /root/.alam3d_env; set +a
       python3 pipeline/trellis/launch_pixal.py path/to/cutout.png \\
           [--prefix car-meshes/pixal_van] [--name van]

--prefix/--name EXIST BECAUSE THE DEFAULTS OVERWRITE. Every run used to land on
car-meshes/pixal_test/{golf.png,pixal_golf.glb}, so a second vehicle destroyed
the first one's input and mesh — and the literal "golf" has already cost an hour
of presenting a Yaris as a Golf (CLAUDE.md 2026-08-20). Give a new vehicle its
own prefix and name; the defaults preserve the original test-bed behaviour.
"""
import argparse
import json
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SB = "https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object"
PRE = "car-meshes/staging/step1x_van"
IMAGE = "runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04"


def put(local, remote, sb_key, pre=PRE):
    req = urllib.request.Request(
        f"{SB}/{pre}/{remote}", data=open(local, "rb").read(), method="POST",
        headers={"apikey": sb_key, "Authorization": f"Bearer {sb_key}",
                 "x-upsert": "true",
                 "Content-Type": "application/octet-stream"})
    urllib.request.urlopen(req, timeout=180)


def main(img, pre=PRE, name="van"):
    key = os.environ["RUNPOD_API_KEY"]
    sb_key = os.environ["SB_KEY"]
    in_name, out_name = f"{name}.png", f"step1x_{name}.glb"
    print(f"prefix {pre}  input {in_name}  output {out_name}")

    put(img, in_name, sb_key, pre)
    put(os.path.join(HERE, "step1x_boot.sh"), "step1x_boot.sh", sb_key, pre)
    
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as tf:
        tf.write("=== STAGE:launching ===\n")
        tmplog = tf.name
    put(tmplog, "log.txt", sb_key, pre)
    os.unlink(tmplog)

    # 200 alone is NOT a preflight: the public URL is CDN-cached and has served
    # a STALE boot script before (the Hi3DGen lesson -- the pod then executes
    # last run's code while the log looks normal). The standard is 200 AND
    # byte-identical to what we just uploaded.
    url = f"{SB}/public/{pre}/step1x_boot.sh"
    served = urllib.request.urlopen(url, timeout=30).read()
    local = open(os.path.join(HERE, "step1x_boot.sh"), "rb").read()
    if served != local:
        raise SystemExit(f"bootstrap preflight failed: served {len(served)}B != "
                         f"local {len(local)}B -- CDN is stale, do not rent a GPU")
    print(f"bootstrap preflight OK ({len(local)}B, byte-identical)")

    body = {
        "name": f"step1x3d-{name}",
        "imageName": IMAGE,
        "gpuTypeIds": ["NVIDIA A100 80GB PCIe", "NVIDIA A100-SXM4-80GB"],
        "gpuTypePriority": "availability",
        "gpuCount": 1, "containerDiskInGb": 120, "volumeInGb": 0,
        "cloudType": "SECURE",
        "dockerStartCmd": ["bash", "-c",
                           f"curl -sSL '{url}?cb='$(date +%s) | bash; "
                           "sleep infinity"],
        "env": {"SB_KEY": sb_key,
                "S1X_PRE": pre,
                "S1X_IN": in_name,
                "HF_TOKEN": os.environ.get("HF_TOKEN", ""),
                "HUGGING_FACE_HUB_TOKEN": os.environ.get("HF_TOKEN", ""),
                "HF_HOME": "/workspace/hf"},
    }
    req = urllib.request.Request(
        "https://rest.runpod.io/v1/pods", data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"})
    pod = json.load(urllib.request.urlopen(req, timeout=60))
    pod_id = pod.get("id")
    if not pod_id:
        raise SystemExit(f"pod launch failed: {pod}")
    print(f"step1x pod {pod_id} launched; monitoring bucket log")

    log_url = f"{SB}/public/{pre}/log.txt"
    t0, last, ok = time.time(), "", False
    try:
        while time.time() - t0 < 5400:          # 90 min hard stop
            try:
                log = urllib.request.urlopen(
                    f"{log_url}?cb={int(time.time())}", timeout=30
                ).read().decode("utf-8", "replace")
                lines = [l for l in log.splitlines() if l.startswith("=== ")]
                if lines and lines[-1] != last:
                    last = lines[-1]
                    print(f"  [{int(time.time()-t0)/60:.0f}m] {last}",
                          flush=True)
                if "STEP1X_OK" in last:
                    ok = True
                    break
                if "FAIL" in last:
                    break
            except Exception:
                pass
            time.sleep(60)
    finally:
        req = urllib.request.Request(
            f"https://rest.runpod.io/v1/pods/{pod_id}", method="DELETE",
            headers={"Authorization": f"Bearer {key}"})
        try:
            urllib.request.urlopen(req, timeout=60)
        except Exception as e:
            print(f"POD DELETE FAILED — kill {pod_id} by hand: {e}")
        else:
            time.sleep(10)
            try:
                chk = urllib.request.Request(
                    f"https://rest.runpod.io/v1/pods/{pod_id}",
                    headers={"Authorization": f"Bearer {key}"})
                urllib.request.urlopen(chk, timeout=30)
                print(f"WARNING: pod {pod_id} still answers — verify by hand")
            except Exception:
                print(f"pod {pod_id} deleted and gone")
    print("STEP1X RESULT:", "OK" if ok else f"NOT OK (last: {last})")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("image", help="RGBA cutout to generate from")
    ap.add_argument("--prefix", default=PRE, help="bucket prefix for this run")
    ap.add_argument("--name", default="van",
                    help="subject name; input <name>.png")
    a = ap.parse_args()
    sys.exit(main(a.image, a.prefix, a.name))
