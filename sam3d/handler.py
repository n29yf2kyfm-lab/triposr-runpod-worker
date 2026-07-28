"""RunPod serverless worker for Meta's SAM 3D Objects (image -> 3D).

SAM 3D Objects reconstructs a single object from ONE image plus a segmentation
mask, and emits a 3D Gaussian splat (.ply) — NOT a triangle mesh/GLB like the
TripoSR and TRELLIS workers in this repo. Downstream viewers must render
gaussian splats (e.g. mkkellogg/GaussianSplats3D, or a Babylon/three splat
loader), not model-viewer/plain GLB.

Upstream: https://github.com/facebookresearch/sam-3d-objects
Weights:  https://huggingface.co/facebook/sam-3d-objects  (gated: SAM License)
Docs API: notebook/inference.py -> Inference(config).__call__(image, mask, seed)

Input (job["input"]):
  image_url | image_b64   (one required)  RGB source image
  mask_b64                 (optional)      1-channel PNG mask isolating the ONE
                                           object. >0 = foreground. If omitted,
                                           a full-frame mask is used (whole image
                                           treated as the subject) — fine for a
                                           pre-cropped part photo, but a real
                                           SAM 3 / foreground mask gives far
                                           better reconstructions. See MASK NOTE.
  seed                     (optional)      int, default 42

Output:
  { status, ply_b64, format:"gaussian-splat-ply", bytes, message }
"""
import os
import sys
import base64
import tempfile
import traceback
from io import BytesIO

import numpy as np
import requests
from PIL import Image
import runpod

os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

# The official repo keeps the inference helpers under notebook/. The Dockerfile
# clones it to SAM3D_ROOT and moves the checkpoints into checkpoints/<tag>/.
SAM3D_ROOT = os.environ.get("SAM3D_ROOT", "/app/sam-3d-objects")
TAG = os.environ.get("SAM3D_TAG", "hf")
CONFIG_PATH = os.environ.get(
    "SAM3D_CONFIG", os.path.join(SAM3D_ROOT, f"checkpoints/{TAG}/pipeline.yaml")
)
sys.path.insert(0, os.path.join(SAM3D_ROOT, "notebook"))

# Cap on the base64 payload we return inline. RunPod drops job outputs above its
# response-size limit (the trellis2 worker hit exactly this and switched to a
# Supabase upload). Gaussian-splat PLYs are often several MB, so treat inline
# delivery as best-effort and warn loudly when it is likely to be dropped.
MAX_INLINE_BYTES = int(os.environ.get("SAM3D_MAX_INLINE_BYTES", str(9 * 1024 * 1024)))

_INFERENCE = None


def get_inference():
    """Lazy-load the pipeline once per cold start (matches the other workers)."""
    global _INFERENCE
    if _INFERENCE is None:
        from inference import Inference  # noqa: E402 (repo module on sys.path)
        _INFERENCE = Inference(CONFIG_PATH, compile=False)
    return _INFERENCE


def _fetch_image(image_url):
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; SAM3D-Worker/1.0)",
        "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
    }
    resp = requests.get(image_url, headers=headers, timeout=30)
    resp.raise_for_status()
    return np.array(Image.open(BytesIO(resp.content)).convert("RGB")).astype(np.uint8)


def _decode_image_b64(image_b64):
    data = base64.b64decode(image_b64)
    return np.array(Image.open(BytesIO(data)).convert("RGB")).astype(np.uint8)


def _decode_mask_b64(mask_b64, target_hw):
    """Decode a 1-channel PNG mask to a bool array matching the image size.

    load_single_mask() in the upstream notebook returns `mask > 0` (bool HxW);
    we produce the same dtype so the pipeline sees an identical input.
    """
    h, w = target_hw
    m = Image.open(BytesIO(base64.b64decode(mask_b64))).convert("L")
    if m.size != (w, h):  # PIL size is (width, height)
        m = m.resize((w, h), Image.NEAREST)
    return np.array(m) > 0


def handler(job):
    job_input = job.get("input", {})
    image_url = job_input.get("image_url", "")
    image_b64 = job_input.get("image_b64", "")
    mask_b64 = job_input.get("mask_b64", "")
    seed = int(job_input.get("seed", 42))

    if not image_url and not image_b64:
        return {"error": "Provide image_url or image_b64"}

    try:
        image = _decode_image_b64(image_b64) if image_b64 else _fetch_image(image_url)
        h, w = image.shape[:2]

        if mask_b64:
            mask = _decode_mask_b64(mask_b64, (h, w))
        else:
            # MASK NOTE: no mask supplied -> reconstruct the whole frame. This is
            # the correct-but-blunt default. For production part photos, generate
            # a mask first (Meta SAM 3, or a background-remover like the BiRefNet
            # the trellis2 worker already uses) and pass it as mask_b64. That is
            # the single biggest quality lever for SAM 3D Objects.
            mask = np.ones((h, w), dtype=bool)

        inference = get_inference()
        output = inference(image, mask, seed=seed)

        # Documented output: output["gs"] is the gaussian splat with .save_ply().
        gs = output.get("gs") if isinstance(output, dict) else None
        if gs is None:
            return {
                "error": "Pipeline returned no 'gs' (gaussian splat) key",
                "output_keys": list(output.keys()) if isinstance(output, dict) else str(type(output)),
            }

        with tempfile.TemporaryDirectory() as tmpdir:
            ply_path = os.path.join(tmpdir, "output.ply")
            gs.save_ply(ply_path)
            with open(ply_path, "rb") as f:
                data = f.read()

        result = {
            "status": "success",
            "format": "gaussian-splat-ply",
            "bytes": len(data),
            "message": "Gaussian splat PLY generated successfully",
        }
        if len(data) > MAX_INLINE_BYTES:
            # Don't silently truncate: tell the caller the inline payload is
            # likely to be dropped by RunPod and point at the durable path.
            result["warning"] = (
                f"PLY is {len(data)} bytes (> {MAX_INLINE_BYTES}); RunPod may drop "
                "an inline response this large. Configure an object-store upload "
                "(see the trellis2 worker's Supabase delivery) for production."
            )
        result["ply_b64"] = base64.b64encode(data).decode("utf-8")
        return result

    except Exception as e:
        return {"error": str(e), "traceback": traceback.format_exc()}


runpod.serverless.start({"handler": handler})
