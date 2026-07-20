# LTX-Video runs on the GPU (diffusers), so we need a CUDA base. Same family as
# the other GPU workers in this repo.
FROM runpod/pytorch:2.2.0-py3.10-cuda12.1.1-devel-ubuntu22.04

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    git ffmpeg libgl1-mesa-glx libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY handler.py /app/handler.py

# NOTE: model weights (~LTX-Video transformer + T5 text encoder) are NOT baked
# into the image to keep it small and CI builds reliable. They download on the
# first cold start into the HF cache. For production, attach a RunPod network
# volume to the endpoint — the handler points HF_HOME at /runpod-volume so the
# download happens once and is reused across workers.

CMD ["python3", "-u", "/app/handler.py"]
