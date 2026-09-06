# Depth-conditioned photoreal worker. Build and push, then create a NEW
# RunPod serverless endpoint from the image — not the vehicle ones.
#
#   docker build -t <registry>/twin-visual-worker:1 twin/visual_worker
#   docker push <registry>/twin-visual-worker:1
#
# Then set RUNPOD_DEPTH_ENDPOINT_ID=<new endpoint id> in the app's env.
FROM runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Bake the weights so a cold start is seconds, not a 7 GB download.
ENV HF_HOME=/models
RUN python - <<'PY'
from diffusers import AutoencoderKL, ControlNetModel, StableDiffusionXLControlNetImg2ImgPipeline
import torch
cn = ControlNetModel.from_pretrained("diffusers/controlnet-depth-sdxl-1.0", torch_dtype=torch.float16)
vae = AutoencoderKL.from_pretrained("madebyollin/sdxl-vae-fp16-fix", torch_dtype=torch.float16)
StableDiffusionXLControlNetImg2ImgPipeline.from_pretrained(
    "stabilityai/stable-diffusion-xl-base-1.0", controlnet=cn, vae=vae, torch_dtype=torch.float16)
PY

COPY handler.py .
CMD ["python", "-u", "handler.py"]
