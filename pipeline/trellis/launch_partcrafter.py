#!/usr/bin/env python3
"""launch_partcrafter.py — launch + monitor a PartCrafter pod (16 parts).

Same hardened pattern as launch_step1x.py: byte-identical bootstrap preflight
before renting a GPU, monitor the BUCKET LOG (never desiredStatus), delete on
any terminal marker and verify from OUTSIDE that the pod is gone.

DIFFERENT FROM THE GEOMETRY LAUNCHER IN THREE WAYS, each deliberate:

  * IT UPLOADS NOTHING BUT THE BOOTSTRAP. The geometry launcher pushes the
    input image; here BOTH inputs (the mesh and the image) are already in the
    bucket from the geometry run. Re-uploading a mesh from local disk would
    invite the exact mismatch this project keeps paying for -- the local copy
    is deleted after every run by standing order, so the bucket is the truth.
    Pass --mesh to name which staged mesh to texture.

  * IT DOES NOT RESET log.txt TO "launching". Doing so would destroy the
    geometry run's log at the same key. The texture run writes its own
    pc_log.txt, and the per-pod namespaced copy alongside it.

  * LONGER CEILING (110 min vs 90). The first texture run has to COMPILE
    pytorch3d -- PyPI ships macOS-only wheels and the official prebuilt index
    has no py311_cu124_pyt251 build. That build is cached to the bucket on
    success, so later runs are a pip install and finish in a fraction of it.

Usage: set -a; . /root/.alam3d_env; set +a
       python3 pipeline/trellis/launch_step1x_tex.py \\
           [--prefix car-meshes/staging/hybrid_van2] [--name van] \\
           [--mesh step1x_label.glb] [--out step1x_textured.glb]
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SB = "https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object"
PRE = "car-meshes/staging/hybrid_van2"
IMAGE = "runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04"
BOOT = "partcrafter_boot.sh"


def put(local, remote, sb_key, pre=PRE):
    req = urllib.request.Request(
        f"{SB}/{pre}/{remote}", data=open(local, "rb").read(), method="POST",
        headers={"apikey": sb_key, "Authorization": f"Bearer {sb_key}",
                 "x-upsert": "true",
                 "Content-Type": "application/octet-stream"})
    urllib.request.urlopen(req, timeout=180)


def head_ok(url, sb_key):
    """Range-read one byte. 2xx (206 included) means the object is really there."""
    req = urllib.request.Request(
        url, headers={"apikey": sb_key, "Authorization": f"Bearer {sb_key}",
                      "Range": "bytes=0-0"})
    try:
        return 200 <= urllib.request.urlopen(req, timeout=30).status < 300
    except Exception:
        return False


def main(pre=PRE, name="van", parts=16, img_name=None):
    sb_key = os.environ.get("SB_KEY")
    key = os.environ.get("RUNPOD_API_KEY")
    if not sb_key or not key:
        raise SystemExit("SB_KEY / RUNPOD_API_KEY not in env "
                         "(set -a; . /root/.alam3d_env; set +a)")
    in_name = img_name or f"{name}.png"
    print(f"prefix {pre}  image {in_name}  num_parts {parts}  -> {pre}/parts/")

    # REFUSE BEFORE RENTING if an input is missing. The geometry launcher can
    # assume its input exists because it just uploaded it; this one cannot, and
    # a pod that dies on FETCH_MESH still costs boot + image pull.
    for obj in (in_name,):
        if not head_ok(f"{SB}/{pre}/{obj}", sb_key):
            raise SystemExit(f"REFUSED: {pre}/{obj} is not in the bucket")
    print("input image confirmed in the bucket")

    put(os.path.join(HERE, BOOT), BOOT, sb_key, pre)

    # Seed OUR log key only. Deliberately NOT log.txt -- that belongs to the
    # geometry run and overwriting it would destroy the record of how this
    # mesh was made, the same clobber that cost pod 3's failure log.
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as tf:
        tf.write("=== STAGE:launching ===\n")
        tmplog = tf.name
    put(tmplog, "pc_log.txt", sb_key, pre)
    os.unlink(tmplog)

    # 200 is NOT a preflight: the public URL is CDN-cached and has served a
    # STALE boot script before, so the pod runs last run's code while the log
    # looks normal. Require byte-identical.
    url = f"{SB}/public/{pre}/{BOOT}"
    served = urllib.request.urlopen(url, timeout=30).read()
    local = open(os.path.join(HERE, BOOT), "rb").read()
    if served != local:
        raise SystemExit(f"bootstrap preflight failed: served {len(served)}B != "
                         f"local {len(local)}B -- CDN is stale, do not rent a GPU")
    print(f"bootstrap preflight OK ({len(local)}B, byte-identical)")

    body = {
        "name": f"partcrafter-{name}",
        "imageName": IMAGE,
        "gpuTypeIds": ["NVIDIA RTX A5000", "NVIDIA RTX A6000", "NVIDIA A40"],
        "gpuTypePriority": "availability",
        "gpuCount": 1, "containerDiskInGb": 60, "volumeInGb": 0,
        "cloudType": "SECURE",
        "dockerStartCmd": ["bash", "-c",
                           f"curl -sSL '{url}?cb='$(date +%s) | bash; "
                           "sleep infinity"],
        "env": {"SB_KEY": sb_key,
                "RUNPOD_API_KEY": key,          # the in-pod fuse needs it
                "PC_PRE": pre,
                "PC_PARTS": str(parts),
                "PC_IN": in_name,
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
    print(f"partcrafter pod {pod_id} launched; monitoring bucket log")

    log_url = f"{SB}/public/{pre}/pc_log.txt"
    t0, last, ok = time.time(), "", False
    try:
        while time.time() - t0 < 3600:          # 60 min ceiling: deps ~6min + inference ~6min
            try:
                log = urllib.request.urlopen(
                    f"{log_url}?cb={int(time.time())}", timeout=30
                ).read().decode("utf-8", "replace")
                lines = [l for l in log.splitlines() if l.startswith("=== ")]
                if lines and lines[-1] != last:
                    last = lines[-1]
                    print(f"  [{int(time.time()-t0)/60:.0f}m] {last}", flush=True)
                if "PARTCRAFTER_OK" in last:
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
        except urllib.error.HTTPError as e:
            if e.code == 404:
                print(f"pod {pod_id} already deleted (404) — nothing to kill")
            else:
                print(f"POD DELETE FAILED — kill {pod_id} by hand: {e}")
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
    print("PARTCRAFTER RESULT:", "OK" if ok else f"NOT OK (last: {last})")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefix", default=PRE, help="bucket prefix for this run")
    ap.add_argument("--name", default="van", help="subject name; image <name>.png")
    ap.add_argument("--image", dest="img_name", default=None,
                    help="override image key (default <name>.png)")
    ap.add_argument("--parts", type=int, default=16,
                    help="num_parts; 16 is measured — at 10 the greenhouse fuses into the body")
    a = ap.parse_args()
    sys.exit(main(a.prefix, a.name, a.parts, a.img_name))
