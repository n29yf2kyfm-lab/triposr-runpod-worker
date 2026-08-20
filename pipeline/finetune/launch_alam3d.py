#!/usr/bin/env python3
"""launch_alam3d.py — run OUR fine-tune (Alam-3D) against STOCK TRELLIS.2 on
the same image, in one pod boot.

Same hardened pattern as launch_pixal_batch / launch_sf3d, plus two preflights
those two do not have, both aimed at the situation this was written in (a $1.47
balance and no room for a wasted rental):

  * BALANCE PREFLIGHT. Billing exhaustion looks EXACTLY like GPU-capacity
    starvation — the create call can succeed and the pod then never runs. It is
    one GraphQL call and it is free. (CLAUDE.md carries the correction that
    `myself { clientBalance }` is NOT 403; acting on the older, wrong note cost
    ~40 minutes misdiagnosing a flat balance as capacity.)
  * CHECKPOINT PREFLIGHT. The weights are in a PRIVATE HF repo. A 403 or a
    typo'd filename discovered on the pod costs money; discovered here it costs
    nothing. This resolves the file against the repo listing and then proves
    HF_TOKEN can actually read its first bytes.

Everything else is the pattern the repo already paid for: stage artefacts to
the bucket, PREFLIGHT the bootstrap URL, monitor the BUCKET LOG (never
`desiredStatus`), boot-watchdog a dead host, delete the pod on any terminal
marker and VERIFY it is gone.

Secrets come from /root/.alam3d_env, by NAME only — RUNPOD_API_KEY, SB_KEY,
HF_TOKEN. No value is ever written into this repo.

Usage:
  set -a; . /root/.alam3d_env; set +a
  python3 pipeline/finetune/launch_alam3d.py car.png              # one car
  python3 pipeline/finetune/launch_alam3d.py a.png b.png          # two cars
  ALAM3D_MULTIVIEW=1 python3 pipeline/finetune/launch_alam3d.py v0.jpg v1.jpg \
      v2.jpg v3.jpg                                # ONE car, four views

Knobs (all optional):
  ALAM3D_CKPT_REPO   default Alamj/alam-3d-v1
  ALAM3D_CKPT_FILE   default denoiser_ema0.9999_step0000500.pt
  ALAM3D_CKPT_PATH   full in-repo path; overrides the FILE lookup entirely
  ALAM3D_RUN_BASE    1 (default) also generates the stock-weights control
  ALAM3D_PIPE        1024_cascade (default) | 512 | 1024 | 1536_cascade
  ALAM3D_MAX_TOKENS  32768 (proven-safe budget; 49152 OOMs 24GB)
  ALAM3D_MULTIVIEW   1 = all given images are views of ONE car
  ALAM3D_MIN_BALANCE 5.0 USD floor before anything is rented
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SB = "https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object"
PRE = os.environ.get("ALAM3D_PRE", "car-meshes/alam3d")

# OUR OWN trellis2-worker-4b (RunPod template i1mk2n9dap) — the production
# render image. It already carries the TRELLIS.2 CUDA extensions, /app/handler.py
# with the ungated-BiRefNet and DINOv3 patches, and /app/alam3d_multiview.py, so
# the pipeline this eval loads is the same one production loads. Same digest
# launch_pixal_batch.py pins.
IMAGE = os.environ.get(
    "ALAM3D_IMAGE",
    "alamk123/ai-mechanic@sha256:"
    "5c5b87edd06cb105d914b9d4c9341411736520ff13045a8d281ce6209709a2bf")

CKPT_REPO = os.environ.get("ALAM3D_CKPT_REPO", "Alamj/alam-3d-v1")
CKPT_FILE = os.environ.get("ALAM3D_CKPT_FILE",
                           "denoiser_ema0.9999_step0000500.pt")
OK_MARKER = "ALAM3D_OK"

# NO HOPPER. Measured 2026-07-28: this image loads the whole model on an H100
# and then dies at the first F.conv2d with "no kernel image is available for
# execution on the device" — 25 minutes and $0.45 in. torch's arch list does not
# predict it (the image reports sm_90); conv2d dispatches to cuDNN, whose
# kernels the list says nothing about. A wider pool is NOT a better capacity
# hunt when the extra hardware is guaranteed to fail. 48GB Ampere/Ada first
# (inference peaked around 26GB in the Stage C evals), A100 as the last resort.
GPU_POOL = ["NVIDIA RTX A6000", "NVIDIA L40S", "NVIDIA L40",
            "NVIDIA RTX 6000 Ada Generation", "NVIDIA A40",
            "NVIDIA A100 80GB PCIe", "NVIDIA A100-SXM4-80GB"]


def put(local, remote, sb_key):
    """Supabase storage needs BOTH apikey and Authorization. With Authorization
    alone it returns 403 'Invalid Compact JWS', which reads as an expired key
    and has cost this project time twice."""
    req = urllib.request.Request(
        f"{SB}/{PRE}/{remote}", data=open(local, "rb").read(), method="POST",
        headers={"apikey": sb_key, "Authorization": f"Bearer {sb_key}",
                 "x-upsert": "true",
                 "Content-Type": "application/octet-stream"})
    urllib.request.urlopen(req, timeout=300)


# ---------------------------------------------------------------- preflights
def preflight_balance(key):
    """Prove there is money BEFORE renting. Billing exhaustion is invisible from
    the create call: submits return 200, the pod sits allocated-but-idle, and
    workers stay at zero forever — indistinguishable from capacity starvation
    unless the balance is read."""
    floor = float(os.environ.get("ALAM3D_MIN_BALANCE", "5.0"))
    body = {"query": "query { myself { clientBalance currentSpendPerHr } }"}
    # THE USER-AGENT IS LOAD-BEARING, measured 2026-08-20. api.runpod.io sits
    # behind Cloudflare, which rejects Python-urllib's default UA with
    # "403 error code: 1010" — while the identical request from curl returns
    # 200. That 403 looks EXACTLY like the stale (and wrong) note this project
    # used to carry saying GraphQL myself{} is forbidden for this key, which
    # already cost ~40 minutes of misdiagnosing a flat balance as GPU-capacity
    # starvation. Send a UA and the query works. rest.runpod.io is unaffected.
    req = urllib.request.Request(
        "https://api.runpod.io/graphql", data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json",
                 "User-Agent": "curl/8.5.0"})
    try:
        me = json.load(urllib.request.urlopen(req, timeout=60))["data"]["myself"]
    except Exception as e:
        print(f"WARNING: balance unreadable ({type(e).__name__}: {str(e)[:80]}) "
              f"— continuing WITHOUT the money guard. If the pod then sits at "
              f"'launching' forever, read billing first: an exhausted account "
              f"is indistinguishable from capacity starvation from the outside.")
        return
    bal = float(me.get("clientBalance") or 0.0)
    print(f"RunPod balance: ${bal:.2f}  (spend now ${me.get('currentSpendPerHr')}/hr)")
    if bal < floor:
        raise SystemExit(
            f"REFUSED: balance ${bal:.2f} is below the ${floor:.2f} floor. This "
            f"run needs roughly 30-45 GPU-minutes; renting on an empty account "
            f"produces a pod that never runs and a diagnosis that looks like "
            f"capacity starvation. Top up, or set ALAM3D_MIN_BALANCE to "
            f"override deliberately. Nothing was rented.")


def preflight_ckpt(hf_token):
    """Resolve the checkpoint path against the repo listing, then prove the
    token can read it. A gated/private 403 or a mistyped step number found on
    the pod costs a rental; found here it costs nothing."""
    explicit = os.environ.get("ALAM3D_CKPT_PATH")
    req = urllib.request.Request(
        f"https://huggingface.co/api/models/{CKPT_REPO}",
        headers={"Authorization": f"Bearer {hf_token}"})
    try:
        info = json.load(urllib.request.urlopen(req, timeout=60))
    except urllib.error.HTTPError as e:
        raise SystemExit(
            f"REFUSED: cannot read {CKPT_REPO} (HTTP {e.code}). The repo is "
            f"PRIVATE — HF_TOKEN must belong to the owning account. Nothing "
            f"was rented.")
    files = [f["rfilename"] for f in info.get("siblings", [])]
    print(f"{CKPT_REPO}: private={info.get('private')}, {len(files)} files")
    if explicit:
        path = explicit
    else:
        cand = [f for f in files if os.path.basename(f) == CKPT_FILE]
        if not cand:
            ck = [f for f in files if f.endswith(".pt")]
            raise SystemExit(
                f"REFUSED: {CKPT_FILE} is not in {CKPT_REPO}. Checkpoints "
                f"present: {ck}. Set ALAM3D_CKPT_FILE (or ALAM3D_CKPT_REPO) to "
                f"one of those. Nothing was rented.")
        path = cand[0]
    if path not in files:
        raise SystemExit(f"REFUSED: {path} is not in {CKPT_REPO}: {files}")
    # A listing proves existence, not readability. Pull the first KB.
    req = urllib.request.Request(
        f"https://huggingface.co/{CKPT_REPO}/resolve/main/{path}",
        headers={"Authorization": f"Bearer {hf_token}", "Range": "bytes=0-1023"})
    try:
        r = urllib.request.urlopen(req, timeout=120)
    except urllib.error.HTTPError as e:
        raise SystemExit(
            f"REFUSED: {CKPT_REPO}/{path} is not readable by this token "
            f"(HTTP {e.code}). Nothing was rented.")
    size = (r.headers.get("Content-Range") or "").split("/")[-1] or "?"
    print(f"checkpoint preflight OK: {path} (HTTP {r.status}, {size} bytes)")
    try:
        gb = int(size) / 1e9
        if gb < 1.0:
            raise SystemExit(
                f"REFUSED: {path} is only {gb:.2f} GB. A 1.3B denoiser EMA is "
                f"~5.2GB — this one is truncated (a full volume did exactly "
                f"that to Stage C's step-1250 save). Nothing was rented.")
        print(f"  size {gb:.2f} GB — plausible for a 1.3B denoiser EMA")
    except ValueError:
        print("  size not reported; the pod re-verifies the archive anyway")
    return path


def stage_inputs(images, sb_key):
    """Upload the images, the manifest and the bootstrap. Cheap artefacts go up
    before anything expensive starts — this container has rolled back mid-run
    and the bucket is what survived."""
    multiview = os.environ.get("ALAM3D_MULTIVIEW") == "1"
    cars = []
    if multiview:
        views = []
        for i, p in enumerate(images):
            name = f"in_car_{i:02d}{os.path.splitext(p)[1].lower()}"
            put(p, name, sb_key)
            views.append(name)
            print(f"  uploaded {name}  <- {p}")
        cars.append({"tag": "car", "views": views})
    else:
        for p in images:
            tag = os.path.splitext(os.path.basename(p))[0]
            name = f"in_{tag}{os.path.splitext(p)[1].lower()}"
            put(p, name, sb_key)
            cars.append({"tag": tag, "views": [name]})
            print(f"  uploaded {name}")
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as bf:
        json.dump(cars, bf)
        bpath = bf.name
    put(bpath, "batch.json", sb_key)
    os.unlink(bpath)
    print(f"manifest: {[(c['tag'], len(c['views'])) for c in cars]}")

    put(os.path.join(HERE, "alam3d_boot.sh"), "alam3d_boot.sh", sb_key)
    reset_log(sb_key)

    # PREFLIGHT THE BOOTSTRAP URL. The pod's start command is
    # `curl -fsSL … | bash`, so a URL that 404s means curl fails, the pipe runs
    # nothing, and the pod boots into total silence — no heartbeat, no log,
    # nothing to diagnose. That was misread as "slow image pulls" for two runs
    # on the P3-SAM work. One HTTP call removes the entire failure class.
    url = f"{SB}/public/{PRE}/alam3d_boot.sh"
    if urllib.request.urlopen(url, timeout=30).status != 200:
        raise SystemExit("bootstrap preflight failed — refusing to rent a GPU")
    print("bootstrap preflight OK")
    return url


def reset_log(sb_key):
    """Reset the marker log for THIS attempt. A leftover marker from a previous
    pod makes a dead host look alive — the stale-heartbeat trap this project
    already paid for on the Hi3DGen runs."""
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as tf:
        tf.write("=== STAGE:launching ===\n")
        p = tf.name
    put(p, "log.txt", sb_key)
    os.unlink(p)


# ------------------------------------------------------------------- attempt
def attempt(url, sb_key, ckpt_path, n, total):
    """Rent a pod, watch the bucket log, return "ok" | "dead" | "fail".

    "dead" means the host never ran the bootstrap at all — a HOST fault, so the
    supervisor re-rents rather than concluding the job is broken."""
    key = os.environ["RUNPOD_API_KEY"]
    print(f"--- attempt {n}/{total}", flush=True)
    body = {
        "name": "alam3d-eval",
        "imageName": IMAGE,
        "gpuTypeIds": GPU_POOL,
        "gpuTypePriority": "availability",
        "gpuCount": 1,
        # image (~30GB) + TRELLIS.2-4B cascade + a 5.2GB checkpoint + GLBs.
        "containerDiskInGb": 140,
        # NO network volume on purpose. The alam3d volume has hit quota before
        # and truncated a checkpoint mid-save; everything here is fetched from
        # HF and pushed to Supabase, so container disk is both enough and safer.
        "volumeInGb": 0,
        "cloudType": "SECURE",
        # `sleep infinity` is load-bearing. A dockerStartCmd that EXITS gets the
        # pod restarted — re-clone, re-install, re-download ~10GB of weights,
        # forever, at 0% GPU, while the API reports desiredStatus RUNNING. The
        # cache-buster on the URL stops a CDN serving a stale bootstrap.
        "dockerStartCmd": ["bash", "-c",
                           f"curl -sSL '{url}?cb='$(date +%s) | bash; "
                           "sleep infinity"],
        "env": {"SB_KEY": sb_key,
                # the pod MUST resolve the same prefix the launcher wrote to,
                # or it fetches a manifest that is not there and reports the
                # failure to a log nobody is watching (the 2026-08-19 bug)
                "ALAM3D_PRE": PRE,
                "ALAM3D_CKPT_REPO": CKPT_REPO,
                # the RESOLVED path, verified above — the pod never re-guesses
                "ALAM3D_CKPT_PATH": ckpt_path,
                "ALAM3D_RUN_BASE": os.environ.get("ALAM3D_RUN_BASE", "1"),
                "ALAM3D_PIPE": os.environ.get("ALAM3D_PIPE", "1024_cascade"),
                "ALAM3D_SEED": os.environ.get("ALAM3D_SEED", "42"),
                "ALAM3D_MAX_TOKENS": os.environ.get("ALAM3D_MAX_TOKENS", "32768"),
                "ALAM3D_MIN_MATCH": os.environ.get("ALAM3D_MIN_MATCH", "0.99"),
                "ALAM3D_RUN_ID": RUN_ID,
                "HF_TOKEN": os.environ.get("HF_TOKEN", ""),
                "HUGGING_FACE_HUB_TOKEN": os.environ.get("HF_TOKEN", ""),
                "HF_HOME": "/workspace/hf"},
    }
    req = urllib.request.Request(
        "https://rest.runpod.io/v1/pods", data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"})
    try:
        pod = json.load(urllib.request.urlopen(req, timeout=90))
    except urllib.error.HTTPError as e:
        raise SystemExit(f"pod create refused: HTTP {e.code} "
                         f"{e.read().decode()[:200]}")
    pod_id = pod.get("id")
    if not pod_id:
        raise SystemExit(f"pod launch failed: {pod}")
    print(f"alam3d pod {pod_id} launched; monitoring bucket log", flush=True)
    reset_log(sb_key)

    log_url = f"{SB}/public/{PRE}/log.txt"
    t0, last, ok = time.time(), "", False
    # BOOT WATCHDOG. A dead host reports desiredStatus RUNNING with runtime None
    # forever — measured 2026-08-19: 26 minutes stuck at "launching", $0.69
    # burned, and only a human noticed. Poll PROGRESS, never desire: if the
    # bootstrap has not moved past "launching" inside the limit, the host is
    # dead. Say so and re-rent.
    BOOT_LIMIT = float(os.environ.get("ALAM3D_BOOT_LIMIT_S", "900"))
    CEIL = float(os.environ.get("ALAM3D_CEILING_S", "10800"))   # 3h
    try:
        while time.time() - t0 < CEIL:
            if (last in ("", "=== STAGE:launching ===")
                    and time.time() - t0 > BOOT_LIMIT):
                print(f"DEAD HOST: no progress past '{last or 'nothing'}' in "
                      f"{BOOT_LIMIT/60:.0f} min — killing pod {pod_id}; "
                      "relaunch lands on a different host.", flush=True)
                break
            try:
                log = urllib.request.urlopen(
                    f"{log_url}?cb={int(time.time())}", timeout=30
                ).read().decode("utf-8", "replace")
                lines = [ln for ln in log.splitlines() if ln.startswith("=== ")]
                if lines and lines[-1] != last:
                    last = lines[-1]
                    print(f"  [{(time.time()-t0)/60:.0f}m] {last}", flush=True)
                if OK_MARKER in last:
                    ok = True
                    break
                if "FAIL" in last:
                    break
            except Exception:
                pass
            time.sleep(45)
        else:
            # A bounded loop MUST print a distinct marker on fall-through. The
            # P3-SAM watcher expired after 45 identical lines, printed nothing
            # to distinguish "gave up" from "done", and the pod then billed
            # unwatched for half an hour.
            print(f"TIMED_OUT: attempt hit the {CEIL/3600:.1f}h ceiling at "
                  f"'{last}' — killing the pod", flush=True)
    finally:
        # ALWAYS delete, and VERIFY it is gone. An undeleted pod bills forever.
        req = urllib.request.Request(
            f"https://rest.runpod.io/v1/pods/{pod_id}", method="DELETE",
            headers={"Authorization": f"Bearer {key}"})
        try:
            urllib.request.urlopen(req, timeout=60)
        except Exception as e:
            print(f"POD DELETE FAILED — kill {pod_id} BY HAND NOW: {e}")
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


RUN_ID = os.environ.get("ALAM3D_RUN_ID") or time.strftime("%Y%m%dT%H%M",
                                                          time.gmtime())


def main(images):
    for var in ("RUNPOD_API_KEY", "SB_KEY", "HF_TOKEN"):
        if not os.environ.get(var):
            raise SystemExit(
                f"{var} missing. Load the credentials first:\n"
                f"  set -a; . /root/.alam3d_env; set +a")
    missing = [p for p in images if not os.path.isfile(p)]
    if missing:
        raise SystemExit(f"no such image(s): {missing}")

    # Everything that can refuse for free refuses BEFORE the pod exists.
    preflight_balance(os.environ["RUNPOD_API_KEY"])
    ckpt_path = preflight_ckpt(os.environ["HF_TOKEN"])
    sb_key = os.environ["SB_KEY"]
    url = stage_inputs(images, sb_key)
    print(f"run id {RUN_ID} -> results land in {PRE}/{RUN_ID}/")

    tries = int(os.environ.get("ALAM3D_MAX_ATTEMPTS", "2"))
    for n in range(1, tries + 1):
        verdict = attempt(url, sb_key, ckpt_path, n, tries)
        print(f"attempt {n} verdict: {verdict}", flush=True)
        if verdict == "ok":
            print(f"ALAM3D RESULT: OK — GLBs and run_meta.json in "
                  f"{PRE}/{RUN_ID}/ (…_base.glb vs …_alam3d.glb)")
            return 0
        if verdict == "fail":
            print("ALAM3D RESULT: NOT OK (the job failed — read the FAIL marker "
                  f"in {SB}/public/{PRE}/log.txt; this is not a host fault, so "
                  "re-renting would fail the same way)")
            return 1
        if n < tries:
            print("dead host — re-renting on a different machine\n", flush=True)
            time.sleep(20)
    print(f"ALAM3D RESULT: NOT OK ({tries} dead hosts in a row — check RunPod "
          f"SECURE capacity for {GPU_POOL[0]})")
    return 1


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    sys.exit(main(sys.argv[1:]))
