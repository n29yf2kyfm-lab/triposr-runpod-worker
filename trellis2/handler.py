import runpod
import torch
import requests
import base64
import os
from io import BytesIO
from PIL import Image
import sys

# Match the environment example.py sets before importing cv2/torch.
os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
os.environ.setdefault("ATTN_BACKEND", "flash-attn")

sys.path.insert(0, "/app/TRELLIS.2")

from trellis2.pipelines import Trellis2ImageTo3DPipeline
import o_voxel

# TRELLIS.2 is image-to-3D only — there is no text-to-3D pipeline in v2 (unlike
# the v1 worker). A `prompt` in the request is therefore rejected explicitly so
# callers migrating from the v1 endpoint get a clear error instead of silence.
IMAGE_MODEL = "microsoft/TRELLIS.2-4B"

# GLB baking knobs — these mirror example.py's defaults. Higher texture_size /
# decimation_target trade generation time and file size for fidelity.
DECIMATION_TARGET = 1_000_000  # target face count after remeshing
TEXTURE_SIZE = 4096            # baked PBR texture resolution
REMESH = True

OUTPUT_DIR = "/runpod-volume/outputs"

_pipeline = None


def get_pipeline():
    global _pipeline
    if _pipeline is None:
        _pipeline = Trellis2ImageTo3DPipeline.from_pretrained(IMAGE_MODEL)
        _pipeline.cuda()
    return _pipeline


def fetch_image(image_url):
    """Fetch an image from a URL with browser-like headers."""
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; TRELLIS2-Worker/1.0)",
        "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
    }
    response = requests.get(image_url, headers=headers, timeout=30)
    response.raise_for_status()
    return Image.open(BytesIO(response.content)).convert("RGB")


def run_pipeline(pipeline, img, seed):
    """Run generation, passing seed if the installed pipeline accepts it.

    example.py calls `pipeline.run(image)` with no seed; the app exposes a seed
    control, so the kwarg is expected to exist. Guard with a TypeError fallback
    so a signature mismatch degrades to a non-seeded run instead of a hard crash.
    """
    try:
        return pipeline.run(img, seed=seed)[0]
    except TypeError:
        return pipeline.run(img)[0]


def handler(job):
    job_input = job.get("input", {})
    job_id = job.get("id", "unknown")

    prompt = job_input.get("prompt", "")
    image_url = job_input.get("image_url", "")
    image_b64 = job_input.get("image_b64", "")
    seed = job_input.get("seed", 1)

    if prompt and not (image_url or image_b64):
        return {
            "error": "TRELLIS.2 is image-to-3D only; text prompts are not supported. "
                     "Provide image_url or image_b64.",
        }
    if not image_url and not image_b64:
        return {"error": "Provide image_url or image_b64 (image-to-3D)."}

    try:
        if image_b64:
            img_data = base64.b64decode(image_b64)
            img = Image.open(BytesIO(img_data)).convert("RGB")
        else:
            img = fetch_image(image_url)

        pipeline = get_pipeline()

        with torch.no_grad():
            mesh = run_pipeline(pipeline, img, seed)

        # O-Voxel -> textured PBR GLB. Field names come from example.py's
        # to_glb call against the mesh object returned by pipeline.run().
        glb = o_voxel.postprocess.to_glb(
            vertices=mesh.vertices,
            faces=mesh.faces,
            attr_volume=mesh.attrs,
            coords=mesh.coords,
            attr_layout=mesh.layout,
            voxel_size=mesh.voxel_size,
            decimation_target=DECIMATION_TARGET,
            texture_size=TEXTURE_SIZE,
            remesh=REMESH,
        )

        os.makedirs(OUTPUT_DIR, exist_ok=True)
        persisted_path = os.path.join(OUTPUT_DIR, f"{job_id}.glb")
        # extension_webp=True stores textures as WebP inside the GLB — much
        # smaller PBR maps, as in example.py.
        glb.export(persisted_path, extension_webp=True)

        with open(persisted_path, "rb") as f:
            glb_b64 = base64.b64encode(f.read()).decode("utf-8")

        return {
            "status": "success",
            "glb_b64": glb_b64,
            "glb_path": persisted_path,
            "mode": "image",
            "message": "GLB generated successfully",
        }

    except Exception as e:
        import traceback
        return {
            "error": str(e),
            "traceback": traceback.format_exc(),
        }


runpod.serverless.start({"handler": handler})
