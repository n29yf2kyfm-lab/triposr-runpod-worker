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

# setup.sh --basic runs one big `pip install a b c ... z` line (no requirements.txt
# exists in this repo). setup.sh has no `set -e`, so when that command fails
# outright on one package, the whole install is silently skipped and the Docker
# build still reports success -- confirmed by two sequential crashes (easydict,
# then rembg) that are BOTH in that exact line. Installing it explicitly here,
# split into smaller chunks so one bad wheel doesn't take out the whole batch.
RUN pip install --no-cache-dir pillow imageio imageio-ffmpeg tqdm easydict opencv-python-headless scipy ninja && \
    pip install --no-cache-dir rembg onnxruntime && \
    pip install --no-cache-dir trimesh open3d xatlas pyvista pymeshfix igraph transformers && \
    pip install --no-cache-dir "git+https://github.com/EasternJournalist/utils3d.git@9a4eb15e4021b67b12c460c7057d642626897ec8" && \
    pip install --no-cache-dir omegaconf

# This build runs on a GPU-less CI runner, so nvcc can't auto-detect the target
# architecture — without this, extensions silently compile for the wrong (or no)
# SM and the container crashes on first real GPU use instead of failing the build.
# 8.6 covers RunPod's AMPERE_24 pool (RTX 3090 / A5000 / A6000); +PTX keeps it
# forward-compatible with newer architectures via JIT.
ENV TORCH_CUDA_ARCH_LIST="8.6+PTX"

# setup.sh's own CLI is broken in this container: `getopt` fails to parse its
# long options here, so `. ./setup.sh --basic --xformers ...` silently prints
# --help and returns in under a second, never running ANY of the install logic
# it was told to (confirmed in a CI log: the whole RUN step took 0.4s and its
# only output was the usage text). That's the actual root cause behind every
# "missing module" crash we chased one at a time (easydict, rembg, kaolin...) --
# it was never a case of individual packages failing, the entire block was a
# no-op. Replicating each install explicitly, matching torch==2.4.0 + cu121
# exactly as setup.sh's own version tables specify, bypassing its CLI entirely.
RUN pip install --no-cache-dir xformers==0.0.27.post2 --index-url https://download.pytorch.org/whl/cu121
RUN pip install --no-cache-dir spconv-cu120
RUN mkdir -p /tmp/extensions && \
    git clone --recurse-submodules https://github.com/JeffreyXiang/diffoctreerast.git /tmp/extensions/diffoctreerast && \
    pip install --no-cache-dir /tmp/extensions/diffoctreerast
RUN mkdir -p /tmp/extensions && \
    git clone https://github.com/autonomousvision/mip-splatting.git /tmp/extensions/mip-splatting && \
    pip install --no-cache-dir /tmp/extensions/mip-splatting/submodules/diff-gaussian-rasterization/
RUN pip install --no-cache-dir kaolin -f https://nvidia-kaolin.s3.us-east-2.amazonaws.com/torch-2.4.0_cu121.html
RUN mkdir -p /tmp/extensions && \
    git clone https://github.com/NVlabs/nvdiffrast.git /tmp/extensions/nvdiffrast && \
    pip install --no-cache-dir /tmp/extensions/nvdiffrast

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
