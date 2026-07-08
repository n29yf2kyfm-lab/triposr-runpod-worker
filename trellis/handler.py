import runpod
import torch
import requests
import base64
import os
import tempfile
from io import BytesIO
from PIL import Image
import sys

sys.path.insert(0, "/app/TRELLIS")
os.environ.setdefault("SPCONV_ALGO", "native")
os.environ.setdefault("ATTN_BACKEND", "xformers")

from trellis.pipelines import TrellisTextTo3DPipeline, TrellisImageTo3DPipeline
from trellis.utils import postprocessing_utils

TEXT_MODEL = "microsoft/TRELLIS-text-xlarge"
IMAGE_MODEL = "microsoft/TRELLIS-image-large"

_text_pipeline = None
_image_pipeline = None


def get_text_pipeline():
    global _text_pipeline
    if _text_pipeline is None:
        _text_pipeline = TrellisTextTo3DPipeline.from_pretrained(TEXT_MODEL)
        _text_pipeline.cuda()
    return _text_pipeline


def get_image_pipeline():
    global _image_pipeline
    if _image_pipeline is None:
        _image_pipeline = TrellisImageTo3DPipeline.from_pretrained(IMAGE_MODEL)
        _image_pipeline.cuda()
    return _image_pipeline


def fetch_image(image_url):
    """Fetch image from URL with browser-like headers"""
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; TRELLIS-Worker/1.0)",
        "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
    }
    response = requests.get(image_url, headers=headers, timeout=30)
    response.raise_for_status()
    return Image.open(BytesIO(response.content)).convert("RGB")


def handler(job):
    job_input = job.get("input", {})

    prompt = job_input.get("prompt", "")
    image_url = job_input.get("image_url", "")
    image_b64 = job_input.get("image_b64", "")
    seed = job_input.get("seed", 1)

    if not prompt and not image_url and not image_b64:
        return {"error": "Provide prompt (text-to-3D), or image_url / image_b64 (image-to-3D)"}

    try:
        if prompt:
            pipeline = get_text_pipeline()
            outputs = pipeline.run(prompt, seed=seed)
            mode = "text"
        else:
            if image_b64:
                img_data = base64.b64decode(image_b64)
                img = Image.open(BytesIO(img_data)).convert("RGB")
            else:
                img = fetch_image(image_url)
            pipeline = get_image_pipeline()
            outputs = pipeline.run(img, seed=seed)
            mode = "image"

        glb = postprocessing_utils.to_glb(
            outputs["gaussian"][0],
            outputs["mesh"][0],
            simplify=0.95,
            texture_size=1024,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            glb_path = os.path.join(tmpdir, "output.glb")
            glb.export(glb_path)
            with open(glb_path, "rb") as f:
                glb_b64 = base64.b64encode(f.read()).decode("utf-8")

        return {
            "status": "success",
            "glb_b64": glb_b64,
            "mode": mode,
            "message": "GLB generated successfully",
        }

    except Exception as e:
        import traceback
        return {
            "error": str(e),
            "traceback": traceback.format_exc(),
        }


runpod.serverless.start({"handler": handler})
