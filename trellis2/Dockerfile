# TRELLIS.2 RunPod serverless worker — built from OUR VENDORED COPY of the
# TRELLIS.2 code (see ./TRELLIS.2/), not from Microsoft's repo at build time.
#
# The code was vendored from microsoft/TRELLIS.2 at the commit recorded in
# TRELLIS.2/UPSTREAM_COMMIT and is now maintained/modified in THIS repo:
# builds are reproducible (no upstream drift) and every code change lands
# through our own git history. See TRELLIS.2/WORKER_CHANGES.md for the list
# of modifications relative to upstream.
#
# Upgrade lineage: trellis/ (v1, microsoft/TRELLIS) -> trellis2/ (this, 4B
# O-Voxel model with full PBR). Needs a >=24GB GPU (L40S/A6000/A100/H100).
# The build fixes below are carried over from the v1 Dockerfile's hard-won
# lessons (see trellis/Dockerfile for the autopsy of each).

FROM nvidia/cuda:12.4.1-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    git wget curl build-essential ninja-build \
    python3.10 python3.10-dev python3-pip \
    libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 ffmpeg libjpeg-dev \
    && rm -rf /var/lib/apt/lists/*

RUN ln -sf /usr/bin/python3.10 /usr/bin/python && \
    ln -sf /usr/bin/pip3 /usr/bin/pip

# TRELLIS.2's setup.sh pins these exactly (cu124, unlike v1's cu121).
RUN pip install --upgrade pip && \
    pip install torch==2.6.0 torchvision==0.21.0 --index-url https://download.pytorch.org/whl/cu124

# ---------------------------------------------------------------------------
# Dependencies are replicated from upstream setup.sh's flags explicitly
# (--basic --flash-attn --nvdiffrast --nvdiffrec --cumesh --o-voxel
# --flexgemm) — on the v1 worker, setup.sh's getopt CLI silently no-op'd
# inside Docker. Installing everything explicitly removes that failure mode.
# Deps are installed BEFORE our source is copied in, so code edits don't
# invalidate these expensive cached layers.
# ---------------------------------------------------------------------------

# --basic : split into chunks so one bad wheel can't silently take out the batch.
RUN pip install --no-cache-dir imageio imageio-ffmpeg tqdm easydict opencv-python-headless ninja && \
    pip install --no-cache-dir trimesh transformers tensorboard pandas lpips zstandard && \
    pip install --no-cache-dir kornia timm && \
    pip install --no-cache-dir "git+https://github.com/EasternJournalist/utils3d.git@9a4eb15e4021b67b12c460c7057d642626897ec8"
# pillow-simd is a drop-in faster PIL; if its build ever fails, fall back to Pillow.
RUN pip install --no-cache-dir --force-reinstall pillow-simd || pip install --no-cache-dir pillow

# GPU-less CI runner: nvcc can't auto-detect the target arch, so every native
# extension must be told explicitly or it compiles for the wrong/no SM and
# crashes on first GPU use instead of at build. Ampere (8.0 A100, 8.6 A6000),
# Ada (8.9 L40S/4090), Hopper (9.0 H100); +PTX for JIT forward-compat.
ENV TORCH_CUDA_ARCH_LIST="8.0;8.6;8.9;9.0+PTX"
ENV FORCE_CUDA=1

# Upgrade setuptools/wheel/ninja BEFORE any --no-build-isolation build: on v1,
# stock setuptools couldn't read pyproject [project] metadata and nvdiffrast
# silently installed as an empty package named "UNKNOWN".
RUN pip install --no-cache-dir --upgrade "setuptools>=64" wheel ninja packaging

# --flash-attn : MAX_JOBS caps parallel nvcc if pip falls back to a source build.
ENV MAX_JOBS=4
RUN pip install --no-cache-dir --no-build-isolation flash-attn==2.7.3

# --nvdiffrast (v0.4.0) / --nvdiffrec : native extensions whose setup.py imports
# torch -> --no-build-isolation so they see the torch installed above.
RUN git clone -b v0.4.0 https://github.com/NVlabs/nvdiffrast.git /tmp/extensions/nvdiffrast && \
    pip install --no-cache-dir --no-build-isolation /tmp/extensions/nvdiffrast
RUN git clone -b renderutils https://github.com/JeffreyXiang/nvdiffrec.git /tmp/extensions/nvdiffrec && \
    pip install --no-cache-dir --no-build-isolation /tmp/extensions/nvdiffrec

# --cumesh / --flexgemm : both have submodules and compile CUDA under the arch
# list set above.
RUN git clone --recursive https://github.com/JeffreyXiang/CuMesh.git /tmp/extensions/CuMesh && \
    pip install --no-cache-dir --no-build-isolation /tmp/extensions/CuMesh
RUN git clone --recursive https://github.com/JeffreyXiang/FlexGEMM.git /tmp/extensions/FlexGEMM && \
    pip install --no-cache-dir --no-build-isolation /tmp/extensions/FlexGEMM

# Text-to-3D stage 1: diffusion text-to-image (SDXL by default, override with
# T2I_MODEL env). TRELLIS.2 has no native text mode, so the worker renders the
# prompt to an image first, then runs image-to-3D on it.
RUN pip install --no-cache-dir diffusers accelerate safetensors

# Serverless glue.
RUN pip install --no-cache-dir runpod requests

# ---------------------------------------------------------------------------
# OUR source. Everything below rebuilds on code changes; everything above
# stays cached.
# ---------------------------------------------------------------------------
COPY TRELLIS.2 /app/TRELLIS.2

# --o-voxel : built from OUR vendored source. The eigen headers (23MB of
# third-party code we never modify) are not vendored — fetch them at the exact
# commit upstream's .gitmodules pinned, into the path o-voxel/setup.py expects.
RUN git init /app/TRELLIS.2/o-voxel/third_party/eigen && \
    cd /app/TRELLIS.2/o-voxel/third_party/eigen && \
    git remote add origin https://gitlab.com/libeigen/eigen.git && \
    git fetch --depth 1 origin 21e4582d1739107337a03460c81412981130373e && \
    git checkout FETCH_HEAD
RUN pip install --no-cache-dir --no-build-isolation /app/TRELLIS.2/o-voxel

# ATTN_BACKEND: TRELLIS.2 uses flash-attn. (No SPCONV in the v2 stack — O-Voxel
# replaces the sparse-conv path.)
ENV ATTN_BACKEND=flash-attn
# 4B weights live on the mounted RunPod network volume so cold starts don't
# redownload multi-GB checkpoints. Same convention as the v1 worker.
ENV HF_HOME=/runpod-volume/hf_cache
ENV TRANSFORMERS_CACHE=/runpod-volume/hf_cache
ENV TORCH_HOME=/runpod-volume/torch_cache
# Matches upstream example.py: EXR reads for HDRI envmaps + expandable CUDA segments.
ENV OPENCV_IO_ENABLE_OPENEXR=1
ENV PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

COPY handler.py /app/handler.py

CMD ["python", "-u", "/app/handler.py"]
