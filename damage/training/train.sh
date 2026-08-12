#!/usr/bin/env bash
# Bootstrap run on a rented RunPod GPU: fetch data, train, export ONNX, publish,
# then SHUT THE POD DOWN.
#
# The self-termination at the end is not tidiness, it is the whole safety
# design. A GPU pod left running after a finished job bills indefinitely, and
# this project has already paid for that lesson once. The trap fires on success
# and on failure alike, so a crashed training run costs minutes, not days.
#
# Required env: ROBOFLOW_API_KEY, HF_TOKEN, HF_REPO, RUNPOD_API_KEY, RUNPOD_POD_ID
set -uo pipefail

WORK=/workspace
mkdir -p "$WORK" && cd "$WORK"

shutdown_pod() {
  code=$?
  echo "=== exit code $code — terminating pod $RUNPOD_POD_ID ==="
  # Best effort, twice: losing the shutdown call is the expensive failure.
  for _ in 1 2; do
    curl -s -X POST "https://rest.runpod.io/v1/pods/${RUNPOD_POD_ID}/stop" \
      -H "Authorization: Bearer ${RUNPOD_API_KEY}" >/dev/null && break
    sleep 5
  done
}
trap shutdown_pod EXIT

echo "=== deps ==="
pip install -q --upgrade pip
pip install -q rfdetr onnxruntime huggingface_hub roboflow || exit 1

echo "=== fetch scripts ==="
python - <<'PY' || exit 1
import os
from huggingface_hub import hf_hub_download
for f in ("prepare_data.py", "train_detector.py"):
    p = hf_hub_download(repo_id=os.environ["HF_REPO"], filename=f,
                        token=os.environ["HF_TOKEN"], local_dir="/workspace")
    print("got", p)
PY

echo "=== fetch dataset ==="
curl -sL "$(curl -s "https://api.roboflow.com/ai-model-vapko/vehicle-damage-detection-9tpqp/2/coco?api_key=${ROBOFLOW_API_KEY}" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["export"]["link"])')" -o ds.zip || exit 1
mkdir -p raw && unzip -q -o ds.zip -d raw && echo "dataset unpacked"

echo "=== prepare ==="
python prepare_data.py --src raw --out prepared || exit 1

echo "=== train ==="
python train_detector.py --data prepared --out runs \
  --epochs "${EPOCHS:-12}" --batch-size "${BATCH:-4}" || exit 1

echo "=== publish ==="
python - <<'PY'
import os, glob
from huggingface_hub import HfApi
api = HfApi(token=os.environ["HF_TOKEN"])
repo = os.environ["HF_REPO"]
sent = 0
for pat in ("runs/**/*.onnx", "runs/**/*.pth", "runs/deploy.json",
            "prepared/labels.txt"):
    for p in glob.glob(pat, recursive=True):
        name = os.path.basename(p)
        api.upload_file(path_or_fileobj=p, path_in_repo=f"detector/{name}",
                        repo_id=repo, token=os.environ["HF_TOKEN"])
        print("uploaded", name, os.path.getsize(p))
        sent += 1
print("uploaded_files:", sent)
PY

echo "=== DONE ==="
