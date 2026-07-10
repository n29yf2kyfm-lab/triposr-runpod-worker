import runpod
import torch
import requests
import base64
import os
from io import BytesIO
from PIL import Image
import sys

# TRELLIS.2 repo is cloned to /app/TRELLIS.2 in the Dockerfile; its `trellis2`
# package is imported from there. The CUDA extension `o_voxel` is pip-installed.
sys.path.insert(0, "/app/TRELLIS.2")
os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
os.environ.setdefault("SPCONV_ALGO", "native")
# TRELLIS.2 uses flash-attn by default; xformers is the fallback for GPUs
# without flash-attention support.
os.environ.setdefault("ATTN_BACKEND", "flash-attn")

import o_voxel
from trellis2.pipelines import Trellis2ImageTo3DPipeline

IMAGE_MODEL = "microsoft/TRELLIS.2-4B"

OUTPUT_DIR = "/runpod-volume/outputs"

_image_pipeline = None


def get_image_pipeline():
    global _image_pipeline
    if _image_pipeline is None:
        _image_pipeline = Trellis2ImageTo3DPipeline.from_pretrained(IMAGE_MODEL)
        _image_pipeline.cuda()
    return _image_pipeline


def fetch_image(image_url):
    """Fetch image from URL with browser-like headers."""
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; TRELLIS-Worker/1.0)",
        "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
    }
    response = requests.get(image_url, headers=headers, timeout=30)
    response.raise_for_status()
    return Image.open(BytesIO(response.content)).convert("RGB")


def handler(job):
    job_input = job.get("input", {})
    job_id = job.get("id", "unknown")

    prompt = job_input.get("prompt", "")
    image_url = job_input.get("image_url", "")
    image_b64 = job_input.get("image_b64", "")
    seed = job_input.get("seed", 1)
    # Mesh knobs (safe defaults tuned for car assets served to a web viewer).
    decimation_target = int(job_input.get("decimation_target", 500000))
    texture_size = int(job_input.get("texture_size", 2048))

    if not image_url and not image_b64:
        # TRELLIS.2-4B is an image-to-3D model. The caller (on-pod handler)
        # already turns a text prompt into a reference image before calling
        # here, so a prompt with no image is a client error, not a text job.
        return {
            "error": "TRELLIS.2 is image-to-3D: provide image_url or image_b64"
                     + (" (prompt received but not supported here)" if prompt else "")
        }

    try:
        if image_b64:
            img = Image.open(BytesIO(base64.b64decode(image_b64))).convert("RGB")
        else:
            img = fetch_image(image_url)

        pipeline = get_image_pipeline()
        # TRELLIS.2 run() takes the PIL image (seed for reproducible rolls) and
        # returns a list of O-Voxel meshes; take the first.
        try:
            mesh = pipeline.run(img, seed=seed)[0]
        except TypeError:
            # Some builds don't accept a seed kwarg on run().
            torch.manual_seed(seed)
            mesh = pipeline.run(img)[0]

        os.makedirs(OUTPUT_DIR, exist_ok=True)
        persisted_path = os.path.join(OUTPUT_DIR, f"{job_id}.glb")

        # O-Voxel -> GLB with PBR (Base Color / Roughness / Metallic / Opacity).
        # remesh=True closes surface holes (the black-gap artifacts of v1) and
        # produces watertight-ish topology; PNG textures (extension_webp=False)
        # keep the GLB compatible with every downstream loader (Blender, web).
        glb = o_voxel.postprocess.to_glb(
            vertices=mesh.vertices,
            faces=mesh.faces,
            attr_volume=mesh.attrs,
            coords=mesh.coords,
            attr_layout=mesh.layout,
            voxel_size=mesh.voxel_size,
            aabb=[[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]],
            decimation_target=decimation_target,
            texture_size=texture_size,
            remesh=True,
            remesh_band=1,
            remesh_project=0,
            verbose=True,
        )
        glb.export(persisted_path, extension_webp=False)

        with open(persisted_path, "rb") as f:
            glb_b64 = base64.b64encode(f.read()).decode("utf-8")

        return {
            "status": "success",
            "glb_b64": glb_b64,
            "glb_path": persisted_path,
            "mode": "image",
            "model": IMAGE_MODEL,
            "message": "GLB generated successfully",
        }

    except Exception as e:
        import traceback
        return {
            "error": str(e),
            "traceback": traceback.format_exc(),
        }


runpod.serverless.start({"handler": handler})
