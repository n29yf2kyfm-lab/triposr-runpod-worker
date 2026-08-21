#!/usr/bin/env python3
"""launch_sparseflex.py — one pod, one car, through the TripoSF/SparseFlex VAE.

LEG A of the representation-vs-generation experiment. See sparseflex_boot.sh
for what the run is FOR; this file is only the harness around it.

Everything here is a scar from this repo's pod history, so nothing is
decorative:
  * PREFLIGHT the bootstrap URL and the weights BEFORE renting. A mangled URL
    once 400'd, curl failed, `&&` short-circuited, the bootstrap never ran, and
    it was misdiagnosed as slow image pulls across two runs.
  * The pod fetches its bootstrap through the AUTHED endpoint. The public CDN
    has served a STALE boot script to a pod before.
  * POLL PROGRESS, NOT DESIRE. `desiredStatus` reads RUNNING straight through
    an infinite restart loop. This prints runtime.uptimeInSeconds and
    gpuUtilPercent every tick; uptime RESETTING while the wall clock climbs IS
    the restart loop, and GPU at 0% means nothing is computing.
  * The watcher is bounded and says so: it prints a distinct TIMED_OUT marker
    on fall-through, because a bounded `for i in $(seq ...)` that expires
    silently is a countdown, not a monitor.
  * The pod is deleted on EVERY terminal path in a `finally:`, and then
    RE-QUERIED to prove it is gone. Two orphans have billed ~$3.30 here.
  * The bootstrap ALSO carries its own fuse, because the operator's container
    has died mid-run and a fuse is the only ceiling that survives that.

Never print the pod's raw JSON: GET /v1/pods/<id> returns the env INLINE, and
that env carries SB_KEY, HF_TOKEN and (here) RUNPOD_API_KEY. This file only
ever prints named scalar fields.

Usage: set -a; . /root/.alam3d_env; set +a
       python3 pipeline/trellis/launch_sparseflex.py
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SB = "https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object"
PRE = os.environ.get("ST_PRE", "car-meshes/staging/sharptest")
RUN = os.environ.get("ST_RUN", "runA")
IMAGE = os.environ.get(
    "ST_IMAGE", "runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04")
OK_MARKER = "SPARSEFLEX_OK"
# 24GB is the documented floor for 1024^3 headroom (the README asks >=12GB).
GPUS = ["NVIDIA GeForce RTX 3090", "NVIDIA RTX A6000",
        "NVIDIA GeForce RTX 4090", "NVIDIA A40", "NVIDIA L40"]


def _hdr(key):
    return {"apikey": key, "Authorization": f"Bearer {key}"}


def put(local, remote, key, ctype="application/octet-stream"):
    h = _hdr(key)
    h.update({"x-upsert": "true", "Content-Type": ctype})
    req = urllib.request.Request(f"{SB}/{PRE}/{remote}",
                                 data=open(local, "rb").read(),
                                 method="POST", headers=h)
    code = urllib.request.urlopen(req, timeout=300).status
    print(f"  staged {remote} -> {code}")


def get_text(remote, key, timeout=30):
    req = urllib.request.Request(
        f"{SB}/{PRE}/{remote}?cb={int(time.time())}", headers=_hdr(key))
    return urllib.request.urlopen(req, timeout=timeout).read().decode(
        "utf-8", "replace")


def preflight(key, hf):
    """Prove the two things that can make the whole run impossible, for free."""
    req = urllib.request.Request(
        "https://huggingface.co/VAST-AI/TripoSF/resolve/main/vae/"
        "pretrained_TripoSFVAE_256i1024o.safetensors",
        headers={"Authorization": f"Bearer {hf}", "Range": "bytes=0-1023"})
    code = urllib.request.urlopen(req, timeout=60).status
    if code not in (200, 206):
        raise SystemExit(f"REFUSED: weights preflight HTTP {code}")
    print(f"weights preflight -> HTTP {code}")

    # The EXACT url and headers the pod will use, not an equivalent one.
    req = urllib.request.Request(f"{SB}/{PRE}/sparseflex_boot.sh",
                                 headers=_hdr(key))
    body = urllib.request.urlopen(req, timeout=60).read()
    if b"SPARSEFLEX_OK" not in body:
        raise SystemExit("REFUSED: bootstrap fetched but content is wrong")
    print(f"bootstrap preflight -> HTTP 200, {len(body)} bytes, marker present")


def pod_state(pod_id, key):
    """Named scalars only — the raw record carries every secret in env."""
    req = urllib.request.Request(f"https://rest.runpod.io/v1/pods/{pod_id}",
                                 headers={"Authorization": f"Bearer {key}"})
    d = json.load(urllib.request.urlopen(req, timeout=30))
    rt = d.get("runtime") or {}
    gpus = rt.get("gpus") or [{}]
    return {"desired": d.get("desiredStatus"),
            "uptime": rt.get("uptimeInSeconds"),
            "gpu_pct": gpus[0].get("gpuUtilPercent"),
            "cost": d.get("costPerHr")}


def delete_pod(pod_id, key):
    try:
        urllib.request.urlopen(urllib.request.Request(
            f"https://rest.runpod.io/v1/pods/{pod_id}", method="DELETE",
            headers={"Authorization": f"Bearer {key}"}), timeout=60)
    except Exception as e:
        print(f"POD DELETE call failed ({e}) — verifying anyway")
    time.sleep(10)
    try:
        urllib.request.urlopen(urllib.request.Request(
            f"https://rest.runpod.io/v1/pods/{pod_id}",
            headers={"Authorization": f"Bearer {key}"}), timeout=30)
    except urllib.error.HTTPError as e:
        if e.code in (404, 400):
            print(f"pod {pod_id} deleted and gone (HTTP {e.code})")
            return True
        print(f"pod {pod_id} query HTTP {e.code} — VERIFY BY HAND")
        return False
    print(f"WARNING: pod {pod_id} STILL ANSWERS — kill it by hand")
    return False


def main():
    key = os.environ["RUNPOD_API_KEY"]
    sb = os.environ["SB_KEY"]
    hf = os.environ["HF_TOKEN"]
    sha = os.environ["ST_INPUT_SHA"]
    fuse = os.environ.get("ST_FUSE_S", "2700")
    watch_s = float(os.environ.get("ST_WATCH_S", "3300"))
    boot_limit = float(os.environ.get("ST_BOOT_LIMIT_S", "900"))

    print("staging code to the bucket")
    put(os.path.join(HERE, "sparseflex_boot.sh"), "sparseflex_boot.sh", sb)
    put(os.path.join(HERE, "crease_density.py"), "crease_density.py", sb)
    put(os.path.join(HERE, "crease2.py"), "crease2.py", sb)
    preflight(sb, hf)

    # RESET THE LOG BEFORE THE POD EXISTS. Attempt 2 launched a healthy pod and
    # killed it inside one second, because {RUN}_log.txt still held attempt 1's
    # "=== FAIL:O3D_IMPORT ===" and the watcher read a PREVIOUS run's terminal
    # marker as this run's. This is the recorded run-id-namespacing trap
    # ("a previous run's heartbeat masquerades as progress"), reproduced.
    # Two guards, because one was not enough: the log is overwritten with a
    # unique sentinel here, AND no stage line is believed until the log carries
    # "fuse armed", which only THIS pod's bootstrap can print.
    nonce = f"LAUNCH-{int(time.time())}"
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as fh:
        fh.write(f"=== STAGE:launching {nonce} ===\n")
        sentinel = fh.name
    put(sentinel, f"{RUN}_log.txt", sb, "text/plain")
    os.unlink(sentinel)

    boot_cmd = (
        f"curl -sS -H 'apikey: $SB_KEY' -H 'Authorization: Bearer $SB_KEY' "
        f"'{SB}/{PRE}/sparseflex_boot.sh?cb='$(date +%s) -o /tmp/boot.sh "
        f"&& bash /tmp/boot.sh; sleep infinity")
    body = {
        "name": f"sparseflex-{RUN}",
        "imageName": IMAGE,
        "gpuTypeIds": GPUS,
        "gpuTypePriority": "availability",
        "gpuCount": 1,
        "containerDiskInGb": 60,
        "volumeInGb": 0,
        "cloudType": "SECURE",
        # A pod whose dockerStartCmd EXITS gets RESTARTED into an infinite
        # re-clone loop. `sleep infinity` is what stops that.
        "dockerStartCmd": ["bash", "-c", boot_cmd],
        "env": {"SB_KEY": sb, "HF_TOKEN": hf,
                "HUGGING_FACE_HUB_TOKEN": hf,
                "RUNPOD_API_KEY": key,          # the in-pod fuse needs it
                "HF_HOME": "/workspace/hf",
                "ST_PRE": PRE, "ST_RUN": RUN,
                "ST_INPUT_SHA": sha, "ST_FUSE_S": fuse},
    }
    req = urllib.request.Request(
        "https://rest.runpod.io/v1/pods", data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"})
    try:
        pod = json.load(urllib.request.urlopen(req, timeout=90))
    except urllib.error.HTTPError as e:
        raise SystemExit(f"pod launch HTTP {e.code}: "
                         f"{e.read().decode()[:400]}")
    pod_id = pod.get("id")
    if not pod_id:
        raise SystemExit("pod launch returned no id")
    print(f"POD {pod_id} launched ({RUN}); fuse {fuse}s", flush=True)

    t0, last, ok, timed_out = time.time(), "", False, True
    try:
        while time.time() - t0 < watch_s:
            el = int(time.time() - t0)
            try:
                st = pod_state(pod_id, key)
            except Exception as e:
                st = {"desired": f"query-failed:{type(e).__name__}"}
            try:
                log = get_text(f"{RUN}_log.txt", sb)
                # Only THIS pod's bootstrap prints "fuse armed". Until that
                # appears, whatever is in the object belongs to someone else.
                if "fuse armed" not in log:
                    cur = ""
                else:
                    lines = [l for l in log.splitlines() if l.startswith("=== ")]
                    cur = lines[-1] if lines else ""
            except Exception:
                cur = last
            if cur != last:
                last = cur
                print(f"  [{el//60}m{el%60:02d}s] {last}   "
                      f"uptime={st.get('uptime')} gpu={st.get('gpu_pct')}%",
                      flush=True)
            elif el % 120 < 30:
                print(f"  [{el//60}m] (no new stage) last={last or '-'} "
                      f"desired={st.get('desired')} "
                      f"uptime={st.get('uptime')} gpu={st.get('gpu_pct')}%",
                      flush=True)
            if OK_MARKER in last:
                ok, timed_out = True, False
                break
            if "=== FAIL:" in last:
                timed_out = False
                print(f"BOOTSTRAP FAILED: {last}")
                break
            if not last and el > boot_limit:
                timed_out = False
                print(f"DEAD HOST: nothing past launch in {boot_limit/60:.0f}m")
                break
            time.sleep(30)
        if timed_out:
            # A bounded loop MUST announce its own fall-through. A silent
            # expiry is indistinguishable from "still working".
            print(f"=== WATCHER TIMED_OUT after {watch_s/60:.0f}m — "
                  f"last stage was: {last or 'nothing'} ===")
    finally:
        print("deleting pod")
        delete_pod(pod_id, key)

    print(f"RESULT: {'OK' if ok else 'NOT OK'} (last stage: {last})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
