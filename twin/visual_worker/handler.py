"""RunPod serverless worker: depth-conditioned photoreal render.

THIS IS THE GEOMETRY-LOCKED PATH. The app renders a depth map straight
from the measured model (white near, black far) and sends it here with
the massing colour render and a prompt. Stable Diffusion XL with a depth
ControlNet then has no freedom about WHERE the walls, eaves and ridge
are — only about what they are made of. A free-form image model can be
asked to keep the geometry; this one is made to.

Input  (job["input"]):
  prompt            str   what to dress the massing in
  depth_png_b64     str   depth pass from the app's renderer
  image_png_b64     str   optional colour massing, used as img2img init
  control_strength  float 0..1, default 0.9 — how hard the depth binds
  steps             int   default 28
  seed              int   optional, for repeatability
Output:
  image_png_b64     str   the render, same size as the depth map
  model / controlnet str  what produced it, for the provenance record

Deploy on its own endpoint. This worker MUST NOT be pointed at the
vehicle project's endpoints; the app refuses those ids by name.
"""
from __future__ import annotations

import base64
import io
import os

MODEL = os.environ.get("SDXL_MODEL", "stabilityai/stable-diffusion-xl-base-1.0")
CONTROLNET = os.environ.get("CONTROLNET_MODEL", "diffusers/controlnet-depth-sdxl-1.0")
NEGATIVE = ("text, watermark, signature, people, cars, cartoon, painting, "
            "blurry, deformed, extra buildings, changed roof")

_pipe = None


def _load():
    """Lazy, once per warm worker. Import inside so the handler module
    imports cleanly on a CPU box for tests."""
    global _pipe
    if _pipe is not None:
        return _pipe
    import torch
    from diffusers import (AutoencoderKL, ControlNetModel,
                           StableDiffusionXLControlNetImg2ImgPipeline)
    dtype = torch.float16
    cn = ControlNetModel.from_pretrained(CONTROLNET, torch_dtype=dtype)
    vae = AutoencoderKL.from_pretrained("madebyollin/sdxl-vae-fp16-fix",
                                        torch_dtype=dtype)
    _pipe = StableDiffusionXLControlNetImg2ImgPipeline.from_pretrained(
        MODEL, controlnet=cn, vae=vae, torch_dtype=dtype).to("cuda")
    _pipe.enable_model_cpu_offload() if os.environ.get("LOW_VRAM") else None
    return _pipe


def _decode(b64: str):
    from PIL import Image
    return Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")


def _fit(im, multiple=64, max_side=1024):
    """SDXL wants sides that are multiples of 64; keep the aspect."""
    w, h = im.size
    s = min(1.0, max_side / max(w, h))
    w = max(multiple, int(round(w * s / multiple)) * multiple)
    h = max(multiple, int(round(h * s / multiple)) * multiple)
    return im.resize((w, h))


def render(inp: dict, pipe=None) -> dict:
    """Pure function of the input, so it can be exercised with a fake
    pipeline on a machine with no GPU."""
    if not inp.get("depth_png_b64"):
        raise ValueError("depth_png_b64 is required — without the depth "
                         "map this is a free-form render, which is the "
                         "thing this worker exists not to be")
    depth = _fit(_decode(inp["depth_png_b64"]))
    init = (_fit(_decode(inp["image_png_b64"])).resize(depth.size)
            if inp.get("image_png_b64") else depth)
    strength = float(inp.get("control_strength", 0.9))
    steps = int(inp.get("steps", 28))
    seed = inp.get("seed")
    pipe = pipe or _load()
    generator = None
    if seed is not None:
        import torch
        generator = torch.Generator("cuda").manual_seed(int(seed))
    out = pipe(
        prompt=inp.get("prompt", "a house"),
        negative_prompt=inp.get("negative_prompt", NEGATIVE),
        image=init,
        control_image=depth,
        controlnet_conditioning_scale=strength,
        # img2img strength: high, so the flat massing colours do not
        # survive, while the depth map still fixes the geometry.
        strength=float(inp.get("denoise", 0.85)),
        num_inference_steps=steps,
        generator=generator,
    ).images[0]
    buf = io.BytesIO()
    out.save(buf, format="PNG")
    return {"image_png_b64": base64.b64encode(buf.getvalue()).decode(),
            "model": MODEL, "controlnet": CONTROLNET,
            "size": list(out.size), "control_strength": strength}


def handler(job):
    try:
        return render(job.get("input") or {})
    except Exception as e:                    # RunPod wants a dict back
        return {"error": f"{type(e).__name__}: {e}"}


if __name__ == "__main__":
    import runpod
    runpod.serverless.start({"handler": handler})
