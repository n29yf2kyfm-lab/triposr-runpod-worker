#!/usr/bin/env bash
# Bootstrap run on a rented RunPod GPU: fetch data, merge, train, export ONNX,
# publish, then SHUT THE POD DOWN.
#
# Two hard lessons are encoded here.
#
# 1. SELF-TERMINATION. The EXIT trap stops the pod on failure as well as
#    success. A GPU pod left running after a finished job bills indefinitely,
#    and this project has already paid for that.
#
# 2. THE LOG IS AN ARTEFACT. RunPod's REST API exposes no logs endpoint, so a
#    run that dies without uploading its log is undebuggable — the first
#    attempt here exited after seven minutes and left nothing behind but a
#    charge. The trap now uploads train.log ALWAYS, before stopping the pod, so
#    a failure costs one run instead of a blind retry.
#
# Required env: ROBOFLOW_API_KEY HF_TOKEN HF_REPO RUNPOD_API_KEY RUNPOD_POD_ID
# Optional: EPOCHS BATCH MAX_SOURCES RUN_TAG
set -x
# Deliberately NOT `set -u`: an unset RUNPOD_POD_ID must not abort the very trap
# that stops the pod.

WORK=/workspace
mkdir -p "$WORK" && cd "$WORK"
LOG="$WORK/train.log"
exec > >(tee -a "$LOG") 2>&1
TAG="${RUN_TAG:-run}"


finish() {
  code=$?
  set +x
  echo "=== exit code $code ==="
  # Upload the log FIRST — it is the only diagnostic that survives the pod.
  python - <<'PY' || echo "log upload failed"
import os
from huggingface_hub import HfApi
try:
    HfApi(token=os.environ["HF_TOKEN"]).upload_file(
        path_or_fileobj="/workspace/train.log",
        path_in_repo=f"logs/{os.environ.get('RUN_TAG','run')}.log",
        repo_id=os.environ["HF_REPO"], token=os.environ["HF_TOKEN"])
    print("log uploaded")
except Exception as e:
    print("log upload error:", e)
PY
  # Pod id: the env var is NOT reliably injected — on the first full run it was
  # empty, the guard skipped the stop call, and a crashed pod kept billing for
  # six minutes until stopped by hand. Fall back to the hostname (RunPod sets it
  # to the pod id), then to looking ourselves up by name. Failing to stop is the
  # expensive failure, so it gets three chances and three strategies.
  PID="${RUNPOD_POD_ID:-}"
  [ -z "$PID" ] && PID="$(hostname)"
  echo "stopping pod id=$PID"

  # THE IN-POD STOP IS THE ONLY FAILSAFE THAT RUNS UNATTENDED.
  # An external watcher in the controlling session does not count: that process
  # is frozen whenever the session is idle. On the v5 run the script correctly
  # gave up after five minutes, and the pod then billed for SIX HOURS because
  # the only thing that would have stopped it was asleep. So this block has to
  # actually work, and it has to be checked rather than assumed.
  #
  # Previous version looped on `curl ... | grep -q .` — any response at all,
  # including an error body, counted as success, so a failing stop looked fine.
  # Now: runpodctl first (present on RunPod images, uses the pod's own
  # credentials), then the REST API with the HTTP status actually inspected,
  # and terminate as the last resort because a stopped-but-existing pod can
  # still be restarted by the platform.
  if command -v runpodctl >/dev/null 2>&1; then
    echo "runpodctl stop:"; runpodctl stop pod "$PID" || true
  fi
  for attempt in 1 2 3; do
    code=$(curl -s -o /tmp/stop.out -w "%{http_code}" -X POST \
      "https://rest.runpod.io/v1/pods/${PID}/stop" \
      -H "Authorization: Bearer ${RUNPOD_API_KEY}")
    echo "stop attempt $attempt -> HTTP $code $(head -c 160 /tmp/stop.out)"
    [ "$code" = "200" ] || [ "$code" = "204" ] && break
    sleep 5
  done
  code=$(curl -s -o /tmp/term.out -w "%{http_code}" -X DELETE \
    "https://rest.runpod.io/v1/pods/${PID}" \
    -H "Authorization: Bearer ${RUNPOD_API_KEY}")
  echo "terminate -> HTTP $code $(head -c 160 /tmp/term.out)"
  # Last resort: find any pod with this name still running and stop it.
  python - <<'PY' || true
import os, json, urllib.request
key = os.environ.get("RUNPOD_API_KEY", "")
req = urllib.request.Request("https://rest.runpod.io/v1/pods",
                             headers={"Authorization": f"Bearer {key}"})
try:
    pods = json.load(urllib.request.urlopen(req, timeout=20))
    for p in pods if isinstance(pods, list) else []:
        if p.get("name", "").startswith("damage-detector-train") \
                and p.get("desiredStatus") == "RUNNING":
            u = f"https://rest.runpod.io/v1/pods/{p['id']}/stop"
            urllib.request.urlopen(urllib.request.Request(
                u, data=b"", headers={"Authorization": f"Bearer {key}"}),
                timeout=20)
            print("stopped by name:", p["id"])
except Exception as e:
    print("name-based stop failed:", e)
PY
}
trap finish EXIT

