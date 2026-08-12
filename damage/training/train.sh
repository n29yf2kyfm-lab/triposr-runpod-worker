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
  for _ in 1 2 3; do
    curl -s -X POST "https://rest.runpod.io/v1/pods/${PID}/stop" \
      -H "Authorization: Bearer ${RUNPOD_API_KEY}" | grep -q . && break
    sleep 5
  done
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
python -c "import torch,sys; sys.exit(0 if tuple(map(int,torch.__version__.split('.')[:2]))>=(2,5) else 1)" \
  || pip install -q --upgrade torch torchvision --index-url https://download.pytorch.org/whl/cu124 \
  || exit 13
python -c "import torch;print('torch', torch.__version__, 'cuda', torch.cuda.is_available())" || exit 13
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
python - <<'PY' || exit 15
import rfdetr, pytorch_lightning
from rfdetr import RFDETRBase
assert hasattr(RFDETRBase, "train"), "RFDETRBase has no train()"
print("rfdetr train deps OK; lightning", pytorch_lightning.__version__)
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
