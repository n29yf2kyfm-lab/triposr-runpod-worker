# Phase 0 — SAM 3D Body (DINOv3) on RunPod serverless
FROM pytorch/pytorch:2.4.0-cuda12.1-cudnn9-devel

ENV DEBIAN_FRONTEND=noninteractive
WORKDIR /workspace

# System deps for opencv / pyrender / detectron2, plus headless OSMesa OpenGL
# so pyrender doesn't crash for lack of a display in a serverless container.
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    ffmpeg \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libosmesa6-dev \
    libgl1-mesa-glx \
    xvfb \
    && rm -rf /var/lib/apt/lists/*

# Force pyrender into headless OSMesa mode (prevents OpenGL NullFunctionError).
ENV PYRENDER_PLATFORM=osmesa
ENV MUJOCO_GL=osmesa

# Official inference repo.
RUN git clone https://github.com/facebookresearch/sam-3d-body.git
WORKDIR /workspace/sam-3d-body

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Detectron2 — pinned commit per the repo INSTALL.md, no build isolation.
RUN pip install --no-cache-dir \
    'git+https://github.com/facebookresearch/detectron2.git@a1ce2f9' \
    --no-build-isolation --no-deps

# MoGe2 (camera field-of-view model used by the default demo pipeline).
RUN pip install --no-cache-dir git+https://github.com/microsoft/MoGe.git

# Cache the gated checkpoint on a RunPod Network Volume so cold starts don't
# re-download several GB each time.
ENV HF_HOME=/runpod-volume/hf-cache
ENV HUGGINGFACE_HUB_CACHE=/runpod-volume/hf-cache

COPY handler.py .
CMD ["python", "-u", "handler.py"]
