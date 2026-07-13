FROM runpod/pytorch:2.2.0-py3.10-cuda12.1.1-devel-ubuntu22.04

WORKDIR /app

# System deps (ffmpeg is required to encode the output mp4)
RUN apt-get update && apt-get install -y \
    git ffmpeg libgl1-mesa-glx libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Python deps
RUN pip install --no-cache-dir \
    runpod requests Pillow \
    "diffusers>=0.32.0" transformers accelerate safetensors \
    imageio imageio-ffmpeg sentencepiece

COPY handler.py /app/handler.py

# Model selection (override at deploy time if you want CogVideoX):
#   MODEL_ID=Lightricks/LTX-Video           MODEL_KIND=ltx        (default, fast)
#   MODEL_ID=THUDM/CogVideoX-5b             MODEL_KIND=cogvideox  (Apache-2.0)
ENV MODEL_ID="Lightricks/LTX-Video"
ENV MODEL_KIND="ltx"

# OPTIONAL: pre-download weights at build time so the first request isn't slow.
# This makes the image large (several GB). Comment out to download on first run instead.
RUN python3 -c "import torch; from diffusers import LTXPipeline; LTXPipeline.from_pretrained('Lightricks/LTX-Video', torch_dtype=torch.bfloat16); print('LTX-Video weights cached')"

CMD ["python3", "-u", "/app/handler.py"]
