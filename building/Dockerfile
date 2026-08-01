# Building scanner — RunPod serverless worker.
#
# ISOLATION: this image is entirely separate from the live vehicle worker.
# Different tag (alamk123/building-scan:*), different endpoint, different
# volume, different bucket. Its CI only triggers on building/**, and the
# vehicle CI only on trellis2/**, so neither can rebuild the other.
#
# Every build fix below is carried over from the vehicle worker's Dockerfile,
# where each one was earned the hard way. See trellis2/Dockerfile for the
# autopsy of each. They apply here because COLMAP, Open3D, PDAL and the
# feed-forward reconstruction models have exactly the same build hazards.

FROM nvidia/cuda:12.4.1-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# ---------------------------------------------------------------------------
# System dependencies.
#
# COLMAP comes from apt rather than source: the distro build is older than
# upstream but it is the QUALITY path, not the default path, and an hour of
# CMake on a CI runner to gain a point release is a poor trade. Swap to a
# source build when a specific upstream feature is actually needed.
# ---------------------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
    git wget curl build-essential cmake ninja-build \
    python3.10 python3.10-dev python3-pip \
    libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 \
    ffmpeg libjpeg-dev libpng-dev \
    colmap \
    libgeos-dev libproj-dev \
    && rm -rf /var/lib/apt/lists/*

RUN ln -sf /usr/bin/python3.10 /usr/bin/python && \
    ln -sf /usr/bin/pip3 /usr/bin/pip

# torch first, pinned to the cu124 wheels matching the base image.
RUN pip install --upgrade pip && \
    pip install torch==2.6.0 torchvision==0.21.0 \
      --index-url https://download.pytorch.org/whl/cu124

# GPU-less CI runner: nvcc cannot auto-detect the target arch, so every
# native extension must be told explicitly or it compiles for no SM and
# crashes on first GPU use instead of at build time. Ampere (8.0 A100,
# 8.6 A6000), Ada (8.9 L40S), Hopper (9.0 H100); +PTX for JIT forward-compat.
ENV TORCH_CUDA_ARCH_LIST="8.0;8.6;8.9;9.0+PTX"
ENV FORCE_CUDA=1
# Cap parallel nvcc — an uncapped build OOMs a CI runner.
ENV MAX_JOBS=4

# Upgrade setuptools BEFORE any --no-build-isolation build. On the vehicle
# worker, stock setuptools could not read pyproject [project] metadata and
# nvdiffrast silently installed as an empty package named "UNKNOWN".
RUN pip install --no-cache-dir --upgrade "setuptools>=64" wheel ninja packaging

# ---------------------------------------------------------------------------
# Python dependencies, split into chunks so one bad wheel cannot silently
# take out the whole batch. Installed BEFORE our source is copied, so code
# edits reuse every cached layer.
# ---------------------------------------------------------------------------

# Geometry and point cloud core.
RUN pip install --no-cache-dir \
      numpy scipy scikit-image scikit-learn opencv-python-headless pillow

RUN pip install --no-cache-dir \
      open3d==0.19.0 trimesh pye57 laspy plyfile

# BIM. ifcopenshell publishes manylinux wheels; shapely needs the geos
# headers installed above.
RUN pip install --no-cache-dir \
      ifcopenshell shapely ezdxf pyquaternion networkx

# Reconstruction. MapAnything is the primary engine — Apache 2.0, metric by
# design, and a modular interface that runs VGGT/DUSt3R/MASt3R/Pi3-X as
# swappable backends, so a better model replaces it without a rewrite.
# Installed from source at a pinned ref for reproducibility.
ARG MAPANYTHING_REF=main
RUN pip install --no-cache-dir --no-build-isolation \
      "git+https://github.com/facebookresearch/map-anything.git@${MAPANYTHING_REF}" \
    || echo "WARN: map-anything install failed — reconstruct mode will report unavailable"

# Vision models for Condition Mode (Phase 5). transformers pulls the VLM
# path; ultralytics provides the YOLO stage that locates before SAM 2
# segments — the pattern the crack-segmentation literature converged on.
RUN pip install --no-cache-dir \
      transformers accelerate safetensors huggingface_hub

# Serverless glue.
RUN pip install --no-cache-dir runpod requests pyyaml

# ---------------------------------------------------------------------------
# Caches on the mounted network volume so cold starts do not redownload
# multi-GB checkpoints. Same convention as the vehicle worker — but a
# DIFFERENT volume, so the two products cannot interfere.
# ---------------------------------------------------------------------------
ENV HF_HOME=/runpod-volume/building_hf_cache
ENV TORCH_HOME=/runpod-volume/building_torch_cache
ENV BUILDING_OUTPUT_DIR=/runpod-volume/building-outputs

WORKDIR /app

# ---------------------------------------------------------------------------
# Our source. Everything below rebuilds on code changes; everything above
# stays cached.
# ---------------------------------------------------------------------------
COPY validation.py delivery.py progress.py handler.py preload_models.py /app/
COPY osgb.py roof_geometry.py roof.py solar.py scale.py reconstruct.py /app/
# Phase modules land here as each phase ships; the handler imports them
# lazily and reports "not implemented" until they exist.
COPY *.py /app/

# Optional: bake model weights into the image for fully-offline operation.
# Pair with OFFLINE=1 on the endpoint. Adds several GB, so build this variant
# on a pod rather than a stock CI runner.
ARG PRELOAD_MODELS=0
RUN --mount=type=secret,id=hf_token \
    if [ "$PRELOAD_MODELS" = "1" ]; then \
      HF_TOKEN=$(cat /run/secrets/hf_token 2>/dev/null || true) \
      python /app/preload_models.py; \
    fi

CMD ["python", "-u", "/app/handler.py"]
