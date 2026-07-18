import runpod
import torch
import base64
import ipaddress
import os
import socket
import tempfile
from io import BytesIO
from urllib.parse import urlparse

import requests
from PIL import Image

# Text-to-video + image-to-video RunPod serverless worker.
#
# Default model: Lightricks/LTX-Video (fast, fits a 24-48GB GPU).
# To swap to CogVideoX (Apache-2.0, safest license for a commercial app),
# set env MODEL_KIND=cogvideox. See README for details.

MODEL_ID = os.environ.get("MODEL_ID", "Lightricks/LTX-Video")
MODEL_KIND = os.environ.get("MODEL_KIND", "ltx")  # "ltx" | "cogvideox"

# Generation guardrails -- cap cost / protect against OOM from bad callers.
MAX_FRAMES = int(os.environ.get("MAX_FRAMES", "257"))
MAX_STEPS = int(os.environ.get("MAX_STEPS", "60"))
MAX_DIM = int(os.environ.get("MAX_DIM", "1280"))
MAX_IMAGE_BYTES = int(os.environ.get("MAX_IMAGE_BYTES", str(16 * 1024 * 1024)))

_T2V = None   # text-to-video pipeline
_I2V = None   # image-to-video pipeline (LTX only)


def _dtype():
    return torch.bfloat16 if torch.cuda.is_available() else torch.float32


def _place(pipe):
    # enable_model_cpu_offload() handles device placement itself and saves VRAM on
    # smaller GPUs; it must NOT be combined with an explicit .to("cuda") (diffusers
    # rejects that). Fall back to a plain .to("cuda") only if offload is unavailable.
    if torch.cuda.is_available():
        try:
            pipe.enable_model_cpu_offload()
        except Exception:
            pipe.to("cuda")
    return pipe


def get_text_pipe():
    global _T2V
    if _T2V is None:
        if MODEL_KIND == "cogvideox":
            from diffusers import CogVideoXPipeline
            _T2V = _place(CogVideoXPipeline.from_pretrained(MODEL_ID, torch_dtype=_dtype()))
        else:
            from diffusers import LTXPipeline
            _T2V = _place(LTXPipeline.from_pretrained(MODEL_ID, torch_dtype=_dtype()))
    return _T2V


def get_image_pipe():
    """Image-to-video (LTX only). Built from the text pipe's components so the model
    weights are resident in VRAM only once instead of twice."""
    global _I2V
    if _I2V is None:
        from diffusers import LTXImageToVideoPipeline
        _I2V = LTXImageToVideoPipeline(**get_text_pipe().components)
    return _I2V


def _is_public_http_url(url):
    """SSRF guard: allow only http(s) URLs whose host resolves to public IPs."""
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        return False
    try:
        addrs = {info[4][0] for info in socket.getaddrinfo(p.hostname, None)}
    except OSError:
        return False
    if not addrs:
        return False
    for a in addrs:
        ip = ipaddress.ip_address(a)
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            return False
    return True


def fetch_image(url):
    if not _is_public_http_url(url):
        raise ValueError("image_url must be a public http(s) URL")
    headers = {"User-Agent": "Mozilla/5.0 (compatible; VideoWorker/1.0)"}
    with requests.get(url, headers=headers, timeout=30, stream=True) as r:
        r.raise_for_status()
        buf = BytesIO()
        total = 0
        for chunk in r.iter_content(65536):
            total += len(chunk)
            if total > MAX_IMAGE_BYTES:
                raise ValueError("image exceeds max allowed size")
            buf.write(chunk)
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _parse_params(inp):
    num_frames = _clamp(int(inp.get("num_frames", 97)), 9, MAX_FRAMES)
    width = _clamp(int(inp.get("width", 704)), 32, MAX_DIM)
    height = _clamp(int(inp.get("height", 480)), 32, MAX_DIM)
    steps = _clamp(int(inp.get("steps", 40)), 1, MAX_STEPS)
    fps = _clamp(int(inp.get("fps", 24)), 1, 60)
    seed = int(inp.get("seed", 0))
    if MODEL_KIND == "ltx":
        # LTX-Video requires width/height divisible by 32 and num_frames == 8k+1.
        width = max(32, round(width / 32) * 32)
        height = max(32, round(height / 32) * 32)
        num_frames = ((num_frames - 1) // 8) * 8 + 1
    return num_frames, width, height, steps, fps, seed


def handler(job):
    inp = job.get("input", {})

    prompt = (inp.get("prompt") or "").strip()
    if not prompt:
        return {"error": "Provide a text 'prompt'"}

    try:
        from diffusers.utils import export_to_video

        negative_prompt = inp.get(
            "negative_prompt", "worst quality, blurry, jittery, distorted, watermark"
        )
        num_frames, width, height, steps, fps, seed = _parse_params(inp)

        init_image = None
        image_b64 = inp.get("image_b64", "")
        image_url = inp.get("image_url", "")
        if image_b64:
            init_image = Image.open(BytesIO(base64.b64decode(image_b64))).convert("RGB")
        elif image_url:
            init_image = fetch_image(image_url)

        if init_image is not None and MODEL_KIND != "ltx":
            return {"error": "image-to-video is only supported with MODEL_KIND=ltx"}

        device = "cuda" if torch.cuda.is_available() else "cpu"
        generator = torch.Generator(device=device).manual_seed(seed)

        kwargs = dict(
            prompt=prompt,
            negative_prompt=negative_prompt,
            num_frames=num_frames,
            num_inference_steps=steps,
            generator=generator,
        )

        if init_image is not None:
            # image-to-video (LTX)
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

        frames = pipe(**kwargs).frames[0]

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
