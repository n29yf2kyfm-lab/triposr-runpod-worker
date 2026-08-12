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
  if [ -n "${RUNPOD_POD_ID:-}" ]; then
    for _ in 1 2 3; do
      curl -s -X POST "https://rest.runpod.io/v1/pods/${RUNPOD_POD_ID}/stop" \
        -H "Authorization: Bearer ${RUNPOD_API_KEY}" && break
      sleep 5
    done
  fi
}
trap finish EXIT

echo "=== env ==="
nvidia-smi || echo "NO GPU VISIBLE"
python -V; df -h /workspace | tail -1

echo "=== deps ==="
pip install -q --upgrade pip
# Pinned install, one package per line so a failure names itself in the log.
pip install -q huggingface_hub || exit 11
pip install -q onnxruntime       || exit 12
pip install -q rfdetr            || exit 13

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
