# Seedance 2.0 Video Worker

RunPod serverless worker that turns a product photo (or a text prompt) into a
cinematic video using **ByteDance Seedance 2.0** via the
[Replicate API](https://replicate.com/bytedance/seedance-2.0).

Unlike the TripoSR / TRELLIS workers in this repo, this one does **no local model
inference** — it's a thin proxy that calls Replicate, which runs the model. So it
needs **no GPU**: build it on a slim CPU image and run it on RunPod's cheapest
serverless workers.

## Setup

Set your Replicate token as a RunPod **secret / environment variable** on the
endpoint:

```
REPLICATE_API_TOKEN=r8_xxx...
```

Optional overrides:

| Env var | Default | Purpose |
|---|---|---|
| `REPLICATE_API_TOKEN` | — | **Required.** Your Replicate API token. |
| `SEEDANCE_MODEL` | `bytedance/seedance-2.0` | Pin a different model or a specific `owner/model:version`. |

## Input

Only `prompt` is required. One unified model handles text-to-video,
image-to-video, and reference-to-video.

| Field | Type | Notes |
|---|---|---|
| `prompt` | string | **Required.** Describe subject + motion + camera + lighting. Max 4000 chars. |
| `image_url` | string | First-frame image URL → image-to-video. |
| `image_b64` | string | First-frame image as base64 (data-URI prefix optional). Uploaded to Replicate automatically. |
| `last_frame_url` / `last_frame_b64` | string | Optional end frame for start→end transitions (needs a first frame). |
| `reference_images` | list\<url\> | Up to 9 — character consistency / style / composition. |
| `reference_videos` | list\<url\> | Up to 3 — motion transfer / style (total ≤ 15s). |
| `reference_audios` | list\<url\> | Up to 3 — audio-driven / lip-sync (needs a reference image or video). |
| `duration` | int | Seconds, `1`–`15`. `-1` = model picks the best length. Default `5`. |
| `resolution` | string | `480p` \| `720p` \| `1080p` \| `4k`. Default `720p`. |
| `aspect_ratio` | string | `16:9` `4:3` `1:1` `3:4` `9:16` `21:9` `9:21` `adaptive`. Default `16:9`. |
| `generate_audio` | bool | Native synced audio. Default `true`. |
| `seed` | int | For reproducibility. |
| `return_b64` | bool | If `true`, also download the clip and return it as `video_b64`. Off by default — videos are large; prefer the URL. |
| `model` | string | Override the Replicate model id for this call. |

## Output

```json
{
  "status": "success",
  "video_url": "https://replicate.delivery/.../output.mp4",
  "model": "bytedance/seedance-2.0",
  "seed": 42
}
```

## Example request

```json
{
  "input": {
    "prompt": "A slow, smooth 360-degree orbit around the exact product shown, kept centered and unchanged. Soft studio lighting with a gentle rim light, seamless charcoal background, shallow depth of field, premium commercial look, subtle reflections, cinematic color grade.",
    "image_url": "https://your-cdn.com/product.jpg",
    "duration": 8,
    "resolution": "1080p",
    "aspect_ratio": "9:16",
    "generate_audio": true
  }
}
```

## Notes

- Each call spends **your Replicate credits** (billed per second of output).
- The handler blocks until the prediction completes (`replicate.run` polls
  internally), then returns the finished video URL.
- For batch A/B ad testing, vary one dimension at a time (camera move, lighting,
  resolution) so results stay comparable.
