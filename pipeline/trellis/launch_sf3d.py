#!/usr/bin/env python3
"""launch_sf3d.py — one pod, N cars through Stable Fast 3D (or SPAR3D).

Same hardened pattern as launch_pixal_batch: stage inputs to the bucket,
PREFLIGHT the bootstrap URL before renting a GPU, watch the BUCKET LOG (never
desiredStatus), boot-watchdog a dead host, delete the pod on any terminal
marker and VERIFY it is gone.

Image is a CUDA **devel** image on purpose: SF3D compiles two custom CUDA
extensions (texture_baker, uv_unwrapper) at install time and needs nvcc. The
trellis2-worker image would also work but is ~30GB to pull for extensions we
do not use here.

SPAR3D: same driver. Point SF3D_REPO/SF3D_MODEL at the SPAR3D repo and model
id once that gate is granted for this account (measured 403 on 2026-08-19).

Usage: set -a; . /root/.alam3d_env; set +a
       python3 pipeline/trellis/launch_sf3d.py path/to/cutout_dir
"""
import json
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SB = "https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object"
PRE = os.environ.get("SF3D_PRE", "car-meshes/sf3d")
IMAGE = os.environ.get(
    "SF3D_IMAGE",
    "runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04")
REPO = os.environ.get("SF3D_REPO",
                      "https://github.com/Stability-AI/stable-fast-3d")
MODEL = os.environ.get("SF3D_MODEL", "stabilityai/stable-fast-3d")
OK_MARKER = "SF3D_OK"


def put(local, remote, sb_key):
    req = urllib.request.Request(
        f"{SB}/{PRE}/{remote}", data=open(local, "rb").read(), method="POST",
        headers={"apikey": sb_key, "Authorization": f"Bearer {sb_key}",
                 "x-upsert": "true",
                 "Content-Type": "application/octet-stream"})
    urllib.request.urlopen(req, timeout=180)


def preflight_gate(model, hf_token):
    """Prove the account can pull the weights BEFORE renting anything.

    The pod checks this too, but finding out here costs nothing at all —
    and a gated model is the single most likely reason this run cannot
    happen (SPAR3D is gated to this account today)."""
    req = urllib.request.Request(
        f"https://huggingface.co/{model}/resolve/main/model.safetensors",
        headers={"Authorization": f"Bearer {hf_token}", "Range": "bytes=0-1023"})
    try:
        code = urllib.request.urlopen(req, timeout=60).status
    except urllib.error.HTTPError as e:
        raise SystemExit(
            f"REFUSED: {model} weights are not readable by this account "
            f"(HTTP {e.code}). Accept the licence on "
            f"https://huggingface.co/{model} with the account that owns "
            f"HF_TOKEN, then re-run. Nothing was rented.")
    print(f"weights preflight {model} -> HTTP {code}")


def stage_inputs(cutout_dir, sb_key):
    import glob as _glob
    import tempfile as _tf
    tags = []
    for p in sorted(_glob.glob(os.path.join(cutout_dir, "*.png"))):
        tag = os.path.splitext(os.path.basename(p))[0]
        put(p, f"in_{tag}.png", sb_key)
        tags.append(tag)
        print(f"  uploaded {tag}")
    if not tags:
        raise SystemExit(f"no .png cutouts in {cutout_dir}")
    with _tf.NamedTemporaryFile("w", suffix=".json", delete=False) as bf:
        json.dump(tags, bf)
        bpath = bf.name
    put(bpath, "batch.json", sb_key)
    os.unlink(bpath)
    print(f"batch manifest: {tags}")
    put(os.path.join(HERE, "sf3d_boot.sh"), "sf3d_boot.sh", sb_key)
    put(os.path.join(HERE, "crease_density.py"), "crease_density.py", sb_key)
    with _tf.NamedTemporaryFile("w", suffix=".txt", delete=False) as tf:
        tf.write("=== STAGE:launching ===\n")
        tmplog = tf.name
    put(tmplog, "log.txt", sb_key)
    os.unlink(tmplog)

    url = f"{SB}/public/{PRE}/sf3d_boot.sh"
    if urllib.request.urlopen(url, timeout=30).status != 200:
        raise SystemExit("bootstrap preflight failed")
    print("bootstrap preflight OK")
    return url


