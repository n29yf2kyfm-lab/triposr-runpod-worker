FROM nvidia/cuda:12.4.1-devel-ubuntu22.04

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
# --recursive: o-voxel and other pieces live as submodules inside the repo, and
# setup.sh copies o-voxel/ out of the checkout, so it must be present.
# PINNED to a known-good commit (2026-07-24) so builds are reproducible and
# upstream main cannot silently change our worker's behaviour. Bump the hash
# deliberately when upgrading; Alam-3D fine-tune work assumes this revision.
ARG TRELLIS2_COMMIT=75fbf0183001ed9876c8dbb35de6b68552ee08bd
RUN git clone https://github.com/microsoft/TRELLIS.2.git && \
    cd TRELLIS.2 && git checkout ${TRELLIS2_COMMIT} && \
    git submodule update --init --recursive

WORKDIR /app/TRELLIS.2

# TRELLIS.2 targets PyTorch 2.6.0 on CUDA 12.4 (per its setup.sh version table).
RUN pip install --upgrade pip && \
    pip install --no-cache-dir torch==2.6.0 torchvision==0.21.0 --index-url https://download.pytorch.org/whl/cu124

# GPU-less CI build: nvcc can't auto-detect the target SM, so extensions would
# compile for the wrong arch and crash on first GPU use. 8.6 covers RunPod's
# AMPERE_24 pool (RTX 3090 / A5000 / A6000, all >=24GB as TRELLIS.2 requires);
# +PTX keeps it JIT-forward-compatible with newer GPUs (Ada/Hopper).
ENV TORCH_CUDA_ARCH_LIST="8.6+PTX"
# Native extensions import torch inside their setup.py; pip's default build
# isolation hides the already-installed torch, so every extension below uses
# --no-build-isolation and we upgrade the build backend first. psutil + packaging
# are build-time imports for several of these setup.py files (flash-attn reads
# psutil to pick MAX_JOBS) — without build isolation they must be present in the
# real env or metadata generation fails ("No module named 'psutil'").
RUN pip install --no-cache-dir --upgrade "setuptools>=64" wheel ninja psutil packaging cmake

# --- setup.sh --basic, replicated explicitly ------------------------------
# setup.sh parses its long flags with getopt, which fails silently in a
# non-interactive container (proven on the v1 image: the whole `. ./setup.sh`
# step ran in <1s and only printed --help, installing nothing). So we run the
# exact commands from setup.sh directly instead of invoking its CLI.
RUN pip install --no-cache-dir imageio imageio-ffmpeg tqdm easydict \
        opencv-python-headless ninja trimesh transformers \
        tensorboard pandas lpips zstandard kornia timm && \
    pip install --no-cache-dir git+https://github.com/EasternJournalist/utils3d.git@9a4eb15e4021b67b12c460c7057d642626897ec8

# --- Extensions (CUDA), each --no-build-isolation -------------------------
# Flash-Attention compiles CUDA kernels from source here. MAX_JOBS is capped
# so the parallel nvcc jobs don't exhaust the ~16GB CI runner's RAM (unbounded
# MAX_JOBS OOM-kills the build); this trades a longer compile for reliability,
# and the gha layer cache means later builds reuse it.
ENV MAX_JOBS=2
RUN pip install --no-cache-dir flash-attn==2.7.3 --no-build-isolation

# nvdiffrast v0.4.0
RUN git clone -b v0.4.0 https://github.com/NVlabs/nvdiffrast.git /tmp/extensions/nvdiffrast && \
    pip install --no-cache-dir /tmp/extensions/nvdiffrast --no-build-isolation

# nvdiffrec (JeffreyXiang renderutils fork)
RUN git clone -b renderutils https://github.com/JeffreyXiang/nvdiffrec.git /tmp/extensions/nvdiffrec && \
    pip install --no-cache-dir /tmp/extensions/nvdiffrec --no-build-isolation

# CuMesh
RUN git clone --recursive https://github.com/JeffreyXiang/CuMesh.git /tmp/extensions/CuMesh && \
    pip install --no-cache-dir /tmp/extensions/CuMesh --no-build-isolation

# FlexGEMM
RUN git clone --recursive https://github.com/JeffreyXiang/FlexGEMM.git /tmp/extensions/FlexGEMM && \
    pip install --no-cache-dir /tmp/extensions/FlexGEMM --no-build-isolation

# O-Voxel (the field-free sparse-voxel post-processor; ships in-repo).
RUN pip install --no-cache-dir /app/TRELLIS.2/o-voxel --no-build-isolation

# --- Runtime deps ---------------------------------------------------------
RUN pip install --no-cache-dir runpod requests pillow

ENV SPCONV_ALGO=native
ENV ATTN_BACKEND=flash-attn
ENV OPENCV_IO_ENABLE_OPENEXR=1
ENV PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
# Model weights + HF cache live on the mounted RunPod network volume so cold
# starts don't redownload the multi-GB TRELLIS.2-4B checkpoint each time.
ENV HF_HOME=/runpod-volume/hf_cache
ENV TRANSFORMERS_CACHE=/runpod-volume/hf_cache
ENV TORCH_HOME=/runpod-volume/torch_cache

COPY handler.py /app/handler.py
COPY alam3d_multiview.py /app/alam3d_multiview.py

CMD ["python", "-u", "/app/handler.py"]
