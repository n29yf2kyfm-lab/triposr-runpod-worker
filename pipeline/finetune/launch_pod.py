#!/usr/bin/env python3
"""launch_pod.py — capacity-hunt a RunPod pod for a fine-tune stage, poll its
status server, and ALWAYS delete the pod on any terminal state.

Replaces the ad-hoc /tmp launchers. Forensic-audit fix F5: the old poller
exited on DONE/FATAL/poll-timeout while the pod slept (and billed) forever;
this one tears the pod down on every terminal path, including poll timeout
(the bootstrap serves logs from the network volume, so nothing is lost when
the pod dies).

Secrets come from env only — never hardcoded:
  RUNPOD_API_KEY   required
  HF_TOKEN         optional; forwarded to the pod env for gated HF downloads

Usage:
  python3 pipeline/finetune/launch_pod.py --script stage_b_pod.sh \
      [--name alam3d-stage-b] [--tier 80gb|render] [--hours 6] [--keep]
"""
import argparse, json, os, subprocess, sys, time, urllib.request

BUCKET = "https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object/public/car-renders/finetune"
VOLUME = "yiv4apiad7"          # alam3d-data (EU-RO-1)
IMAGE = "alamk123/ai-mechanic:trellis2-latest"
TIERS = {
    # 80GB-class only: 24GB cards cudaMalloc-OOM the 1.3B trainer
    "80gb": [["NVIDIA A100 80GB PCIe", "NVIDIA A100-SXM4-80GB",
              "NVIDIA H100 PCIe", "NVIDIA H100 80GB HBM3"],
             ["NVIDIA A100-SXM4-80GB"]],
    # render/encode work (e.g. render_cond backfill) is fine on 24GB
    "render": [["NVIDIA RTX A5000", "NVIDIA GeForce RTX 3090",
                "NVIDIA RTX A6000", "NVIDIA L40S"],
               ["NVIDIA GeForce RTX 4090"]],
}


def api(key, path, method="GET", body=None):
    req = urllib.request.Request(
        f"https://rest.runpod.io/v1/{path}",
        data=json.dumps(body).encode() if body else None, method=method,
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    try:
        raw = urllib.request.urlopen(req, timeout=90).read()
        return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        return {"err": f"{e.code} {e.read().decode()[:140]}"}


def delete_pod(key, pod, why):
    for attempt in range(5):
        r = api(key, f"pods/{pod}", method="DELETE")
        if "err" not in r:
            print(f"pod {pod} deleted ({why})", flush=True)
            return True
        time.sleep(10 * (attempt + 1))
    print(f"POD_DELETE_FAILED {pod} — DELETE IT MANUALLY, IT IS STILL BILLING", flush=True)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--script", required=True, help="bootstrap filename in the finetune bucket")
    ap.add_argument("--name", default="alam3d-stage")
    ap.add_argument("--tier", choices=TIERS, default="80gb")
    ap.add_argument("--hours", type=float, default=6, help="poll budget before teardown")
    ap.add_argument("--hunt-hours", type=float, default=2, help="capacity-hunt budget")
    ap.add_argument("--keep", action="store_true", help="do NOT delete the pod on terminal state")
    a = ap.parse_args()

    key = os.environ.get("RUNPOD_API_KEY")
    if not key:
        sys.exit("RUNPOD_API_KEY missing from env")
    hf = os.environ.get("HF_TOKEN", "")

    boot = (f"curl -sSL '{BUCKET}/{a.script}?cb='$(date +%s) | bash; sleep infinity")
    env = {"HF_HOME": "/workspace/hf_cache"}
    if hf:
        env["HF_TOKEN"] = env["HUGGING_FACE_HUB_TOKEN"] = hf

    pod = None
    deadline = time.time() + a.hunt_hours * 3600
    while time.time() < deadline and not pod:
        for gpus in TIERS[a.tier]:
            d = api(key, "pods", "POST", {
                "name": a.name, "imageName": IMAGE, "cloudType": "SECURE",
                "gpuTypeIds": gpus, "gpuCount": 1, "containerDiskInGb": 60,
                "networkVolumeId": VOLUME, "volumeMountPath": "/workspace",
                "ports": ["8000/http"], "env": env,
                "dockerStartCmd": ["bash", "-c", boot]})
            if d.get("id"):
                pod = d["id"]
                print(f"POD CREATED {pod} tier={gpus[0]} cost={d.get('costPerHr')}", flush=True)
                break
            print(f"no capacity ({gpus[0]}): {d.get('err', '?')[:100]}", flush=True)
        if not pod:
            time.sleep(120)
    if not pod:
        print("NO_CAPACITY within hunt budget", flush=True)
        return

    url = f"https://{pod}-8000.proxy.runpod.net"

    # NB: poll with curl, not urllib — the sandbox egress proxy 403s python
    # urllib for *.proxy.runpod.net while letting curl through, which made
    # earlier pollers silently blind (they never saw DONE/FATAL).
    def fetch(path, timeout=30):
        r = subprocess.run(["curl", "-s", "-m", str(timeout), url + path],
                           capture_output=True, text=True)
        return r.stdout if r.returncode == 0 else ""

    outcome = "POLL_TIMEOUT"
    last = ""
    for _ in range(int(a.hours * 3600 / 120)):
        time.sleep(120)
        s = fetch("/status.json")
        if s and s != last:
            print("status:", s.strip(), flush=True)
            last = s
        if "DONE" in s or "FATAL" in s:
            outcome = "DONE" if "DONE" in s else "FATAL"
            tail = fetch("/stage_b.log", timeout=90)[-4000:]
            if tail:
                print(tail, flush=True)
            break
    print(f"TERMINAL {outcome}", flush=True)
    if not a.keep:
        delete_pod(key, pod, outcome)


if __name__ == "__main__":
    main()
