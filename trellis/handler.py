import runpod
import torch
import requests
import base64
import os
import numpy as np
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


def _load_image(data_or_bytes):
    """Load an image PRESERVING its alpha channel.

    TRELLIS.2's preprocess_image() skips background removal when it receives an
    RGBA image with a real (non-uniform) alpha mask, and only falls back to the
    gated, non-commercial briaai/RMBG-2.0 model for plain RGB inputs. Our
    callers already send a background-removed cutout, so we keep the alpha and
    signal "skip preprocessing" — the worker then never needs RMBG at all.
    """
    img = Image.open(BytesIO(data_or_bytes))
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
    else:
        img = img.convert("RGB")
    return img


def _has_cutout_alpha(img):
    """True if the image carries a usable transparency mask (a real cutout)."""
    if img.mode != "RGBA":
        return False
    alpha = np.asarray(img)[:, :, 3]
    return bool(alpha.min() < 250)  # some pixels transparent -> it's a cutout


def fetch_image(image_url):
    """Fetch image from URL with browser-like headers, keeping any alpha."""
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; TRELLIS-Worker/1.0)",
        "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
    }
    response = requests.get(image_url, headers=headers, timeout=30)
    response.raise_for_status()
    return _load_image(response.content)


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
            img = _load_image(base64.b64decode(image_b64))
        else:
            img = fetch_image(image_url)

        # If the caller sent a real cutout (RGBA with transparency), skip
        # TRELLIS.2's internal background removal so the worker never loads the
        # gated, non-commercial briaai/RMBG-2.0 model. Plain RGB still falls
        # back to its built-in preprocessing.
        skip_preprocess = _has_cutout_alpha(img)

        pipeline = get_image_pipeline()
        # TRELLIS.2 run() takes the PIL image (seed for reproducible rolls) and
        # returns a list of O-Voxel meshes; take the first.
        try:
            mesh = pipeline.run(
                img, seed=seed, preprocess_image=not skip_preprocess
            )[0]
        except TypeError:
            # Older/newer builds may not accept every kwarg on run().
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
