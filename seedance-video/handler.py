import runpod
import replicate
import requests
import base64
import os
import tempfile

# Replicate model that serves ByteDance Seedance 2.0. One unified model handles
# text-to-video, image-to-video, and reference-to-video — `image`/references are
# all optional; only `prompt` is required.
#   https://replicate.com/bytedance/seedance-2.0
DEFAULT_MODEL = os.environ.get("SEEDANCE_MODEL", "bytedance/seedance-2.0")

# Verified against the live Replicate input schema (see seedance-video/README.md).
RESOLUTIONS = {"480p", "720p", "1080p", "4k"}
ASPECT_RATIOS = {"16:9", "4:3", "1:1", "3:4", "9:16", "21:9", "9:21", "adaptive"}


def _b64_to_tempfile(image_b64, tmpdir, name):
    """Decode a base64 image into a uniquely-named temp file, return an open handle.

    The Replicate client uploads file handles to its file API and substitutes
    the resulting URL, so we avoid stuffing a huge data URI into the request.
    """
    if "," in image_b64 and image_b64.strip().startswith("data:"):
        image_b64 = image_b64.split(",", 1)[1]
    path = os.path.join(tmpdir, name)
    with open(path, "wb") as f:
        f.write(base64.b64decode(image_b64))
    return open(path, "rb")


def _output_to_url(output):
    """Normalize replicate.run() output to a single video URL string."""
    if output is None:
        return None
    if isinstance(output, list):
        output = output[0] if output else None
    if output is None:
        return None
    # FileOutput objects expose .url; plain strings are already the URL.
    return getattr(output, "url", None) or str(output)


def handler(job):
    job_input = job.get("input", {})

    if not os.environ.get("REPLICATE_API_TOKEN"):
        return {"error": "REPLICATE_API_TOKEN is not set. Add it as a RunPod secret / env var."}

    prompt = job_input.get("prompt", "")
    if not prompt:
        return {"error": "Provide a 'prompt' describing the desired motion/scene."}

    model = job_input.get("model", DEFAULT_MODEL)

    # Build the payload with only the keys the caller set, so the model's own
    # defaults apply to everything else.
    payload = {"prompt": prompt}

    # Optional passthrough / validated params
    resolution = job_input.get("resolution")
    if resolution:
        if resolution not in RESOLUTIONS:
            return {"error": f"resolution must be one of {sorted(RESOLUTIONS)}"}
        payload["resolution"] = resolution

    aspect_ratio = job_input.get("aspect_ratio")
    if aspect_ratio:
        if aspect_ratio not in ASPECT_RATIOS:
            return {"error": f"aspect_ratio must be one of {sorted(ASPECT_RATIOS)}"}
        payload["aspect_ratio"] = aspect_ratio

    if "duration" in job_input:
        payload["duration"] = int(job_input["duration"])  # -1 = intelligent, 1..15
    if "generate_audio" in job_input:
        payload["generate_audio"] = bool(job_input["generate_audio"])
    if "seed" in job_input and job_input["seed"] is not None:
        payload["seed"] = int(job_input["seed"])

    # URL-based reference inputs pass straight through.
    if job_input.get("image_url"):
        payload["image"] = job_input["image_url"]
    if job_input.get("last_frame_url"):
        payload["last_frame_image"] = job_input["last_frame_url"]
    for key in ("reference_images", "reference_videos", "reference_audios"):
        if job_input.get(key):
            payload[key] = job_input[key]

    open_handles = []
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            # base64 image inputs -> temp file handles the client will upload.
            if job_input.get("image_b64"):
                fh = _b64_to_tempfile(job_input["image_b64"], tmpdir, "first_frame")
                open_handles.append(fh)
                payload["image"] = fh
            if job_input.get("last_frame_b64"):
                fh = _b64_to_tempfile(job_input["last_frame_b64"], tmpdir, "last_frame")
                open_handles.append(fh)
                payload["last_frame_image"] = fh

            # Blocking call — replicate.run polls the prediction to completion.
            output = replicate.run(model, input=payload)

        video_url = _output_to_url(output)
        if not video_url:
            return {"error": "Model returned no video output", "raw": str(output)}

        result = {
            "status": "success",
            "video_url": video_url,
            "model": model,
        }
        if "seed" in payload:
            result["seed"] = payload["seed"]

        # Optional: download and return the clip as base64 (videos are large —
        # off by default; prefer handing the URL back to the caller).
        if job_input.get("return_b64"):
            resp = requests.get(video_url, timeout=120)
            resp.raise_for_status()
            result["video_b64"] = base64.b64encode(resp.content).decode("utf-8")

        return result

    except Exception as e:
        import traceback
        return {"error": str(e), "traceback": traceback.format_exc()}
    finally:
        for fh in open_handles:
            try:
                fh.close()
            except Exception:
                pass


runpod.serverless.start({"handler": handler})
