# SAM 3D Objects — RunPod serverless worker
#
# This mirrors the upstream doc/setup.md as closely as a container allows.
# SAM 3D Objects' environment is conda/mamba-based with editable installs plus
# pytorch3d + kaolin (both need nvcc), so we build inside a CUDA 12.1 *devel*
# image via micromamba rather than the runpod/pytorch base the mesh workers use.
#
# HEADS-UP (all confirmed from doc/setup.md):
#   * Requires an NVIDIA GPU with >= 32 GB VRAM at run time.
#   * The pytorch3d/kaolin/hydra-patch steps are the fragile part of the build;
#     they follow upstream's exact commands and index URLs.
#   * The weights repo facebook/sam-3d-objects is GATED under the SAM License —
#     accept it on huggingface.co and pass --build-arg HF_TOKEN=hf_xxx.
FROM nvidia/cuda:12.1.1-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
WORKDIR /app

RUN apt-get update && apt-get install -y \
    git wget curl bzip2 ca-certificates build-essential ninja-build \
    libgl1-mesa-glx libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# --- micromamba (drop-in mamba/conda) ---
RUN curl -Ls https://micro.mamba.pm/api/micromamba/linux-64/latest \
    | tar -xvj -C /usr/local bin/micromamba
ENV MAMBA_ROOT_PREFIX=/opt/micromamba
ENV PATH=/opt/micromamba/bin:$PATH

# --- clone the official repo ---
RUN git clone https://github.com/facebookresearch/sam-3d-objects.git /app/sam-3d-objects
WORKDIR /app/sam-3d-objects

# --- create the env exactly as upstream defines it ---
RUN micromamba create -y -n sam3d-objects -f environments/default.yml && \
    micromamba clean -a -y

# --- dependency install (verbatim from doc/setup.md) ---
# The two-step p3d install is upstream's documented fix for pytorch3d's broken
# torch dependency resolution.
ENV PIP_EXTRA_INDEX_URL="https://pypi.ngc.nvidia.com https://download.pytorch.org/whl/cu121"
RUN micromamba run -n sam3d-objects pip install -e '.[dev]'
RUN micromamba run -n sam3d-objects pip install -e '.[p3d]'

# Inference extras (kaolin find-links + the hydra patch script).
ENV PIP_FIND_LINKS="https://nvidia-kaolin.s3.us-east-2.amazonaws.com/torch-2.5.1_cu121.html"
RUN micromamba run -n sam3d-objects pip install -e '.[inference]'
RUN micromamba run -n sam3d-objects bash ./patching/hydra

# Worker runtime deps.
RUN micromamba run -n sam3d-objects pip install --no-cache-dir \
    runpod requests Pillow numpy

# --- download gated checkpoints at build time (needs HF_TOKEN with license accepted) ---
ARG HF_TOKEN
ENV SAM3D_TAG=hf
RUN micromamba run -n sam3d-objects pip install --no-cache-dir 'huggingface-hub[cli]<1.0' && \
    HF_TOKEN=${HF_TOKEN} micromamba run -n sam3d-objects hf download \
        --repo-type model --local-dir checkpoints/${SAM3D_TAG}-download \
        --max-workers 1 facebook/sam-3d-objects && \
    mv checkpoints/${SAM3D_TAG}-download/checkpoints checkpoints/${SAM3D_TAG} && \
    rm -rf checkpoints/${SAM3D_TAG}-download

# --- worker handler ---
COPY handler.py /app/sam-3d-objects/handler.py

CMD ["micromamba", "run", "-n", "sam3d-objects", "python3", "-u", "/app/sam-3d-objects/handler.py"]
