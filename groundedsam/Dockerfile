FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.10 python3.10-dev python3-pip \
    libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

RUN ln -sf /usr/bin/python3.10 /usr/bin/python && ln -sf /usr/bin/pip3 /usr/bin/pip

# Torch on CUDA 12.4 (matches the base image runtime).
RUN pip install --upgrade pip && \
    pip install --no-cache-dir torch==2.6.0 torchvision==0.21.0 --index-url https://download.pytorch.org/whl/cu124

# Grounding DINO + SAM ship inside transformers now, so no custom repos to
# compile (unlike the TRELLIS image). timm + accelerate are runtime deps of the
# GroundingDINO / SAM model code paths.
RUN pip install --no-cache-dir \
    "transformers>=4.44" accelerate timm \
    runpod requests pillow numpy

# Weights (grounding-dino-base ~700MB, sam-vit-huge ~2.5GB) cache on the mounted
# RunPod network volume so cold starts don't redownload them each time.
ENV HF_HOME=/runpod-volume/hf_cache
ENV TRANSFORMERS_CACHE=/runpod-volume/hf_cache
ENV PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

COPY handler.py /app/handler.py
WORKDIR /app
CMD ["python", "-u", "/app/handler.py"]
