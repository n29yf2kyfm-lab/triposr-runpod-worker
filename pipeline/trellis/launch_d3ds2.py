#!/usr/bin/env python3
"""launch_d3ds2.py — one pod, N conditioning images through Direct3D-S2.

Leg C of the sharpness experiment. Same hardened pattern as launch_sf3d: stage inputs
to the bucket, PREFLIGHT both the bootstrap URL and the weights gate before renting a
GPU, watch the BUCKET LOG (never desiredStatus), and delete the pod on every terminal
path then VERIFY it is gone.

TWO DELIBERATE DIFFERENCES FROM launch_sf3d, both for durability:

1. RUNPOD_API_KEY IS PASSED INTO THE POD so the in-pod fuse can actually delete the
   pod. CLAUDE.md records that the RunPod-INJECTED pod-scoped key could NOT delete its
   own pod via REST (the pc41 run survived its own finish() and needed an external
   kill), so the injected key is not sufficient. This is a real, stated exposure
   trade: the pod's env now carries the account key as well as SB_KEY and HF_TOKEN.
   It is accepted because the operator container running this launcher has restarted
   twice today and killed one predecessor outright, and an unwatched pod bills until
   someone notices — two orphans have already cost ~$3.30 here. NEVER print a pod's
   raw JSON: /v1/pods/<id> returns the env block inline.

2. A HARD IN-POD CEILING (D3D_MAXSEC). The launcher's own watchdog dies with the
   launcher; the pod-side `sleep MAX && self-destruct` does not.

Usage: set -a; . /root/.alam3d_env; set +a
       python3 pipeline/trellis/launch_d3ds2.py IMG_DIR
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SB = "https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object"
PRE = os.environ.get("D3D_PRE", "car-meshes/staging/direct3d")
IMAGE = os.environ.get(
    "D3D_IMAGE", "runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04")
MAXSEC = os.environ.get("D3D_MAXSEC", "3000")
OK_MARKER = "D3DS2_OK"
WEIGHT_FILE = "direct3d-s2-v-1-1/model_sparse_1024.ckpt"


def put(local, remote, sb_key):
    req = urllib.request.Request(
        f"{SB}/{PRE}/{remote}", data=open(local, "rb").read(), method="POST",
        headers={"apikey": sb_key, "Authorization": f"Bearer {sb_key}",
                 "x-upsert": "true", "Content-Type": "application/octet-stream"})
    urllib.request.urlopen(req, timeout=300)


def preflight_weights(hf_token):
    req = urllib.request.Request(
        f"https://huggingface.co/wushuang98/Direct3D-S2/resolve/main/{WEIGHT_FILE}",
        headers={"Authorization": f"Bearer {hf_token}", "Range": "bytes=0-1023"})
    try:
        code = urllib.request.urlopen(req, timeout=60).status
    except urllib.error.HTTPError as e:
        raise SystemExit(
            f"REFUSED: Direct3D-S2 weights not readable (HTTP {e.code}). "
            f"Nothing was rented.")
    print(f"weights preflight -> HTTP {code}")


def stage_inputs(img_dir, sb_key):
    import glob as _glob
    import tempfile as _tf
    tags = []
    for p in sorted(_glob.glob(os.path.join(img_dir, "*.png"))):
        tag = os.path.splitext(os.path.basename(p))[0]
        put(p, f"in_{tag}.png", sb_key)
        tags.append(tag)
        print(f"  staged {tag}")
    if not tags:
        raise SystemExit(f"no .png conditioning images in {img_dir}")
    with _tf.NamedTemporaryFile("w", suffix=".json", delete=False) as bf:
        json.dump(tags, bf)
        bpath = bf.name
    put(bpath, "batch.json", sb_key)
    os.unlink(bpath)
    put(os.path.join(HERE, "d3ds2_boot.sh"), "d3ds2_boot.sh", sb_key)
    put(os.path.join(HERE, "crease_density.py"), "crease_density.py", sb_key)
    with _tf.NamedTemporaryFile("w", suffix=".txt", delete=False) as tf:
        tf.write("=== STAGE:launching ===\n")
        tmplog = tf.name
    put(tmplog, "log.txt", sb_key)
    os.unlink(tmplog)

    # PREFLIGHT THE BOOTSTRAP URL. A mangled URL once 400'd, curl failed, `&&`
    # short-circuited, the bootstrap never ran, and it was misdiagnosed as slow image
    # pulls across two runs.
    url = f"{SB}/public/{PRE}/d3ds2_boot.sh"
    code = urllib.request.urlopen(url, timeout=30).status
    if code != 200:
        raise SystemExit(f"bootstrap preflight failed: HTTP {code}")
    body = urllib.request.urlopen(url, timeout=30).read()
    if b"D3DS2_OK" not in body:
        raise SystemExit("bootstrap fetched but content looks wrong")
    print(f"bootstrap preflight OK ({len(body)} bytes)")
    print(f"manifest: {tags}")
    return url


def delete_pod(pod_id, key):
    try:
        urllib.request.urlopen(urllib.request.Request(
            f"https://rest.runpod.io/v1/pods/{pod_id}", method="DELETE",
            headers={"Authorization": f"Bearer {key}"}), timeout=60)
    except Exception as e:
        print(f"  delete call raised: {type(e).__name__}: {e}")
    time.sleep(10)
    # VERIFY it is gone. A delete that returned 200 is not proof.
    try:
        urllib.request.urlopen(urllib.request.Request(
            f"https://rest.runpod.io/v1/pods/{pod_id}",
            headers={"Authorization": f"Bearer {key}"}), timeout=30)
    except urllib.error.HTTPError as e:
        if e.code in (404, 400):
            print(f"pod {pod_id} deleted and gone (HTTP {e.code})")
            return True
        print(f"WARNING: pod {pod_id} query HTTP {e.code} — verify by hand")
    except Exception as e:
        print(f"pod {pod_id} unreachable ({type(e).__name__}) — assume gone")
        return True
    else:
        print(f"WARNING: pod {pod_id} STILL ANSWERS — kill it by hand")
    return False


def attempt(url, sb_key, n, total, gpus, disk):
    key = os.environ["RUNPOD_API_KEY"]
    print(f"--- attempt {n}/{total} disk={disk}GB", flush=True)
    body = {
        "name": "d3ds2-legc",
        "imageName": IMAGE,
        "gpuTypeIds": gpus,
        "gpuTypePriority": "availability",
        "gpuCount": 1, "containerDiskInGb": disk, "volumeInGb": 0,
        "cloudType": "SECURE",
        # MUST NOT EXIT: a dockerStartCmd that returns gets the pod RESTARTED into an
        # infinite re-clone loop. The bootstrap self-destructs instead of exiting.
        "dockerStartCmd": ["bash", "-c",
                           f"curl -sSL '{url}?cb='$(date +%s) | bash; sleep infinity"],
        "env": {"SB_KEY": sb_key,
                "D3D_PRE": PRE,
                "D3D_MAXSEC": MAXSEC,
                "HF_TOKEN": os.environ.get("HF_TOKEN", ""),
                "HUGGING_FACE_HUB_TOKEN": os.environ.get("HF_TOKEN", ""),
                "HF_HOME": "/workspace/hf",
                # see module docstring: needed for the in-pod fuse to actually delete
                "RUNPOD_API_KEY": key},
    }
    req = urllib.request.Request(
        "https://rest.runpod.io/v1/pods", data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"})
    try:
        pod = json.load(urllib.request.urlopen(req, timeout=90))
    except urllib.error.HTTPError as e:
        msg = e.read().decode()[:300]
        print(f"pod create HTTP {e.code}: {msg}")
        return "nohost", None
    pod_id = pod.get("id")
    if not pod_id:
        print("pod launch returned no id")
        return "nohost", None
    print(f"pod {pod_id} launched (in-pod fuse {MAXSEC}s); watching bucket log",
          flush=True)

    log_url = f"{SB}/public/{PRE}/log.txt"
    t0, last, ok = time.time(), "", False
    BOOT_LIMIT = float(os.environ.get("D3D_BOOT_LIMIT_S", "900"))
    CEILING = float(MAXSEC) + 600
    try:
        while time.time() - t0 < CEILING:
            if (last in ("", "=== STAGE:launching ===")
                    and time.time() - t0 > BOOT_LIMIT):
                print(f"DEAD HOST: no progress in {BOOT_LIMIT/60:.0f} min", flush=True)
                break
            try:
                log = urllib.request.urlopen(
                    f"{log_url}?cb={int(time.time())}", timeout=30
                ).read().decode("utf-8", "replace")
                lines = [l for l in log.splitlines() if l.startswith("=== ")]
                if lines and lines[-1] != last:
                    last = lines[-1]
                    print(f"  [{(time.time()-t0)/60:.1f}m] {last}", flush=True)
                if OK_MARKER in log:
                    ok = True
                    break
                if "=== FAIL" in last or "TIMED_OUT" in last:
                    break
            except Exception:
                pass
            time.sleep(20)
        else:
            print("watcher hit its ceiling — TIMED_OUT (not silence)", flush=True)
    finally:
        delete_pod(pod_id, key)
    if ok:
        return "ok", pod_id
    return ("dead", pod_id) if last in ("", "=== STAGE:launching ===") else ("fail", pod_id)


def main(img_dir):
    sb_key = os.environ["SB_KEY"]
    preflight_weights(os.environ["HF_TOKEN"])
    url = stage_inputs(img_dir, sb_key)
    # 48GB cards first: the README says 1024 needs "around 24GB", and "around" on a
    # 24GB card is how an OOM at the last stage costs the whole run.
    gpus = ["NVIDIA A40", "NVIDIA RTX A6000", "NVIDIA L40S",
            "NVIDIA GeForce RTX 4090"]
    tries = int(os.environ.get("D3D_MAX_ATTEMPTS", "2"))
    disk = int(os.environ.get("D3D_DISK", "50"))
    for n in range(1, tries + 1):
        verdict, _ = attempt(url, sb_key, n, tries, gpus, disk)
        print(f"attempt {n} verdict: {verdict}", flush=True)
        if verdict == "ok":
            print("D3DS2 RESULT: OK")
            return 0
        if verdict == "fail":
            print("D3DS2 RESULT: NOT OK (job failed — read log.txt in the bucket)")
            return 1
        if verdict == "nohost":
            # 500 "machine does not have the resources" is usually the disk ask.
            disk = 40
        if n < tries:
            print("retrying on another host\n", flush=True)
            time.sleep(20)
    print("D3DS2 RESULT: NOT OK (no usable host)")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
