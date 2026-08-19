#!/usr/bin/env python3
"""launch_pixal_batch.py — one pod, MANY cars through Pixal3D.

Boot + deps (~3 min) and the ~10GB weight cache are paid ONCE for the whole
batch instead of per car, and every car uploads its own result the moment it
finishes, so a late failure cannot lose earlier cars. Usage takes a directory
of RGBA cutouts named <tag>.png.

(derived from launch_pixal.py)

Same hardened pattern as launch_pilot5h: upload artefacts, reset the job log,
PREFLIGHT the bootstrap URL before renting a GPU, monitor the BUCKET LOG (never
desiredStatus), delete the pod on any terminal marker and verify it is gone.

Base image is our own trellis2-worker-4b (template i1mk2n9dap), which already
carries the TRELLIS.2 CUDA extensions Pixal3D needs.

Usage: set -a; . /root/.alam3d_env; set +a
       python3 pipeline/trellis/launch_pixal_batch.py path/to/cutout_dir
"""
import json
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SB = "https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object"
PRE = os.environ.get("PIXAL_PRE", "car-meshes/pixal_batch")
IMAGE = ("alamk123/ai-mechanic@sha256:"
         "5c5b87edd06cb105d914b9d4c9341411736520ff13045a8d281ce6209709a2bf")


def put(local, remote, sb_key):
    req = urllib.request.Request(
        f"{SB}/{PRE}/{remote}", data=open(local, "rb").read(), method="POST",
        headers={"apikey": sb_key, "Authorization": f"Bearer {sb_key}",
                 "x-upsert": "true",
                 "Content-Type": "application/octet-stream"})
    urllib.request.urlopen(req, timeout=180)


def stage_inputs(golf_png, sb_key):
    """Upload cutouts + manifest + bootstrap ONCE; reused by every attempt."""

    import glob as _glob
    tags = []
    for p in sorted(_glob.glob(os.path.join(golf_png, "*.png"))):
        tag = os.path.splitext(os.path.basename(p))[0]
        put(p, f"in_{tag}.png", sb_key)
        tags.append(tag)
        print(f"  uploaded {tag}")
    if not tags:
        raise SystemExit(f"no .png cutouts in {golf_png}")
    import tempfile as _tf
    with _tf.NamedTemporaryFile("w", suffix=".json", delete=False) as bf:
        json.dump(tags, bf)
        bpath = bf.name
    put(bpath, "batch.json", sb_key)
    os.unlink(bpath)
    print(f"batch manifest: {tags}")
    put(os.path.join(HERE, "pixal_batch.sh"), "pixal_batch.sh", sb_key)
    put(os.path.join(HERE, "crease_density.py"), "crease_density.py", sb_key)
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as tf:
        tf.write("=== STAGE:launching ===\n")
        tmplog = tf.name
    put(tmplog, "log.txt", sb_key)
    os.unlink(tmplog)

    url = f"{SB}/public/{PRE}/pixal_batch.sh"
    if urllib.request.urlopen(url, timeout=30).status != 200:
        raise SystemExit("bootstrap preflight failed")
    print("bootstrap preflight OK")
    return url


def attempt(url, sb_key, n, total):
    """Rent a pod, watch it, return "ok" | "dead" | "fail".

    "dead" means the host never ran the bootstrap — that is a HOST fault, not
    a job fault, so the supervisor re-rents rather than giving up."""
    key = os.environ["RUNPOD_API_KEY"]
    print(f"--- attempt {n}/{total}", flush=True)
    body = {
        "name": "pixal3d-batch",
        "imageName": IMAGE,
        # WIDER POOL: two dead A100 hosts in a row on 2026-08-19 stalled the
        # batch twice. Every card here is >=48GB and the bootstrap already
        # falls back low_vram 1536 -> 1024, so availability beats picking one
        # class and waiting on it.
        "gpuTypeIds": ["NVIDIA A100 80GB PCIe", "NVIDIA A100-SXM4-80GB",
                       "NVIDIA H100 80GB HBM3", "NVIDIA H100 PCIe",
                       "NVIDIA L40S", "NVIDIA RTX A6000"],
        "gpuTypePriority": "availability",
        "gpuCount": 1, "containerDiskInGb": 120, "volumeInGb": 0,
        "cloudType": "SECURE",
        "dockerStartCmd": ["bash", "-c",
                           f"curl -sSL '{url}?cb='$(date +%s) | bash; "
                           "sleep infinity"],
        "env": {"SB_KEY": sb_key,
                # the pod must resolve the SAME prefix the launcher used, or
                # it fetches a manifest that is not there and reports the
                # failure to a log nobody is watching (the 2026-08-19 bug)
                "PIXAL_PRE": PRE,
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
    print(f"pixal pod {pod_id} launched; monitoring bucket log")
    # reset the marker log for THIS attempt — a leftover marker from the
    # previous pod would make a dead host look alive (the stale-heartbeat
    # trap this project already paid for on the Hi3DGen runs)
    import tempfile as _tf2
    with _tf2.NamedTemporaryFile("w", suffix=".txt", delete=False) as _tf3:
        _tf3.write("=== STAGE:launching ===\n")
        _p = _tf3.name
    put(_p, "log.txt", sb_key)
    os.unlink(_p)

    log_url = f"{SB}/public/{PRE}/log.txt"
    t0, last, ok = time.time(), "", False
    # BOOT WATCHDOG. A dead host reports desiredStatus RUNNING with runtime
    # None forever — measured 2026-08-19: 26 min stuck at "launching", $0.69
    # burned, and only a human noticed. If the bootstrap has not moved past
    # "launching" within BOOT_LIMIT the host is dead: kill it and say so,
    # rather than renting silence. (Poll PROGRESS, never desire.)
    BOOT_LIMIT = float(os.environ.get("PIXAL_BOOT_LIMIT_S", "600"))
    try:
        while time.time() - t0 < 14400:   # batch: up to 4h
            if (last in ("", "=== STAGE:launching ===")
                    and time.time() - t0 > BOOT_LIMIT):
                print(f"DEAD HOST: no progress past '{last or 'nothing'}' in "
                      f"{BOOT_LIMIT/60:.0f} min — killing pod {pod_id}; "
                      "relaunch to land on a different host.", flush=True)
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
                if "PIXAL_OK" in last:
                    ok = True
                    break
                if "FAIL" in last:
                    break
            except Exception:
                pass
            time.sleep(60)
        else:
            print("attempt hit the 4h ceiling", flush=True)
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
    # a host that never ran the bootstrap is a HOST fault — retryable.
    # anything else (an actual FAIL marker) is the job's own fault — final.
    return "dead" if last in ("", "=== STAGE:launching ===") else "fail"


def main(cutout_dir):
    sb_key = os.environ["SB_KEY"]
    tries = int(os.environ.get("PIXAL_MAX_ATTEMPTS", "3"))
    url = stage_inputs(cutout_dir, sb_key)
    for n in range(1, tries + 1):
        verdict = attempt(url, sb_key, n, tries)
        print(f"attempt {n} verdict: {verdict}", flush=True)
        if verdict == "ok":
            print("PIXAL RESULT: OK")
            return 0
        if verdict == "fail":
            print("PIXAL RESULT: NOT OK (job failed — not a host fault)")
            return 1
        if n < tries:
            print("dead host — re-renting on a different machine\n", flush=True)
            time.sleep(20)
    print(f"PIXAL RESULT: NOT OK ({tries} dead hosts in a row — "
          "check RunPod capacity for A100 SECURE)")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
