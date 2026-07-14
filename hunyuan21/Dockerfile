# Hunyuan3D-2.1 serverless worker (shape + PBR texture -> GLB)
# LICENCE NOTE: Tencent Hunyuan3D 2.1 Community License — Territory EXCLUDES
# the EU, UK and South Korea. Deployment decision and liability recorded in
# docs/licence-evidence/. Owner instructed deployment 2026-07-14.
FROM nvidia/cuda:12.4.1-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    git wget curl build-essential ninja-build cmake \
    python3.10 python3.10-dev python3-pip \
    libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN ln -sf /usr/bin/python3.10 /usr/bin/python && ln -sf /usr/bin/pip3 /usr/bin/pip

WORKDIR /app
RUN git clone --depth 1 https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1.git
WORKDIR /app/Hunyuan3D-2.1

RUN pip install --upgrade pip && \
    pip install --no-cache-dir torch==2.5.1 torchvision==0.20.1 --index-url https://download.pytorch.org/whl/cu124

# strip cn mirrors + training/demo-only deps (deepspeed needs torch at build
# time and is training-only; gradio/fastapi/uvicorn/pythreejs are demo-web).
# basicsr/realesrgan import torch in setup.py -> install build deps first and
# disable PEP-517 build isolation so they can see the installed torch.
RUN sed -i '/extra-index-url/d; /deepspeed/d; /gradio/d; /fastapi/d; /uvicorn/d; /pythreejs/d' requirements.txt && \
    pip install --no-cache-dir ninja==1.11.1.1 pybind11==2.13.4 wheel setuptools && \
    pip install --no-cache-dir --no-build-isolation -r requirements.txt && \
    pip install --no-cache-dir runpod requests

# custom CUDA extensions; GPU-less CI build -> pin arch for RunPod pools:
# 8.6 (A5000/A6000) + 8.9 (L40S/4090) + PTX forward-compat
ENV TORCH_CUDA_ARCH_LIST="8.6;8.9+PTX"
RUN cd hy3dpaint/custom_rasterizer && pip install --no-build-isolation -e . && cd ../.. && \
    cd hy3dpaint/DifferentiableRenderer && bash compile_mesh_painter.sh && cd ../..

RUN mkdir -p hy3dpaint/ckpt && \
    wget -q https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth -P hy3dpaint/ckpt

COPY handler.py /app/Hunyuan3D-2.1/handler.py

# weights (~15GB) download from HF at first start onto the network volume
ENV HF_HOME=/runpod-volume/hf
CMD ["python", "handler.py"]
