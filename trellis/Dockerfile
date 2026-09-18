FROM nvidia/cuda:12.1.0-devel-ubuntu22.04
ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends \
    git wget curl ca-certificates build-essential ninja-build \
    python3.10 python3.10-dev python3.10-venv \
    libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 ffmpeg \
    && rm -rf /var/lib/apt/lists/*
RUN python3.10 -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"
COPY constraints.txt /app/constraints.txt
ENV PIP_CONSTRAINT=/app/constraints.txt
RUN python -m pip install --no-cache-dir --upgrade pip setuptools wheel ninja packaging
RUN python -m pip install --no-cache-dir torch torchvision xformers --index-url https://download.pytorch.org/whl/cu121

WORKDIR /app
RUN git clone https://github.com/microsoft/TRELLIS.git && \
    git -C TRELLIS checkout --detach 442aa1e1afb9014e80681d3bf604e8d728a86ee7 && \
    git -C TRELLIS submodule update --init --recursive
WORKDIR /app/TRELLIS
RUN python -m pip install --no-cache-dir pillow imageio imageio-ffmpeg tqdm easydict \
    opencv-python-headless scipy rembg onnxruntime trimesh open3d xatlas pyvista \
    pymeshfix igraph transformers omegaconf && \
    python -m pip install --no-cache-dir "git+https://github.com/EasternJournalist/utils3d.git@9a4eb15e4021b67b12c460c7057d642626897ec8"
ENV TORCH_CUDA_ARCH_LIST="8.6+PTX" MAX_JOBS=2
RUN python -m pip install --no-cache-dir spconv-cu120
RUN mkdir -p /tmp/extensions && \
    git clone https://github.com/JeffreyXiang/diffoctreerast.git /tmp/extensions/diffoctreerast && \
    git -C /tmp/extensions/diffoctreerast checkout --detach b09c20b84ec3aace4729e6e18a613112320eca3a && \
    git -C /tmp/extensions/diffoctreerast submodule update --init --recursive && \
    python -m pip install --no-cache-dir --no-build-isolation /tmp/extensions/diffoctreerast
RUN git clone https://github.com/autonomousvision/mip-splatting.git /tmp/extensions/mip-splatting && \
    git -C /tmp/extensions/mip-splatting checkout --detach dda02ab5ecf45d6edb8c540d9bb65c7e451345a9 && \
    git -C /tmp/extensions/mip-splatting submodule update --init --recursive && \
    python -m pip install --no-cache-dir --no-build-isolation /tmp/extensions/mip-splatting/submodules/diff-gaussian-rasterization/
RUN python -m pip install --no-cache-dir --only-binary=kaolin kaolin -f https://nvidia-kaolin.s3.us-east-2.amazonaws.com/torch-2.4.0_cu121.html
RUN git clone https://github.com/NVlabs/nvdiffrast.git /tmp/extensions/nvdiffrast && \
    git -C /tmp/extensions/nvdiffrast checkout --detach 253ac4fcea7de5f396371124af597e6cc957bfae && \
    python -m pip install --no-cache-dir --no-build-isolation /tmp/extensions/nvdiffrast
RUN python -m pip install --no-cache-dir runpod requests urllib3 pillow
ENV SPCONV_ALGO=native ATTN_BACKEND=xformers
ENV HF_HOME=/runpod-volume/hf_cache TRANSFORMERS_CACHE=/runpod-volume/hf_cache TORCH_HOME=/runpod-volume/torch_cache
ENV TRELLIS_OUTPUT_DIR=/runpod-volume/outputs/trellis-v1
ARG BUILD_REVISION=unknown
ENV BUILD_REVISION=${BUILD_REVISION}
COPY handler.py input_safety.py output_safety.py verify_runtime.py /app/
RUN python -m pip check && python /app/verify_runtime.py > /app/import-check.json && python -m pip freeze --all > /app/resolved-requirements.txt
CMD ["python","-u","/app/handler.py"]