# RUN-ONCE GUARD — registered AFTER the trap, deliberately. RunPod restarts the
# container whenever dockerStartCmd exits, so a failing script loops (v4 ran 22
# times). The marker on the container disk survives those restarts and makes a
# second entry refuse to work. It sits below `trap finish EXIT` because the
# audit found it above: on the marker path the script exited before the trap
# existed, so the pod never attempted to stop itself — precisely the unattended
# path where self-stop matters most. Now the marker exit flows through finish()
# and its checked stop/terminate, retrying on every 5-minute restart cycle
# until one lands.
MARKER="$WORK/.attempted-$TAG"
if [ -e "$MARKER" ]; then
  echo "=== $TAG already attempted — refusing to re-run; stopping pod ==="
  sleep 60
  exit 0
fi
date -u > "$MARKER"

echo "=== env ==="
nvidia-smi || echo "NO GPU VISIBLE"
python -V; df -h /workspace | tail -1

echo "=== deps ==="
pip install -q --upgrade pip
# One package per line so a failure names itself in the log.
pip install -q huggingface_hub || exit 11
pip install -q onnxruntime     || exit 12

# Torch MUST come first and be >= 2.5. The base image ships 2.4.1, and current
# transformers refuses to enable its PyTorch integration below 2.5 — it prints
# "PyTorch was not found", carries on with tokenizers only, and rfdetr then dies
# on `cannot import name BackboneConfigMixin`. That import error names
# transformers and hides the real cause, which is the torch version. Upgrading
# here costs one large download and removes the whole class of confusion.
# Pick the torch build from the DRIVER ON THIS MACHINE, never a fixed index.
# The rented GPU is not a fixed target: v4 landed on driver 570.x / CUDA 12.8,
# v5 on 550.x / CUDA 12.4. A hardcoded cu124 was too old for the first and a
# hardcoded cu126 was too new for the second — same script, opposite failures,
# both reported as "the NVIDIA driver on your system is too old". Reading the
# driver first is the only version of this that survives whichever machine the
# scheduler hands us.
DRV=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -1)
CUDA_MM=$(nvidia-smi 2>/dev/null | sed -n 's/.*CUDA Version: *\([0-9]*\)\.\([0-9]*\).*/\1\2/p' | head -1)
echo "driver=$DRV cuda=$CUDA_MM"
case "${CUDA_MM:-124}" in
  12[89]|13*) IDX=cu128 ;;
  126|127)    IDX=cu126 ;;
  12[45])     IDX=cu124 ;;
  12[0123])   IDX=cu121 ;;
  *)          IDX=cu124 ;;
