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
# WHAT THE CONTAINER CAN ACTUALLY RUN — measured, not asserted.
# On an H100, alamk123/ai-mechanic:trellis2-latest dies at the first F.conv2d
# with "CUDA error: no kernel image is available for execution on the device",
# after loading the model, 25 minutes and $0.45 in (pod wbaly1yo5vxwb9,
# 2026-07-28). The mechanism is NOT torch's compiled arch list — the image
# reports sm_90 in torch.cuda.get_arch_list() (read live on pod 4r2da7o1qkab9n)
# — conv2d dispatches to cuDNN, which ships its own kernels; a pre-Hopper cuDNN
# is the likely culprit. A100 (sm_80) is proven good by every successful run;
# a 4090 (sm_89) ran stage-a. The pod-side guard now launches a real conv2d on
# the device instead of trusting any list — that guard is the authority.
#
# So a wider GPU list is NOT a better capacity hunt. Asking for hardware the
# image cannot execute converts "wait for an A100" into "pay for a guaranteed
# failure". H100/H200/Blackwell ids are deliberately absent until the image is
# rebuilt with kernels for them; the pod-side guard is the backstop if one
# ever sneaks back in.
TIERS = {
    # 80GB-class, sm_80 or below: 24GB cards cudaMalloc-OOM the 1.3B trainer
    "80gb": [["NVIDIA A100 80GB PCIe", "NVIDIA A100-SXM4-80GB"],
             ["NVIDIA A100-SXM4-80GB"]],
    # INFERENCE-ONLY (checkpoint sweeps, generation). Training needs 80GB;
    # generating does not - last night's training peaked at 33% of an 80GB card,
    # ~26GB, and inference is lighter. 48GB Ampere/Ada parts are sm_86/sm_89,
    # inside what the image supports, and cost a fraction of an A100.
    "eval": [["NVIDIA RTX A6000", "NVIDIA L40S", "NVIDIA L40",
              "NVIDIA RTX 6000 Ada Generation"],
             ["NVIDIA A100 80GB PCIe", "NVIDIA A100-SXM4-80GB"]],
    # render/encode/single-model inference: fine on 24GB. Widened 2026-07-28
    # after the d3s2 hunt sat refused on a 4-id list - every id here is
    # Ampere/Ada (sm_86/sm_89), inside what the image runs and outside the
    # Hopper cuDNN failure. Cheapest group first; 48GB group second; A100 as
    # the priced last resort so a long queue cannot strand the job.
    "render": [["NVIDIA RTX A5000", "NVIDIA GeForce RTX 3090",
                "NVIDIA GeForce RTX 4090", "NVIDIA L4"],
               ["NVIDIA RTX A6000", "NVIDIA A40", "NVIDIA L40",
                "NVIDIA L40S", "NVIDIA RTX 6000 Ada Generation"],
               ["NVIDIA A100 80GB PCIe", "NVIDIA A100-SXM4-80GB"]],
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


def allocated_gpu(key, pod):
    """The GPU the pod actually landed on, from the API — not the requested id,
    not a price heuristic. REST /pods omits the machine's GPU type; the GraphQL
    machine{gpuTypeId} field is where RunPod reports it (verified 2026-07-28
    against the account's own pods). Best-effort: a lookup failure must never
    kill a launch that has already paid for a pod."""
    # curl, not urllib: the sandbox egress proxy 403s python urllib for this
    # host while letting curl through — the exact failure mode that blinded the
    # early pod pollers, and it reproduced here on the first live test of this
    # function (urllib: HTTPError; curl: clean response).
    q = '{"query":"query{myself{pods{id machine{gpuTypeId}}}}"}'
    try:
        r = subprocess.run(
            ["curl", "-s", "-m", "60", "https://api.runpod.io/graphql",
             "-H", "Authorization: Bearer " + key,
             "-H", "Content-Type: application/json", "-d", q],
            capture_output=True, text=True, check=True)
        d = json.loads(r.stdout)
        for p in d["data"]["myself"]["pods"]:
            if p["id"] == pod:
                return (p.get("machine") or {}).get("gpuTypeId") or "unreported"
        return "pod not in listing"
    except Exception as e:
        return f"lookup failed: {type(e).__name__}"


def delete_pod(key, pod, why):
    for attempt in range(5):
        r = api(key, f"pods/{pod}", method="DELETE")
        if "err" not in r:
            print(f"pod {pod} deleted ({why})", flush=True)
            return True
        if "404" in str(r.get("err", "")):
            # Already gone — someone else (watchdog, another supervisor) beat
            # us to it. That is success, not an alarm: the council audit found
            # six zombie launchers queued to cry "STILL BILLING" over pods
            # deleted out-of-band, training the operator to ignore the one
            # message that must never be ignorable.
            print(f"pod {pod} already deleted ({why})", flush=True)
            return True
        time.sleep(10 * (attempt + 1))
    print(f"POD_DELETE_FAILED {pod} — DELETE IT MANUALLY, IT IS STILL BILLING", flush=True)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--script", required=True, help="bootstrap filename in the finetune bucket")
    ap.add_argument("--name", default="alam3d-stage")
    ap.add_argument("--tier", choices=TIERS, default="80gb")
    ap.add_argument("--gpus", type=int, default=1, help="GPUs per pod (Stage C uses 4)")
    ap.add_argument("--hours", type=float, default=6, help="poll budget before teardown")
    ap.add_argument("--hunt-hours", type=float, default=2, help="capacity-hunt budget")
    ap.add_argument("--keep", action="store_true", help="do NOT delete the pod on terminal state")
    a = ap.parse_args()

    key = os.environ.get("RUNPOD_API_KEY")
    if not key:
        sys.exit("RUNPOD_API_KEY missing from env")
    hf = os.environ.get("HF_TOKEN", "")

    # Preflight the script URL: without -f, a 404 pipes a JSON error into bash,
    # nothing starts, no status server exists, and the launcher polls silence
    # for its whole --hours budget — ~$14 of A100 for a filename typo.
    head = subprocess.run(["curl", "-sfI", "-m", "30", f"{BUCKET}/{a.script}"],
                          capture_output=True)
    if head.returncode != 0:
        sys.exit(f"bootstrap script not fetchable: {BUCKET}/{a.script}")
    boot = (f"curl -sfSL '{BUCKET}/{a.script}?cb='$(date +%s) | bash; sleep infinity")
    env = {"HF_HOME": "/workspace/hf_cache"}
    if hf:
        env["HF_TOKEN"] = env["HUGGING_FACE_HUB_TOKEN"] = hf
    if os.environ.get("SB_KEY"):    # lets eval pods upload results; never in scripts
        env["SB_KEY"] = os.environ["SB_KEY"]
    # eval knobs: single-case spot checks, pipeline type, run directory, and the
    # four-way stage-isolation run.
    # Forward EVERY EVAL_* knob by prefix rather than by name. A name-based
    # allowlist has now silently dropped three knobs: HF_REPO (published to the
    # wrong repo), MAX_STEPS (ran 2000 steps instead of 1250) and EVAL_RUN_DIR
    # (would have evaluated v0's damaged weights while reporting them as v1).
    # The old comment warned that a missing name is silently dropped; the
    # warning did not help, so the mechanism changed instead.
    # Any new pod-script knob MUST use one of these prefixes or be named here —
    # the council audit found D3S2_RUN_ID, D3S2_RES and TEX_MIN_POOL silently
    # unreachable, the exact bug class this mechanism was built to kill.
    forwarded = sorted(k for k in os.environ
                       if k.startswith(("EVAL_", "PUBLISH_", "D3S2_", "TEX_"))
                       and os.environ[k])
    for k in ("MAX_STEPS", "HF_REPO", "MIN_FREE_GB"):
        if os.environ.get(k):
            forwarded.append(k)
    for k in forwarded:
        env[k] = os.environ[k]
    if forwarded:
        print("forwarding to pod: " + ", ".join(forwarded), flush=True)

    pod = None
    deadline = time.time() + a.hunt_hours * 3600
    while time.time() < deadline and not pod:
        for gpus in TIERS[a.tier]:
            d = api(key, "pods", "POST", {
                "name": a.name, "imageName": IMAGE, "cloudType": "SECURE",
                "gpuTypeIds": gpus, "gpuCount": a.gpus, "containerDiskInGb": 60,
                "networkVolumeId": VOLUME, "volumeMountPath": "/workspace",
                "ports": ["8000/http"], "env": env,
                "dockerStartCmd": ["bash", "-c", boot]})
            if d.get("id"):
                pod = d["id"]
                # gpus[0] is what we ASKED FIRST for, not what we got — printing
                # the requested id alone is how a 25-minute H100 failure got
                # logged as "tier=A100". An earlier fix printed costPerHr next to
                # a hardcoded price table ("A100 PCIe=1.19") so a surprising
                # price would flag a surprising GPU; that table was itself a
                # guess, and a healthy A100 run at a regional $1.49 tripped it.
                # Ask the API what machine the pod actually landed on instead.
                print(f"POD CREATED {pod} requested={gpus[0]} "
                      f"cost={d.get('costPerHr')}/hr", flush=True)
                print(f"ALLOCATED GPU: {allocated_gpu(key, pod)}", flush=True)
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
    quiet = 0
    for _ in range(int(a.hours * 3600 / 120)):
        time.sleep(120)
        s = fetch("/status.json")
        # Silence is ambiguous: booting pod, dead proxy, or a pod deleted
        # out-of-band. After 5 consecutive empty polls, ask the API whether
        # the pod still exists — a launcher polling a deleted pod for its
        # whole --hours budget is a zombie (six of them existed 2026-07-28).
        quiet = quiet + 1 if not s else 0
        if quiet >= 5:
            if "err" in api(key, f"pods/{pod}"):
                print(f"pod {pod} no longer exists (deleted out-of-band) — exiting", flush=True)
                return
            quiet = 0
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