def attempt(url, sb_key, n, total):
    key = os.environ["RUNPOD_API_KEY"]
    print(f"--- attempt {n}/{total}", flush=True)
    body = {
        "name": "sf3d-batch",
        "imageName": IMAGE,
        # SF3D needs ~11GB for the full model, so the pool can be cheap and
        # wide — availability beats picking one class and waiting on it.
        "gpuTypeIds": ["NVIDIA RTX A5000", "NVIDIA RTX A6000",
                       "NVIDIA GeForce RTX 4090", "NVIDIA GeForce RTX 3090",
                       "NVIDIA L40S", "NVIDIA A40",
                       "NVIDIA A100 80GB PCIe"],
        "gpuTypePriority": "availability",
        "gpuCount": 1, "containerDiskInGb": 60, "volumeInGb": 0,
        "cloudType": "SECURE",
        "dockerStartCmd": ["bash", "-c",
                           f"curl -sSL '{url}?cb='$(date +%s) | bash; "
                           "sleep infinity"],
        "env": {"SB_KEY": sb_key,
                "SF3D_PRE": PRE,
                "SF3D_REPO": REPO,
                "SF3D_MODEL": MODEL,
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
    print(f"sf3d pod {pod_id} launched; monitoring bucket log")
    import tempfile as _tf2
    with _tf2.NamedTemporaryFile("w", suffix=".txt", delete=False) as _tf3:
        _tf3.write("=== STAGE:launching ===\n")
        _p = _tf3.name
    put(_p, "log.txt", sb_key)
    os.unlink(_p)

    log_url = f"{SB}/public/{PRE}/log.txt"
    t0, last, ok = time.time(), "", False
    BOOT_LIMIT = float(os.environ.get("SF3D_BOOT_LIMIT_S", "900"))
    try:
        while time.time() - t0 < 7200:
            if (last in ("", "=== STAGE:launching ===")
                    and time.time() - t0 > BOOT_LIMIT):
                print(f"DEAD HOST: no progress past '{last or 'nothing'}' in "
                      f"{BOOT_LIMIT/60:.0f} min — killing pod {pod_id}",
                      flush=True)
                break
            try:
                log = urllib.request.urlopen(
                    f"{log_url}?cb={int(time.time())}", timeout=30
                ).read().decode("utf-8", "replace")
                lines = [l for l in log.splitlines() if l.startswith("=== ")]
                if lines and lines[-1] != last:
                    last = lines[-1]
                    print(f"  [{int(time.time()-t0)/60:.0f}m] {last}",
                          flush=True)
                if OK_MARKER in last:
                    ok = True
                    break
                if "FAIL" in last:
                    break
            except Exception:
                pass
            time.sleep(30)
        else:
            print("attempt hit the 2h ceiling", flush=True)
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
    if ok:
        return "ok"
    return "dead" if last in ("", "=== STAGE:launching ===") else "fail"


def main(cutout_dir):
    sb_key = os.environ["SB_KEY"]
    preflight_gate(MODEL, os.environ["HF_TOKEN"])
    tries = int(os.environ.get("SF3D_MAX_ATTEMPTS", "3"))
    url = stage_inputs(cutout_dir, sb_key)
    for n in range(1, tries + 1):
        verdict = attempt(url, sb_key, n, tries)
        print(f"attempt {n} verdict: {verdict}", flush=True)
        if verdict == "ok":
            print("SF3D RESULT: OK")
            return 0
        if verdict == "fail":
            print("SF3D RESULT: NOT OK (job failed — not a host fault)")
            return 1
        if n < tries:
            print("dead host — re-renting on a different machine\n", flush=True)
            time.sleep(20)
    print(f"SF3D RESULT: NOT OK ({tries} dead hosts in a row)")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