esac
echo "selected torch index: $IDX"
pip install -q --upgrade torch torchvision --index-url "https://download.pytorch.org/whl/$IDX" || exit 13
# The [train,loggers] extras are NOT optional here. Plain `pip install rfdetr`
# gives a package that imports perfectly and then refuses to train
# ("RF-DETR training dependencies are missing" / no module pytorch_lightning),
# which is why the previous smoke test passed and the run still died — 30
# minutes and a full dataset merge later.
# --ignore-installed blinker: the base image carries blinker 1.4 as a
# distutils-installed system package, which pip refuses to uninstall ("cannot
# accurately determine which files belong to it"), so a transitive upgrade
# request aborts the whole install. Ignoring that one package lets pip put its
# own copy alongside instead of failing.
pip install -q --ignore-installed blinker "rfdetr[train,loggers]" || exit 14
# So the smoke test now checks the TRAINING path, not just the import: the
# gate must fail on the same thing the real run would.
# CUDA is verified AFTER rfdetr, never before. v4 printed "torch 2.6.0+cu124
# cuda True" during its dependency check and then died at the first training
# call with "NVIDIA driver is too old (found version 12080)" — because
# installing rfdetr pulled its own torch build on top, and the machine's driver
# (570.x / CUDA 12.8) could not run it. Checking before the last install
# validated a torch that no longer existed by the time training started.
#
# So the gate below runs last, and does real GPU work rather than reading
# version strings: is_available() alone returned True on the build that then
# failed to initialise.
python - <<'PY' || exit 15
import torch, rfdetr, pytorch_lightning
from rfdetr import RFDETRBase
assert hasattr(RFDETRBase, "train"), "RFDETRBase has no train()"
print("torch", torch.__version__, "| lightning", pytorch_lightning.__version__)
assert torch.cuda.is_available(), "CUDA not available"
# Force a real allocation + kernel launch + bf16 probe: exactly the calls that
# blew up mid-run last time.
x = torch.randn(64, 64, device="cuda")
y = (x @ x).sum().item()
torch.cuda.is_bf16_supported()
torch.cuda.synchronize()
print("CUDA OK:", torch.cuda.get_device_name(0), "| matmul", round(y, 3))
PY

echo "=== fetch scripts ==="
python - <<'PY' || exit 20
import os
from huggingface_hub import hf_hub_download
for f in ("prepare_data.py", "train_detector.py", "merge_datasets.py",
          "manifest.json"):
    try:
        p = hf_hub_download(repo_id=os.environ["HF_REPO"], filename=f,
                            token=os.environ["HF_TOKEN"], local_dir="/workspace")
        print("got", p)
    except Exception as e:
        print("MISSING", f, e)
PY

echo "=== fetch + merge datasets ==="
python merge_datasets.py --manifest manifest.json --out prepared \
  --api-key "$ROBOFLOW_API_KEY" --work _sources \
  ${MAX_SOURCES:+--limit $MAX_SOURCES} || exit 30
du -sh prepared _sources || true

echo "=== train ==="
python train_detector.py --data prepared --out runs \
  --epochs "${EPOCHS:-15}" --batch-size "${BATCH:-8}" || exit 40

echo "=== publish ==="
python - <<'PY' || exit 50
import os, glob
from huggingface_hub import HfApi
api = HfApi(token=os.environ["HF_TOKEN"])
repo, tag = os.environ["HF_REPO"], os.environ.get("RUN_TAG", "run")
sent = 0
for pat in ("runs/**/*.onnx", "runs/**/*.pth", "runs/**/deploy.json",
            "prepared/labels.txt", "runs/**/results.json"):
    for p in glob.glob(pat, recursive=True):
        api.upload_file(path_or_fileobj=p,
                        path_in_repo=f"detector/{tag}/{os.path.basename(p)}",
                        repo_id=repo, token=os.environ["HF_TOKEN"])
        print("uploaded", p, os.path.getsize(p))
        sent += 1
print("uploaded_files:", sent)
assert sent, "nothing uploaded"
PY

echo "=== DONE ==="
