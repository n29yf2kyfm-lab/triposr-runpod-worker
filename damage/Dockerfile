# Damage scanner — RunPod serverless worker.
#
# ISOLATION: entirely separate from the vehicle (trellis2/) and building
# workers. Different tag (alamk123/damage-scan:*), endpoint, volume and bucket.
# Its CI triggers only on damage/**, so it cannot rebuild another product.
#
# ---------------------------------------------------------------------------
# WHY THIS IS A *runtime* BASE, NOT *devel*  (measured, not guessed)
#
# The first cut of this file copied the vehicle worker's
# nvidia/cuda:*-devel base. That produced a 10.6 GB image, and a live cold
# start on RunPod measured delayTime = 41 MINUTES against executionTime =
# 157 ms. On a serverless endpoint that scales to zero, image size IS
# cold-start latency, so the base image was the single dominant cost of the
# whole product.
#
# devel exists to give you nvcc. This worker compiles NOTHING at runtime, and
# the only thing that ever wanted nvcc at build time was flash-attn — which is
# an optional accelerator the code already degrades without (transformers
# falls back to eager attention). Trading it for ~3 GB and tens of minutes of
# cold start is not close.
#
# Also dropped: build-essential, cmake, ninja, git and the *-dev headers. They
# exist to compile native extensions; there are none here. The torch cu124
# wheels ship their own CUDA runtime libraries, so nothing here links against
# the system toolkit either.
# ---------------------------------------------------------------------------

FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
# no .pyc writing and no pip cache -> smaller layers
ENV PYTHONDONTWRITEBYTECODE=1
ENV PIP_NO_CACHE_DIR=1

# Runtime-only system packages. libgl1/libglib2.0-0 are needed by pillow/
# opencv-style image decoding paths; nothing else is.
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3.10 python3-pip \
      libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

RUN ln -sf /usr/bin/python3.10 /usr/bin/python && \
    ln -sf /usr/bin/pip3 /usr/bin/pip

# torch pinned to the cu124 wheels matching the base image. These wheels bundle
# the CUDA runtime they need, which is what makes the devel toolkit redundant.
RUN pip install --upgrade pip && \
    pip install torch==2.6.0 torchvision==0.21.0 \
      --index-url https://download.pytorch.org/whl/cu124

# The VLM stack. Qwen2.5-VL needs a recent transformers; qwen-vl-utils handles
# its image preprocessing; accelerate provides device_map="auto".
RUN pip install \
      "transformers>=4.49" accelerate safetensors huggingface_hub \
      qwen-vl-utils pillow numpy

# Serverless glue.
RUN pip install runpod requests

# ---------------------------------------------------------------------------
# Model cache on the mounted network volume.
#
# ATTACH A NETWORK VOLUME TO THE ENDPOINT. Without one, /runpod-volume is not
# persistent and Qwen2.5-VL's ~16 GB of weights are re-downloaded on EVERY
# cold start — a per-start cost, not a one-off. With a volume attached the
# weights are fetched once and every later worker starts from cache.
# ---------------------------------------------------------------------------
ENV HF_HOME=/runpod-volume/damage_hf_cache
ENV TORCH_HOME=/runpod-volume/damage_torch_cache
# DAMAGE_OUTPUT_DIR is deliberately NOT baked in: an endpoint only has
# /runpod-volume when a volume is attached, and paths.py resolves the writable
# location at runtime. Setting it here would override that check.

WORKDIR /app

# Source. Everything below rebuilds on code changes; everything above is cached.
COPY paths.py delivery.py progress.py validation.py handler.py \
     taxonomy.py severity.py repair.py quality.py analyze.py fusion.py \
     report.py compare.py preload_models.py /app/

# Optional: bake the VLM weights into the image for fully-offline operation
# (pair with OFFLINE=1). Adds ~16 GB, which is the opposite of what this file
# is optimised for — prefer a network volume. Build on a pod, not a CI runner.
ARG PRELOAD_MODELS=0
RUN --mount=type=secret,id=hf_token \
    if [ "$PRELOAD_MODELS" = "1" ]; then \
      HF_TOKEN=$(cat /run/secrets/hf_token 2>/dev/null || true) \
      python /app/preload_models.py; \
    fi

CMD ["python", "-u", "/app/handler.py"]
