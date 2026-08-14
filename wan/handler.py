"""Wan 2.2 image-to-video RunPod serverless worker.

Two jobs, one model:

  1. Cinematic car clips on demand — car photo + preset ("orbit",
     "scanner_sweep", ...) -> ~5s 720p/480p MP4. Used directly by the
     ExpertCarCheck listing-video feature.
  2. Batch b-roll library builds — mode="broll" with a list of shots ->
     one MP4 per shot uploaded under a stable library key. This worker is
     NEVER in the tutorial request path; tutorials/ only assembles clips
     that already exist (that split is what keeps per-video cost at pennies).

Model: Wan-AI/Wan2.2-I2V-A14B-Diffusers (MoE, two 14B experts), bf16.
With the lightx2v distill LoRA (DISTILL=1, default) sampling drops from ~40
steps to 4-8, cutting a 720p 5s clip from ~9 GPU-minutes to under one on an
L40S/H100-class card. If the LoRA fails to load the worker logs it and falls
back to full-step sampling rather than dying.

Delivery mirrors trellis2/: upload to Supabase storage (RunPod drops
oversized job outputs), inline base64 only when small enough.
"""
import base64
import os
import sys
import tempfile
import time
import uuid
from io import BytesIO

import requests
import runpod
import torch
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shots import BROLL_LIBRARY, resolve_prompt  # noqa: E402

MODEL_ID = os.environ.get("WAN_MODEL", "Wan-AI/Wan2.2-I2V-A14B-Diffusers")

# lightx2v 4-step distillation LoRAs (one per MoE expert). Filenames are env
# overrides because the repo layout may change; on any load failure we fall
# back to full-step sampling.
DISTILL = os.environ.get("DISTILL", "1") == "1"
DISTILL_REPO = os.environ.get("DISTILL_LORA_REPO", "lightx2v/Wan2.2-Distill-Loras")
DISTILL_HIGH = os.environ.get(
    "DISTILL_LORA_HIGH",
    "wan2.2_i2v_A14b_high_noise_lora_rank64_lightx2v_4step.safetensors",
)
DISTILL_LOW = os.environ.get(
    "DISTILL_LORA_LOW",
    "wan2.2_i2v_A14b_low_noise_lora_rank64_lightx2v_4step.safetensors",
)

# Drop-in point for the automotive LoRA once trained (musubi-tuner / AI
# Toolkit output). Point at an HF repo or a /runpod-volume path; no rebuild.
STYLE_LORA = os.environ.get("STYLE_LORA", "")
STYLE_LORA_WEIGHT = os.environ.get("STYLE_LORA_WEIGHT", "")  # optional filename

# A14B natively generates 81 frames @ 16 fps (~5s).
RESOLUTIONS = {"480p": (832, 480), "720p": (1280, 720)}
DEFAULT_RESOLUTION = os.environ.get("RESOLUTION", "720p")
DEFAULT_FRAMES = int(os.environ.get("NUM_FRAMES", "81"))
FPS = int(os.environ.get("FPS", "16"))

# CPU offload trades speed for VRAM headroom: required on 24GB cards, wasted
# time on 80GB. Default on — correctness over speed for unknown hardware.
CPU_OFFLOAD = os.environ.get("CPU_OFFLOAD", "1") == "1"

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
SUPABASE_BUCKET = os.environ.get("SUPABASE_BUCKET", "car-videos")
MAX_INLINE_BYTES = 4_000_000

_pipe = None
_distill_active = False


def _log(msg):
    print(msg, flush=True)


