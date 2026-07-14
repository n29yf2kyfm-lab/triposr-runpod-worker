# Hunyuan3D-2.1 serverless worker (shape + PBR texture -> GLB)
# LICENCE NOTE: Tencent Hunyuan3D 2.1 Community License — Territory EXCLUDES
# the EU, UK and South Korea. Deployment decision and liability recorded in
# docs/licence-evidence/. Owner instructed deployment 2026-07-14.
FROM nvidia/cuda:12.4.1-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# python 3.11 (not 3.10): every bpy wheel on PyPI is cp311/cp313-only, and
# hy3dpaint needs bpy for its OBJ->GLB export (convert_obj_to_glb).
RUN apt-get update && apt-get install -y --no-install-recommends \
    git wget curl build-essential ninja-build cmake \
    python3.11 python3.11-dev python3.11-venv python3.11-distutils \
    libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN ln -sf /usr/bin/python3.11 /usr/bin/python && \
    curl -sS https://bootstrap.pypa.io/get-pip.py | python3.11 && \
    ln -sf /usr/local/bin/pip3.11 /usr/bin/pip

WORKDIR /app
RUN git clone --depth 1 https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1.git
WORKDIR /app/Hunyuan3D-2.1

RUN pip install --upgrade pip && \
    pip install --no-cache-dir torch==2.5.1 torchvision==0.20.1 --index-url https://download.pytorch.org/whl/cu124

# strip cn mirrors + training/demo-only deps (deepspeed needs torch at build
# time and is training-only; gradio/fastapi/uvicorn/pythreejs are demo-web).
# basicsr/realesrgan import torch in setup.py -> install build deps first and
# disable PEP-517 build isolation so they can see the installed torch.
# bpy==4.0 was never published to PyPI; 4.2.x is the LTS line for py3.11 and
# the repo's mesh_utils already branches on >=4.2 APIs (shade_auto_smooth).
RUN sed -i '/extra-index-url/d; /deepspeed/d; /gradio/d; /fastapi/d; /uvicorn/d; /pythreejs/d; s/^bpy==.*/bpy==4.2.22/' requirements.txt && \
    pip install --no-cache-dir ninja==1.11.1.1 pybind11==2.13.4 wheel setuptools && \
    pip install --no-cache-dir --no-build-isolation -r requirements.txt && \
    pip install --no-cache-dir runpod requests && \
    pip install --no-cache-dir "setuptools<81"  # keep pkg_resources: hy3dpaint imports it, removed in setuptools 81+

# custom CUDA extensions; GPU-less CI build -> pin arch for RunPod pools:
# 8.6 (A5000/A6000) + 8.9 (L40S/4090) + PTX forward-compat
ENV TORCH_CUDA_ARCH_LIST="8.6;8.9+PTX"
# NOT compile_mesh_painter.sh: it shells out to `python3-config`, which this
# image doesn't have (only python3.11-config). The backticks then expand to
# nothing, the module is written without its .so suffix, c++ still exits 0,
# and the import fails silently at runtime (NameError: meshVerticeInpaint).
# Compile explicitly and prove the module imports before the image ships.
RUN cd hy3dpaint/custom_rasterizer && pip install --no-build-isolation -e . && cd ../.. && \
    cd hy3dpaint/DifferentiableRenderer && \
    c++ -O3 -Wall -shared -std=c++11 -fPIC $(python3.11 -m pybind11 --includes) \
        mesh_inpaint_processor.cpp \
        -o mesh_inpaint_processor$(python3.11-config --extension-suffix) && \
    python3.11 -c "from mesh_inpaint_processor import meshVerticeInpaint; print('mesh_inpaint_processor OK')" && \
    cd ../..

RUN mkdir -p hy3dpaint/ckpt && \
    wget -q https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth -P hy3dpaint/ckpt

COPY handler.py /app/Hunyuan3D-2.1/handler.py

# weights (~15GB) download from HF at first start onto the network volume
ENV HF_HOME=/runpod-volume/hf
CMD ["python", "handler.py"]
