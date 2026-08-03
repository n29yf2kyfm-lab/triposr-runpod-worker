import runpod
import torch
import base64
import os
import tempfile
import requests
from io import BytesIO
from PIL import Image

# LTX-Video image-to-video, run locally on the RunPod GPU (no external API).
#   https://huggingface.co/Lightricks/LTX-Video
MODEL_ID = os.environ.get("LTX_MODEL", "Lightricks/LTX-Video")

# Persist the HF cache on the network volume if one is mounted, so weights are
# downloaded once and reused across cold starts instead of per-worker.
if os.path.isdir("/runpod-volume"):
    os.environ.setdefault("HF_HOME", "/runpod-volume/hf")

PIPE = None


def get_pipe():
    global PIPE
    if PIPE is None:
        from diffusers import LTXImageToVideoPipeline
        PIPE = LTXImageToVideoPipeline.from_pretrained(MODEL_ID, torch_dtype=torch.bfloat16)
        # Keep memory in check so it fits 16-24GB cards (A4000..A5000/3090/L4).
        if os.environ.get("LTX_CPU_OFFLOAD", "0") == "1":
            PIPE.enable_model_cpu_offload()
        else:
            PIPE.to("cuda")
        PIPE.vae.enable_tiling()
    return PIPE


def _round_to(value, multiple):
    return max(multiple, (int(value) // multiple) * multiple)


def _load_image(job_input):
    if job_input.get("image_b64"):
        raw = job_input["image_b64"]
        if raw.strip().startswith("data:") and "," in raw:
            raw = raw.split(",", 1)[1]
        return Image.open(BytesIO(base64.b64decode(raw))).convert("RGB")
    if job_input.get("image_url"):
        headers = {"User-Agent": "Mozilla/5.0 (compatible; LTX-Worker/1.0)"}
        resp = requests.get(job_input["image_url"], headers=headers, timeout=30)
        resp.raise_for_status()
        return Image.open(BytesIO(resp.content)).convert("RGB")
    return None


def handler(job):
    job_input = job.get("input", {})

    prompt = job_input.get("prompt", "")
    if not prompt:
        return {"error": "Provide a 'prompt' describing the desired motion/scene."}

    try:
        image = _load_image(job_input)  # optional: None -> text-to-video-ish first frame

        # LTX constraints: width/height divisible by 32; num_frames = 8*k + 1.
        width = _round_to(job_input.get("width", 704), 32)
        height = _round_to(job_input.get("height", 480), 32)
        num_frames = job_input.get("num_frames", 121)
        num_frames = _round_to(num_frames - 1, 8) + 1
        steps = int(job_input.get("num_inference_steps", 40))
        fps = int(job_input.get("fps", 24))
        negative_prompt = job_input.get(
            "negative_prompt",
            "worst quality, inconsistent motion, blurry, jittery, distorted",
        )

        generator = None
        if job_input.get("seed") is not None:
            generator = torch.Generator(device="cuda").manual_seed(int(job_input["seed"]))

        pipe = get_pipe()
        call_kwargs = dict(
            prompt=prompt,
            negative_prompt=negative_prompt,
            width=width,
            height=height,
            num_frames=num_frames,
            num_inference_steps=steps,
            generator=generator,
        )
        if image is not None:
            call_kwargs["image"] = image

        frames = pipe(**call_kwargs).frames[0]

        from diffusers.utils import export_to_video
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = os.path.join(tmpdir, "output.mp4")
            export_to_video(frames, out_path, fps=fps)
            with open(out_path, "rb") as f:
                video_bytes = f.read()

        result = {
            "status": "success",
            "video_b64": base64.b64encode(video_bytes).decode("utf-8"),
            "model": MODEL_ID,
            "width": width,
            "height": height,
            "num_frames": num_frames,
            "fps": fps,
        }
        if job_input.get("seed") is not None:
            result["seed"] = int(job_input["seed"])
        return result

    except Exception as e:
        import traceback
        return {"error": str(e), "traceback": traceback.format_exc()}


runpod.serverless.start({"handler": handler})
