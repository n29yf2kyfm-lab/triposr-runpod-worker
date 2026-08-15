#!/usr/bin/env python3
"""launch_pilot5h.py — launch + monitor the 5h fine-tune experiment pod.

Follows the carglb.run_shape_pod pattern exactly: upload artefacts, RESET the
job log, preflight the bootstrap URL before renting a GPU, create the pod via
REST with an availability-ordered GPU list, monitor the BUCKET LOG (never
desiredStatus), and delete the pod on completion/timeout with verification.

Usage: set -a; . /root/.alam3d_env; set +a
       python3 pipeline/trellis/launch_pilot5h.py cars.txt
"""
import json
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SB = "https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object"
PRE = "car-meshes/hy21_train/pilot5h"


def put(local, remote, sb_key):
    req = urllib.request.Request(
        f"{SB}/{PRE}/{remote}", data=open(local, "rb").read(), method="POST",
        headers={"apikey": sb_key, "Authorization": f"Bearer {sb_key}",
                 "x-upsert": "true",
                 "Content-Type": "application/octet-stream"})
    urllib.request.urlopen(req, timeout=120)


def main(cars_file):
    key = os.environ["RUNPOD_API_KEY"]
    sb_key = os.environ["SB_KEY"]

    put(cars_file, "cars.txt", sb_key)
    put(os.path.join(HERE, "hy21_render.py"), "hy21_render.py", sb_key)
    put(os.path.join(HERE, "hy21_pilot5h.sh"), "hy21_pilot5h.sh", sb_key)
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as tf:
        tf.write("=== STAGE:launching ===\n")
        tmplog = tf.name
    put(tmplog, "log.txt", sb_key)
    os.unlink(tmplog)

    url = f"{SB}/public/{PRE}/hy21_pilot5h.sh"
    if urllib.request.urlopen(url, timeout=30).status != 200:
        raise SystemExit("bootstrap preflight failed")
    print("bootstrap preflight OK")

    body = {
        "name": "alam3d-v2-pilot5h",
        "imageName": "runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04",
        # A100 80GB ONLY: at H100 rates 5.5h can exhaust the current balance
        # mid-train — RunPod kills the pod at zero and the checkpoint is lost.
        "gpuTypeIds": ["NVIDIA A100 80GB PCIe", "NVIDIA A100-SXM4-80GB"],
        "gpuTypePriority": "availability",
        "gpuCount": 1, "containerDiskInGb": 150, "volumeInGb": 0,
        "cloudType": "SECURE",
        "dockerStartCmd": ["bash", "-c",
                           f"curl -sSL '{url}?cb='$(date +%s) | bash; "
                           "sleep infinity"],
        "env": {"SB_KEY": sb_key,
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
    print(f"pilot pod {pod_id} launched; monitoring bucket log")

    log_url = f"{SB}/public/{PRE}/log.txt"
    t0, last, ok = time.time(), "", False
    try:
        while time.time() - t0 < 20400:          # 5h40 hard stop
            try:
                log = urllib.request.urlopen(
                    f"{log_url}?cb={int(time.time())}", timeout=30
                ).read().decode("utf-8", "replace")
                lines = [l for l in log.splitlines() if l.startswith("=== ")]
                if lines and lines[-1] != last:
                    last = lines[-1]
                    print(f"  [{int(time.time()-t0)/60:.0f}m] {last}",
                          flush=True)
                if "PILOT_OK" in last:
                    ok = True
                    break
                if "FAIL" in last:
                    break
            except Exception:
                pass
            time.sleep(120)
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
    print("PILOT RESULT:", "OK" if ok else f"NOT OK (last: {last})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
