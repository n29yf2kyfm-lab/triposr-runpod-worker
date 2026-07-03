FROM runpod/pytorch:2.2.0-py3.10-cuda12.1.1-devel-ubuntu22.04

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y \
    git wget curl build-essential \
    libgl1-mesa-glx libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Clone TripoSR
RUN git clone https://github.com/VAST-AI-Research/TripoSR.git /app/TripoSR

WORKDIR /app/TripoSR

# Install TripoSR deps
RUN pip install --no-cache-dir -r requirements.txt

# Fix: reinstall torchmcubes with CUDA support
RUN pip uninstall -y torchmcubes && \
    pip install --no-cache-dir git+https://github.com/tatsy/torchmcubes.git

# Install runpod + extra deps
RUN pip install --no-cache-dir runpod requests Pillow trimesh huggingface_hub

# Copy handler
COPY handler.py /app/handler.py

WORKDIR /app

# Pre-download model weights at build time
# NOTE: multi-line python -c breaks Dockerfile parser if it starts with 'from'
# Use a script file instead
RUN python3 -c "import os; os.makedirs('/app/model', exist_ok=True)"
RUN python3 -c "from huggingface_hub import hf_hub_download; hf_hub_download('stabilityai/TripoSR', 'model.ckpt', local_dir='/app/model'); print('model.ckpt downloaded')"
RUN python3 -c "from huggingface_hub import hf_hub_download; hf_hub_download('stabilityai/TripoSR', 'config.yaml', local_dir='/app/model'); print('config.yaml downloaded')"

CMD ["python3", "-u", "/app/handler.py"]
