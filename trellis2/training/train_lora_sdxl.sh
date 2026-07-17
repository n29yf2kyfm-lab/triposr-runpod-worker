#!/usr/bin/env bash
# SDXL LoRA training on a RunPod A40 pod (CUDA devel image).
# Usage: bash train_lora_sdxl.sh /workspace/data [output_name]
set -euo pipefail
DATA="${1:?usage: train_lora_sdxl.sh <data_dir> [name]}"
NAME="${2:-cars-v1}"
BASE="${T2I_MODEL:-SG161222/RealVisXL_V4.0_Lightning}"

pip install -q "diffusers[training]" accelerate transformers datasets peft bitsandbytes
git clone -q --depth 1 https://github.com/huggingface/diffusers /tmp/diffusers || true

accelerate launch /tmp/diffusers/examples/text_to_image/train_text_to_image_lora_sdxl.py \
  --pretrained_model_name_or_path "$BASE" \
  --train_data_dir "$DATA/img" \
  --caption_column text --image_column image \
  --resolution 1024 --random_flip \
  --train_batch_size 2 --gradient_accumulation_steps 4 \
  --max_train_steps 4000 --checkpointing_steps 1000 \
  --learning_rate 1e-4 --lr_scheduler cosine --lr_warmup_steps 100 \
  --mixed_precision fp16 --rank 32 \
  --validation_prompt "a 2024 Audi Q7 S line, district green metallic paint, SUV, three-quarter front view" \
  --output_dir "/workspace/out/$NAME"

echo "LoRA at /workspace/out/$NAME — copy to /runpod-volume/loras/$NAME"