def get_pipeline():
    global _pipe, _distill_active
    if _pipe is not None:
        return _pipe

    from diffusers import WanImageToVideoPipeline

    _log(f"loading {MODEL_ID} ...")
    t0 = time.time()
    pipe = WanImageToVideoPipeline.from_pretrained(MODEL_ID, torch_dtype=torch.bfloat16)

    if DISTILL:
        # The two MoE experts (high/low noise) each need their own LoRA.
        # load_into_transformer_2 targets the low-noise expert (diffusers'
        # Wan 2.2 support); any failure -> full-step fallback, never a crash.
        try:
            pipe.load_lora_weights(
                DISTILL_REPO, weight_name=DISTILL_HIGH, adapter_name="distill_high"
            )
            pipe.load_lora_weights(
                DISTILL_REPO, weight_name=DISTILL_LOW, adapter_name="distill_low",
                load_into_transformer_2=True,
            )
            _distill_active = True
            _log("distill LoRA loaded: 4-step sampling enabled")
        except Exception as e:
            _distill_active = False
            _log(f"distill LoRA load FAILED ({type(e).__name__}: {e}); "
                 "falling back to full-step sampling")

    if STYLE_LORA:
        try:
            kwargs = {"adapter_name": "style"}
            if STYLE_LORA_WEIGHT:
                kwargs["weight_name"] = STYLE_LORA_WEIGHT
            pipe.load_lora_weights(STYLE_LORA, **kwargs)
            _log(f"style LoRA loaded from {STYLE_LORA}")
        except Exception as e:
            _log(f"style LoRA load FAILED ({type(e).__name__}: {e}); continuing without")

    if CPU_OFFLOAD:
        pipe.enable_model_cpu_offload()
    else:
        pipe.to("cuda")
    try:
        pipe.vae.enable_tiling()
    except Exception:
        pass

    _log(f"pipeline ready in {time.time() - t0:.0f}s")
    _pipe = pipe
    return _pipe


def fetch_image(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; WanWorker/1.0)",
        "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
    }
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    return Image.open(BytesIO(r.content)).convert("RGB")


def load_input_image(job_input):
    if job_input.get("image_b64"):
        return Image.open(BytesIO(base64.b64decode(job_input["image_b64"]))).convert("RGB")
    if job_input.get("image_url"):
        return fetch_image(job_input["image_url"])
    raise ValueError("Provide image_url or image_b64")


def fit_to_resolution(img, size):
    """Center-crop to the target aspect ratio, then resize. No letterboxing —
    bars would end up baked into every generated frame."""
    tw, th = size
    w, h = img.size
    target_ratio, ratio = tw / th, w / h
    if ratio > target_ratio:
        new_w = int(h * target_ratio)
        left = (w - new_w) // 2
        img = img.crop((left, 0, left + new_w, h))
    elif ratio < target_ratio:
        new_h = int(w / target_ratio)
        top = (h - new_h) // 2
        img = img.crop((0, top, w, top + new_h))
    return img.resize((tw, th), Image.Resampling.LANCZOS)


def upload_to_supabase(path, object_name, content_type="video/mp4"):
    if not (SUPABASE_URL and SUPABASE_KEY and SUPABASE_BUCKET):
        return None
    try:
        with open(path, "rb") as f:
            data = f.read()
        r = requests.post(
            f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{object_name}",
            data=data,
            headers={
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "apikey": SUPABASE_KEY,
                "Content-Type": content_type,
                "x-upsert": "true",
            },
            timeout=300,
        )
        if r.status_code in (200, 201):
            return f"{SUPABASE_URL}/storage/v1/object/public/{SUPABASE_BUCKET}/{object_name}"
        _log(f"supabase upload failed: {r.status_code} {r.text[:200]}")
    except Exception as e:
        _log(f"supabase upload error: {e}")
    return None


def generate_clip(image, prompt, negative, resolution, num_frames, seed, out_path):
    from diffusers.utils import export_to_video

    pipe = get_pipeline()
    size = RESOLUTIONS[resolution]
    image = fit_to_resolution(image, size)

    kwargs = dict(
        image=image,
        prompt=prompt,
        negative_prompt=negative,
        width=size[0],
        height=size[1],
        num_frames=num_frames,
    )
    if _distill_active:
        # Distilled sampling: few steps, CFG off (the distillation bakes
        # guidance in; real CFG would double compute and wreck the output).
        kwargs.update(num_inference_steps=8, guidance_scale=1.0, guidance_scale_2=1.0)
    else:
        kwargs.update(num_inference_steps=40)
    if seed is not None:
        kwargs["generator"] = torch.Generator(device="cpu").manual_seed(int(seed))

    t0 = time.time()
    frames = pipe(**kwargs).frames[0]
    gen_s = time.time() - t0
    export_to_video(frames, out_path, fps=FPS)
    return gen_s


