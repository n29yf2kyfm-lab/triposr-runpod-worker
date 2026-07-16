# TRELLIS.2 (microsoft/TRELLIS.2-4B) RunPod serverless worker.
#
# This is the "own upgrade" of the trellis/ (TRELLIS v1) worker:
#   - v1  = microsoft/TRELLIS      (text-to-3D + image-to-3D, ~1-2B models)
#   - v2  = microsoft/TRELLIS.2-4B (image-to-3D + PBR texturing, 4B model,
#           O-Voxel structured latents, PBR/GLB with basecolor/roughness/
#           metallic/opacity)
#
# TRELLIS.2 drops text-to-3D but adds full PBR materials and higher-resolution
# geometry. It needs a >=24GB GPU (the 4B weights + O-Voxel decode); H100 / L40S
# / A100 / A6000 class. The build fixes below are carried over from the v1
# Dockerfile's hard-won lessons (see trellis/Dockerfile for the full autopsy of
# each one) and adapted to TRELLIS.2's extension set.

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

WORKDIR /app
# --recursive: TRELLIS.2 vendors o-voxel and other pieces as submodules, and the
# o-voxel CUDA extension is built from this in-tree checkout (setup.sh copies the
# local o-voxel/ dir, it is NOT pulled from PyPI).
RUN git clone -b main --recursive https://github.com/microsoft/TRELLIS.2.git

WORKDIR /app/TRELLIS.2

# TRELLIS.2's setup.sh pins these exactly (cu124, unlike v1's cu121).
RUN pip install --upgrade pip && \
    pip install torch==2.6.0 torchvision==0.21.0 --index-url https://download.pytorch.org/whl/cu124

# ---------------------------------------------------------------------------
# We bypass setup.sh entirely and replicate what each of its flags does. On the
# v1 worker its getopt-based CLI silently no-op'd inside Docker (printed --help
# and returned in 0.4s, installing nothing), which is what caused the whole
# "chase one missing module at a time" saga. Installing everything explicitly
# here removes that failure mode by construction. Flags reproduced below:
#   --basic --flash-attn --nvdiffrast --nvdiffrec --cumesh --o-voxel --flexgemm
# ---------------------------------------------------------------------------

# --basic : split into chunks so one bad wheel can't silently take out the batch
# (setup.sh runs it as one long line with no `set -e`).
RUN pip install --no-cache-dir imageio imageio-ffmpeg tqdm easydict opencv-python-headless ninja && \
    pip install --no-cache-dir trimesh transformers tensorboard pandas lpips zstandard && \
    pip install --no-cache-dir kornia timm && \
    pip install --no-cache-dir "git+https://github.com/EasternJournalist/utils3d.git@9a4eb15e4021b67b12c460c7057d642626897ec8"
# pillow-simd is a drop-in faster PIL that setup.sh installs after libjpeg-dev;
# if its build ever fails on a base image, drop this line and plain Pillow is
# already pulled in transitively.
RUN pip install --no-cache-dir --force-reinstall pillow-simd || pip install --no-cache-dir pillow

# GPU-less CI runner: nvcc can't auto-detect the target arch, so every native
# extension (o-voxel, CuMesh, FlexGEMM, nvdiffrec) must be told explicitly or it
# compiles for the wrong/no SM and crashes on first GPU use instead of at build.
# TRELLIS.2 is a >=24GB / datacenter-class model, so cover Ampere (8.0 A100,
# 8.6 A6000/3090), Ada (8.9 L40S/4090) and Hopper (9.0 H100); +PTX keeps it
# JIT-forward-compatible with anything newer.
ENV TORCH_CUDA_ARCH_LIST="8.0;8.6;8.9;9.0+PTX"
ENV FORCE_CUDA=1

# nvdiffrast declares its package metadata in pyproject.toml [project]. On v1,
# --no-build-isolation fell back to the container's stock (too-old) setuptools
# and silently produced a package named "UNKNOWN" with no module inside. Upgrade
# setuptools/wheel/ninja FIRST (as nvdiffrast's own README instructs) so this
# and every subsequent --no-build-isolation build reads modern metadata.
RUN pip install --no-cache-dir --upgrade "setuptools>=64" wheel ninja packaging

# --flash-attn : prebuilt wheel resolves fast; if pip has to compile it, MAX_JOBS
# caps parallel nvcc jobs so the build doesn't OOM the runner. --no-build-isolation
# so it sees the torch we already installed.
ENV MAX_JOBS=4
RUN pip install --no-cache-dir --no-build-isolation flash-attn==2.7.3

# --nvdiffrast (v0.4.0) and --nvdiffrec (JeffreyXiang renderutils fork). Both
# build native extensions whose setup.py imports torch, so build isolation would
# hide the installed torch -> "No module named torch". --no-build-isolation fixes
# it (same lesson as v1's diffoctreerast).
RUN git clone -b v0.4.0 https://github.com/NVlabs/nvdiffrast.git /tmp/extensions/nvdiffrast && \
    pip install --no-cache-dir --no-build-isolation /tmp/extensions/nvdiffrast
RUN git clone -b renderutils https://github.com/JeffreyXiang/nvdiffrec.git /tmp/extensions/nvdiffrec && \
    pip install --no-cache-dir --no-build-isolation /tmp/extensions/nvdiffrec

# --cumesh and --flexgemm : both have submodules (--recursive) and both compile
# CUDA under the arch list set above.
RUN git clone --recursive https://github.com/JeffreyXiang/CuMesh.git /tmp/extensions/CuMesh && \
    pip install --no-cache-dir --no-build-isolation /tmp/extensions/CuMesh
RUN git clone --recursive https://github.com/JeffreyXiang/FlexGEMM.git /tmp/extensions/FlexGEMM && \
    pip install --no-cache-dir --no-build-isolation /tmp/extensions/FlexGEMM

# --o-voxel : built from the in-tree checkout (this is the core TRELLIS.2 rep —
# O-Voxel post-processing / to_glb lives here), not from PyPI.
RUN cp -r /app/TRELLIS.2/o-voxel /tmp/extensions/o-voxel && \
    pip install --no-cache-dir --no-build-isolation /tmp/extensions/o-voxel

# Serverless glue.
RUN pip install --no-cache-dir runpod requests pillow

# ATTN_BACKEND: TRELLIS.2 uses flash-attn (installed above). SPCONV is not part
# of the v2 stack (O-Voxel replaces the sparse-conv path), so no SPCONV_ALGO here.
ENV ATTN_BACKEND=flash-attn
# 4B weights are large; keep them (and the HF cache) on the mounted RunPod
# network volume so cold starts don't redownload multi-GB checkpoints. Same
# convention as the v1 worker.
ENV HF_HOME=/runpod-volume/hf_cache
ENV TRANSFORMERS_CACHE=/runpod-volume/hf_cache
ENV TORCH_HOME=/runpod-volume/torch_cache
# Matches example.py: EXR reads for HDRI envmaps + expandable CUDA segments.
ENV OPENCV_IO_ENABLE_OPENEXR=1
ENV PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

COPY handler.py /app/handler.py

CMD ["python", "-u", "/app/handler.py"]
