# Wan 2.2 I2V RunPod serverless worker — cinematic car clips + batch b-roll.
#
# Weights (~60GB) are NOT baked in: mount a RunPod network volume at
# /runpod-volume, run preload_models.py once from any pod, and cold starts
# read from the volume (HF_HOME below). Same convention as trellis2/.
#
# GPU sizing (see README.md for the cost math):
#   48GB (L40S/A6000)  - bf16 + CPU_OFFLOAD=1, the price/perf sweet spot
#   80GB (A100/H100)   - CPU_OFFLOAD=0 for max speed
#   24GB (4090)        - works with CPU_OFFLOAD=1 at 480p; 720p is tight

FROM runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# diffusers>=0.35 for Wan 2.2 MoE support (transformer_2, guidance_scale_2,
# load_into_transformer_2). ftfy is a transformers/T5 text-cleanup dep.
RUN pip install --no-cache-dir \
    "diffusers>=0.35.0" "transformers>=4.44" accelerate safetensors \
    peft ftfy imageio imageio-ffmpeg opencv-python-headless \
    runpod requests Pillow

WORKDIR /app

# Weights live on the network volume so cold starts don't pull 60GB.
ENV HF_HOME=/runpod-volume/hf_cache
ENV PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

COPY shots.py handler.py preload_models.py /app/

CMD ["python", "-u", "/app/handler.py"]
