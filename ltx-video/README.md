# LTX-Video Worker

RunPod serverless worker that generates video **on the GPU** from a product photo
+ prompt, using the open [LTX-Video](https://huggingface.co/Lightricks/LTX-Video)
image-to-video model. No external API, no per-call API credits — you pay only for
RunPod GPU time.

> Seedance 2.0 is closed-source and can't be self-hosted; LTX-Video is the open
> image-to-video model used here instead.

## Input

| Field | Type | Default | Notes |
|---|---|---|---|
| `prompt` | string | — | **Required.** Subject + motion + camera + lighting. |
| `image_url` / `image_b64` | string | — | First frame → image-to-video. Omit for prompt-only. |
| `negative_prompt` | string | quality boilerplate | What to avoid. |
| `width` / `height` | int | 704 / 480 | Rounded to a multiple of 32. |
| `num_frames` | int | 121 | Rounded to `8k+1`. ~24fps → 121 ≈ 5s. |
| `num_inference_steps` | int | 40 | More = sharper, slower. |
| `fps` | int | 24 | Output framerate. |
| `seed` | int | — | Reproducibility. |

## Output

```json
{ "status": "success", "video_b64": "<base64 mp4>", "model": "Lightricks/LTX-Video",
  "width": 704, "height": 480, "num_frames": 121, "fps": 24 }
```

Video is returned as base64 MP4. Decode with e.g. `base64 -d > out.mp4`.

## GPU / memory

Fits 16–24 GB cards (RTX A4000/A4500/A5000, L4, RTX 3090). VAE tiling is enabled.
On tight VRAM set env `LTX_CPU_OFFLOAD=1` (slower) or lower `width`/`height`/`num_frames`.

## Cold start

Weights are **not** baked into the image (keeps it small + CI reliable); they
download on first cold start. **For production, attach a RunPod network volume** to
the endpoint — the handler sets `HF_HOME=/runpod-volume/hf`, so weights download
once and are reused instead of per-worker.

## Example

```json
{ "input": {
    "prompt": "Slow 360-degree orbit around the product on a seamless charcoal background, soft studio rim light, shallow depth of field, cinematic, premium commercial look",
    "image_url": "https://your-cdn.com/product.jpg",
    "width": 768, "height": 512, "num_frames": 121, "fps": 24
} }
```