def handle_single(job_input):
    prompt, negative = resolve_prompt(job_input)
    image = load_input_image(job_input)
    resolution = job_input.get("resolution", DEFAULT_RESOLUTION)
    if resolution not in RESOLUTIONS:
        return {"error": f"resolution must be one of {sorted(RESOLUTIONS)}"}
    num_frames = int(job_input.get("num_frames", DEFAULT_FRAMES))
    seed = job_input.get("seed")

    with tempfile.TemporaryDirectory() as tmp:
        out_path = os.path.join(tmp, "clip.mp4")
        gen_s = generate_clip(image, prompt, negative, resolution, num_frames, seed, out_path)

        object_name = job_input.get("object_name") or f"clips/{uuid.uuid4().hex}.mp4"
        url = upload_to_supabase(out_path, object_name)
        result = {
            "status": "success",
            "video_url": url,
            "object_name": object_name if url else None,
            "seconds": round(num_frames / FPS, 2),
            "resolution": resolution,
            "distill": _distill_active,
            "generation_s": round(gen_s, 1),
        }
        size = os.path.getsize(out_path)
        if url is None or size <= MAX_INLINE_BYTES:
            with open(out_path, "rb") as f:
                result["video_b64"] = base64.b64encode(f.read()).decode()
        if url is None and size > MAX_INLINE_BYTES:
            result["warning"] = (
                "No Supabase config and video exceeds RunPod's response cap; "
                "the inline payload may be dropped by the platform."
            )
        return result


def handle_broll(job_input):
    """Batch library build. shots: [{id, prompt?, image_url?/image_b64?}].
    A shot with no prompt uses BROLL_LIBRARY[id]; with no image, the batch's
    source_image_* is used (one generic workshop/car frame can seed many
    shots). Results upload to broll/<id>.mp4 — the tutorials/ assembler's
    lookup key."""
    shots = job_input.get("shots")
    if not shots:
        # No explicit list -> build the entire standard library.
        shots = [{"id": k} for k in BROLL_LIBRARY]

    default_image = None
    if job_input.get("source_image_url") or job_input.get("source_image_b64"):
        default_image = load_input_image({
            "image_url": job_input.get("source_image_url", ""),
            "image_b64": job_input.get("source_image_b64", ""),
        })

    resolution = job_input.get("resolution", DEFAULT_RESOLUTION)
    if resolution not in RESOLUTIONS:
        return {"error": f"resolution must be one of {sorted(RESOLUTIONS)}"}
    num_frames = int(job_input.get("num_frames", DEFAULT_FRAMES))
    results, failures = [], 0

    for shot in shots:
        shot_id = shot.get("id") or uuid.uuid4().hex
        try:
            prompt = shot.get("prompt") or BROLL_LIBRARY.get(shot_id)
            if not prompt:
                raise ValueError(f"shot '{shot_id}' has no prompt and is not in BROLL_LIBRARY")
            if shot.get("image_url") or shot.get("image_b64"):
                image = load_input_image(shot)
            elif default_image is not None:
                image = default_image
            else:
                raise ValueError(f"shot '{shot_id}' has no image and no batch source_image")

            _, negative = resolve_prompt(
                {"prompt": prompt, "negative_prompt": shot.get("negative_prompt", "")}
            )
            with tempfile.TemporaryDirectory() as tmp:
                out_path = os.path.join(tmp, "clip.mp4")
                gen_s = generate_clip(
                    image, prompt, negative,
                    resolution, num_frames, shot.get("seed"), out_path,
                )
                object_name = f"broll/{shot_id}.mp4"
                url = upload_to_supabase(out_path, object_name)
                results.append({
                    "id": shot_id, "video_url": url,
                    "object_name": object_name,
                    "generation_s": round(gen_s, 1),
                })
                _log(f"broll {shot_id}: done in {gen_s:.0f}s -> {url}")
        except Exception as e:
            failures += 1
            results.append({"id": shot_id, "error": f"{type(e).__name__}: {e}"})
            _log(f"broll {shot_id}: FAILED {e}")

    return {
        "status": "success" if failures == 0 else "partial",
        "generated": len(results) - failures,
        "failed": failures,
        "shots": results,
    }


def handler(job):
    job_input = job.get("input", {})
    try:
        if job_input.get("mode") == "broll":
            return handle_broll(job_input)
        return handle_single(job_input)
    except Exception as e:
        import traceback
        return {"error": str(e), "traceback": traceback.format_exc()}


if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
