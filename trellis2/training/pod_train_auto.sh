#!/usr/bin/env bash
# FULLY AUTONOMOUS car-LoRA training on a fresh RunPod GPU pod:
# Wikimedia dataset (licence-recorded) -> captions -> SDXL LoRA
# -> /runpod-volume/loras/cars-v1. Beacons via pod rename (needs
# RUNPOD_ACCOUNT_KEY; RunPod shadows RUNPOD_API_KEY inside pods).
set -euo pipefail
BRANCH="${BRANCH:-claude/custom-upgrade-path-2vszoo}"
RAW="https://raw.githubusercontent.com/n29yf2kyfm-lab/triposr-runpod-worker/$BRANCH/trellis2/training"
OUT="${OUT:-/runpod-volume/loras/cars-v1}"
DATA=/workspace/data
report() {
  [ -n "${RUNPOD_POD_ID:-}" ] && [ -n "${RUNPOD_ACCOUNT_KEY:-}" ] || return 0
  curl -s -X PATCH "https://rest.runpod.io/v1/pods/$RUNPOD_POD_ID" \
    -H "Authorization: Bearer $RUNPOD_ACCOUNT_KEY" -H "Content-Type: application/json" \
    -d "{\"name\": \"lora-$1\"}" > /dev/null || true
}
trap 'report FAILED' ERR

report 1-dataset
mkdir -p $DATA/img
curl -fsSL $RAW/model_manifest.json -o /workspace/manifest.json
curl -fsSL $RAW/fetch_dataset.py -o /workspace/fetch_dataset.py
pip install -q requests pillow
pip install -q 'rembg[cpu]' onnxruntime || echo 'rembg optional, continuing without white-bg'
python3 /workspace/fetch_dataset.py /workspace/manifest.json $DATA/img 2>&1 | tail -5
N=$(ls $DATA/img/*.jpg 2>/dev/null | wc -l)
echo "dataset: $N images"
[ "$N" -ge 200 ] || { report FAILED-smalldata; exit 1; }

report 2-deps
pip install -q "diffusers[training]" accelerate transformers datasets peft

report 3-train
BASE="${T2I_BASE:-SG161222/RealVisXL_V4.0_Lightning}"
git clone -q --depth 1 https://github.com/huggingface/diffusers /tmp/diffusers || true
accelerate launch --mixed_precision fp16 \
  /tmp/diffusers/examples/text_to_image/train_text_to_image_lora_sdxl.py \
  --pretrained_model_name_or_path "$BASE" \
  --train_data_dir "$DATA/img" --caption_column text --image_column image \
  --resolution 1024 --random_flip \
  --train_batch_size 2 --gradient_accumulation_steps 4 \
  --max_train_steps 3000 --checkpointing_steps 1000 \
  --learning_rate 1e-4 --lr_scheduler cosine --lr_warmup_steps 100 --rank 32 \
  --output_dir /workspace/out 2>&1 | tail -40

report 4-save
mkdir -p "$OUT"
cp /workspace/out/pytorch_lora_weights.safetensors "$OUT/" 2>/dev/null || cp -r /workspace/out/* "$OUT/"
cp $DATA/img/licences.csv "$OUT/" 2>/dev/null || true
echo "LoRA saved to $OUT"
report OK
sleep 120  # brief window to read logs, then idle for terminate
