FROM runpod/pytorch:2.2.0-py3.10-cuda12.1.1-devel-ubuntu22.04

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y \
    git wget curl build-essential cmake ninja-build \
    libgl1-mesa-glx libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Clone TripoSR
RUN git clone https://github.com/VAST-AI-Research/TripoSR.git /app/TripoSR

WORKDIR /app/TripoSR

# Install TripoSR deps (skip torchmcubes from requirements — we install it separately)
RUN grep -v torchmcubes requirements.txt > requirements_no_mcubes.txt && \
    pip install --no-cache-dir -r requirements_no_mcubes.txt

# Fix: build torchmcubes with explicit CUDA arch flags so it compiles without a GPU present
# Targets: Ampere (8.0, 8.6), Turing (7.5), Volta (7.0), Ada (8.9) — covers all RunPod GPUs
ENV TORCH_CUDA_ARCH_LIST="7.0;7.5;8.0;8.6;8.9"
ENV FORCE_CUDA="1"
RUN pip install --no-cache-dir git+https://github.com/tatsy/torchmcubes.git

# Install runpod + extra deps
RUN pip install --no-cache-dir runpod requests Pillow trimesh huggingface_hub onnxruntime pooch scipy

# Copy handler
COPY handler.py /app/handler.py

WORKDIR /app

# Pre-download model weights at build time
RUN python3 -c "import os; os.makedirs('/app/model', exist_ok=True)"
RUN python3 -c "from huggingface_hub import hf_hub_download; hf_hub_download('stabilityai/TripoSR', 'model.ckpt', local_dir='/app/model'); print('model.ckpt downloaded')"
RUN python3 -c "from huggingface_hub import hf_hub_download; hf_hub_download('stabilityai/TripoSR', 'config.yaml', local_dir='/app/model'); print('config.yaml downloaded')"

CMD ["python3", "-u", "/app/handler.py"]
