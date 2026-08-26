#!/usr/bin/env python3
"""launch_pixal.py — launch + monitor the Pixal3D gated test pod.

Same hardened pattern as launch_pilot5h: upload artefacts, reset the job log,
PREFLIGHT the bootstrap URL before renting a GPU, monitor the BUCKET LOG (never
desiredStatus), delete the pod on any terminal marker and verify it is gone.

Base image is our own trellis2-worker-4b (template i1mk2n9dap), which already
carries the TRELLIS.2 CUDA extensions Pixal3D needs.

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
PRE = "car-meshes/pixal_test"
IMAGE = ("alamk123/ai-mechanic@sha256:"
         "5c5b87edd06cb105d914b9d4c9341411736520ff13045a8d281ce6209709a2bf")


def put(local, remote, sb_key, pre=PRE):
    req = urllib.request.Request(
        f"{SB}/{pre}/{remote}", data=open(local, "rb").read(), method="POST",
        headers={"apikey": sb_key, "Authorization": f"Bearer {sb_key}",
                 "x-upsert": "true",
                 "Content-Type": "application/octet-stream"})
    urllib.request.urlopen(req, timeout=180)


def main(golf_png, pre=PRE, name="golf"):
    key = os.environ["RUNPOD_API_KEY"]
    sb_key = os.environ["SB_KEY"]
    in_name, out_name = f"{name}.png", f"pixal_{name}.glb"
    print(f"prefix {pre}  input {in_name}  output {out_name}")

    put(golf_png, in_name, sb_key, pre)
    put(os.path.join(HERE, "pixal_boot.sh"), "pixal_boot.sh", sb_key, pre)
    put(os.path.join(HERE, "crease_density.py"), "crease_density.py", sb_key, pre)
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as tf:
        tf.write("=== STAGE:launching ===\n")
        tmplog = tf.name
    put(tmplog, "log.txt", sb_key, pre)
    os.unlink(tmplog)

    url = f"{SB}/public/{pre}/pixal_boot.sh"
    if urllib.request.urlopen(url, timeout=30).status != 200:
        raise SystemExit("bootstrap preflight failed")
    print("bootstrap preflight OK")

    body = {
        "name": f"pixal3d-{name}",
        "imageName": IMAGE,
        "gpuTypeIds": ["NVIDIA A100 80GB PCIe", "NVIDIA A100-SXM4-80GB"],
        "gpuTypePriority": "availability",
        "gpuCount": 1, "containerDiskInGb": 120, "volumeInGb": 0,
        "cloudType": "SECURE",
        "dockerStartCmd": ["bash", "-c",
                           f"curl -sSL '{url}?cb='$(date +%s) | bash; "
                           "sleep infinity"],
        "env": {"SB_KEY": sb_key,
                "PIXAL_PRE": pre,
                "PIXAL_IN": in_name,
                "PIXAL_OUT": out_name,
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
                if "PIXAL_OK" in last:
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
    print("PIXAL RESULT:", "OK" if ok else f"NOT OK (last: {last})")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("image", help="RGBA cutout to generate from")
    ap.add_argument("--prefix", default=PRE, help="bucket prefix for this run")
    ap.add_argument("--name", default="golf",
                    help="vehicle name; input <name>.png, output pixal_<name>.glb")
    a = ap.parse_args()
    sys.exit(main(a.image, a.prefix, a.name))
