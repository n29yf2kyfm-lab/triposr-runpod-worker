FROM nvidia/cuda:12.1.0-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    git wget curl build-essential ninja-build \
    python3.10 python3.10-dev python3-pip \
    libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN ln -sf /usr/bin/python3.10 /usr/bin/python && \
    ln -sf /usr/bin/pip3 /usr/bin/pip

WORKDIR /app
RUN git clone --recurse-submodules https://github.com/microsoft/TRELLIS.git

WORKDIR /app/TRELLIS

RUN pip install --upgrade pip && \
    pip install torch==2.4.0 torchvision==0.19.0 --index-url https://download.pytorch.org/whl/cu121

# This build runs on a GPU-less CI runner, so nvcc can't auto-detect the target
# architecture — without this, extensions silently compile for the wrong (or no)
# SM and the container crashes on first real GPU use instead of failing the build.
# 8.6 covers RunPod's AMPERE_24 pool (RTX 3090 / A5000 / A6000); +PTX keeps it
# forward-compatible with newer architectures via JIT.
ENV TORCH_CUDA_ARCH_LIST="8.6+PTX"

# Installs xformers, spconv, nvdiffrast, diffoctreerast, mip-splatting (gaussian
# rasterizer) and kaolin per TRELLIS's own setup script. This step compiles CUDA
# extensions and is the most likely place a version mismatch will surface.
RUN chmod +x setup.sh && \
    . ./setup.sh --basic --xformers --spconv --diffoctreerast --mipgaussian --kaolin --nvdiffrast

RUN pip install --no-cache-dir runpod requests pillow

ENV SPCONV_ALGO=native
ENV ATTN_BACKEND=xformers
# Model weights and HF cache are expected to live on the mounted RunPod network
# volume (kyh32l0npu / "hunyuan3d-models", 200GB, EU-SE-1) instead of the image,
# so cold starts don't redownload multi-GB checkpoints every time.
ENV HF_HOME=/runpod-volume/hf_cache
ENV TRANSFORMERS_CACHE=/runpod-volume/hf_cache
ENV TORCH_HOME=/runpod-volume/torch_cache

COPY handler.py /app/handler.py

CMD ["python", "-u", "/app/handler.py"]
