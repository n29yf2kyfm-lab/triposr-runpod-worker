# Damage scanner — RunPod serverless worker.
#
# ISOLATION: entirely separate from the vehicle (trellis2/) and building
# workers. Different tag (alamk123/damage-scan:*), endpoint, volume and bucket.
# Its CI triggers only on damage/**, so it cannot rebuild another product.
#
# Lighter than the building image: this worker needs one vision model, not the
# COLMAP/Open3D/reconstruction stack. The CUDA build lessons still apply to the
# VLM's kernels (flash-attn), so the arch list and setuptools ordering carry
# over from the vehicle Dockerfile where they were earned.

FROM nvidia/cuda:12.4.1-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    git wget curl build-essential \
    python3.10 python3.10-dev python3-pip \
    libgl1 libglib2.0-0 libjpeg-dev libpng-dev \
    && rm -rf /var/lib/apt/lists/*

RUN ln -sf /usr/bin/python3.10 /usr/bin/python && \
    ln -sf /usr/bin/pip3 /usr/bin/pip

# torch first, pinned to the cu124 wheels matching the base image.
RUN pip install --upgrade pip && \
    pip install torch==2.6.0 torchvision==0.21.0 \
      --index-url https://download.pytorch.org/whl/cu124

# GPU-less CI runner: nvcc can't auto-detect the target arch. Ampere (8.0/8.6),
# Ada (8.9), Hopper (9.0); +PTX for JIT forward-compat. Same as the other
# workers' Dockerfiles.
ENV TORCH_CUDA_ARCH_LIST="8.0;8.6;8.9;9.0+PTX"
ENV FORCE_CUDA=1
ENV MAX_JOBS=4

# Upgrade setuptools BEFORE any --no-build-isolation build (the "UNKNOWN"
# empty-package trap the vehicle worker hit).
RUN pip install --no-cache-dir --upgrade "setuptools>=64" wheel ninja packaging

# The VLM stack. Qwen2.5-VL needs a recent transformers; qwen-vl-utils handles
# its image preprocessing. accelerate provides device_map="auto".
RUN pip install --no-cache-dir \
      "transformers>=4.49" accelerate safetensors huggingface_hub \
      qwen-vl-utils pillow

# flash-attn speeds the VLM up materially; a build failure must not sink the
# image — the model runs (slower) with eager attention if it's absent.
RUN pip install --no-cache-dir --no-build-isolation flash-attn \
    || echo "WARN: flash-attn build failed — VLM will use eager attention"

# Serverless glue.
RUN pip install --no-cache-dir runpod requests

# Caches on the mounted network volume — a DIFFERENT volume from the other
# workers, so the products cannot interfere.
ENV HF_HOME=/runpod-volume/damage_hf_cache
ENV TORCH_HOME=/runpod-volume/damage_torch_cache
# DAMAGE_OUTPUT_DIR is deliberately NOT baked in: an endpoint only has
# /runpod-volume when a volume is attached, and paths.py resolves the writable
# location at runtime. Set it on the endpoint only when a volume really exists.

WORKDIR /app

# Source. Everything below rebuilds on code changes; everything above is cached.
COPY paths.py delivery.py progress.py validation.py handler.py \
     taxonomy.py severity.py repair.py quality.py analyze.py fusion.py \
     report.py compare.py preload_models.py /app/

# Optional: bake the VLM weights in for fully-offline operation (pair with
# OFFLINE=1). Adds several GB — build this variant on a pod, not a CI runner.
ARG PRELOAD_MODELS=0
RUN --mount=type=secret,id=hf_token \
    if [ "$PRELOAD_MODELS" = "1" ]; then \
      HF_TOKEN=$(cat /run/secrets/hf_token 2>/dev/null || true) \
      python /app/preload_models.py; \
    fi

CMD ["python", "-u", "/app/handler.py"]
