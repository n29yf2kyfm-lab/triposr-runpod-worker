import runpod
import torch
import base64
import os
import tempfile
import requests
from io import BytesIO
from PIL import Image

# Text-to-video + image-to-video RunPod serverless worker.
#
# Default model: Lightricks/LTX-Video (fast, fits a 24-48GB GPU).
# To swap to CogVideoX (Apache-2.0, safest license for a commercial app),
# set env MODEL_KIND=cogvideox. See README for details.

MODEL_ID = os.environ.get("MODEL_ID", "Lightricks/LTX-Video")
MODEL_KIND = os.environ.get("MODEL_KIND", "ltx")  # "ltx" | "cogvideox"

_T2V = None   # text-to-video pipeline
_I2V = None   # image-to-video pipeline (LTX only)


def _dtype():
    return torch.bfloat16 if torch.cuda.is_available() else torch.float32


def get_text_pipe():
    global _T2V
    if _T2V is not None:
        return _T2V
    if MODEL_KIND == "cogvideox":
        from diffusers import CogVideoXPipeline
        pipe = CogVideoXPipeline.from_pretrained(MODEL_ID, torch_dtype=_dtype())
    else:
        from diffusers import LTXPipeline
        pipe = LTXPipeline.from_pretrained(MODEL_ID, torch_dtype=_dtype())
    if torch.cuda.is_available():
        pipe.to("cuda")
        # Save VRAM on smaller GPUs; harmless on big ones.
        try:
            pipe.enable_model_cpu_offload()
        except Exception:
            pass
    _T2V = pipe
    return _T2V


def get_image_pipe():
    """Image-to-video (LTX only). CogVideoX i2v uses a different checkpoint."""
    global _I2V
    if _I2V is not None:
        return _I2V
    from diffusers import LTXImageToVideoPipeline
    pipe = LTXImageToVideoPipeline.from_pretrained(MODEL_ID, torch_dtype=_dtype())
    if torch.cuda.is_available():
        pipe.to("cuda")
    _I2V = pipe
    return _I2V


def fetch_image(url):
    headers = {"User-Agent": "Mozilla/5.0 (compatible; VideoWorker/1.0)"}
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    return Image.open(BytesIO(r.content)).convert("RGB")


def handler(job):
    inp = job.get("input", {})

    prompt = (inp.get("prompt") or "").strip()
    if not prompt:
        return {"error": "Provide a text 'prompt'"}

    negative_prompt = inp.get(
        "negative_prompt", "worst quality, blurry, jittery, distorted, watermark"
    )
    num_frames = int(inp.get("num_frames", 97))   # ~4s @ 24fps for LTX
    width = int(inp.get("width", 704))
    height = int(inp.get("height", 480))
    steps = int(inp.get("steps", 40))
    fps = int(inp.get("fps", 24))
    seed = int(inp.get("seed", 0))

    image_url = inp.get("image_url", "")
    image_b64 = inp.get("image_b64", "")

    try:
        from diffusers.utils import export_to_video

        init_image = None
        if image_b64:
            init_image = Image.open(BytesIO(base64.b64decode(image_b64))).convert("RGB")
        elif image_url:
            init_image = fetch_image(image_url)

        device = "cuda" if torch.cuda.is_available() else "cpu"
        generator = torch.Generator(device=device).manual_seed(seed)

        kwargs = dict(
            prompt=prompt,
            negative_prompt=negative_prompt,
            num_frames=num_frames,
            num_inference_steps=steps,
            generator=generator,
        )

        if init_image is not None and MODEL_KIND == "ltx":
            # image-to-video
            pipe = get_image_pipe()
            kwargs["image"] = init_image.resize((width, height))
            kwargs["width"] = width
            kwargs["height"] = height
        else:
            # text-to-video
            pipe = get_text_pipe()
            if MODEL_KIND == "ltx":
                kwargs["width"] = width
                kwargs["height"] = height
            # CogVideoX uses its own fixed resolution; don't pass width/height.

        result = pipe(**kwargs)
        frames = result.frames[0]

        with tempfile.TemporaryDirectory() as tmp:
            out_path = os.path.join(tmp, "output.mp4")
            export_to_video(frames, out_path, fps=fps)
            with open(out_path, "rb") as f:
                video_b64 = base64.b64encode(f.read()).decode("utf-8")

        return {
            "status": "success",
            "video_b64": video_b64,
            "mime_type": "video/mp4",
            "message": "Video generated successfully",
        }

    except Exception as e:
        import traceback
        return {"error": str(e), "traceback": traceback.format_exc()}


runpod.serverless.start({"handler": handler})
