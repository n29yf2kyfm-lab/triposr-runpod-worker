# Video Generation RunPod Serverless Worker

Text-to-video and image-to-video worker for **Alam GPT**, built the same way as the
TripoSR worker in this repo. It runs an **open-source** video model on a RunPod GPU
and returns an MP4 as base64.

## Model

| Env | Model | Speed | License | Notes |
|-----|-------|-------|---------|-------|
| `MODEL_KIND=ltx` (default) | `Lightricks/LTX-Video` | Fast | LTX-Video open-weights license | Text+image→video, low VRAM |
| `MODEL_KIND=cogvideox` | `THUDM/CogVideoX-5b` | Slower | **Apache-2.0** | Safest license for a paid product |

> ⚠️ **Licensing:** LTX-Video is fast but check its open-weights license before
> commercial use. **CogVideoX-5b is Apache-2.0** — the clean choice for a commercial app.
> Swap by setting `MODEL_KIND` / `MODEL_ID` build args or endpoint env vars.

## Input

```json
{
  "input": {
    "prompt": "a red sports car driving along a coastal road at sunset, cinematic",
    "num_frames": 97,
    "width": 704,
    "height": 480,
    "steps": 40,
    "fps": 24,
    "seed": 0
  }
}
```

Image-to-video (LTX): also pass `image_url` or `image_b64`.

## Output

```json
{
  "status": "success",
  "video_b64": "<base64 mp4>",
  "mime_type": "video/mp4",
  "message": "Video generated successfully"
}
```

## Build & deploy

```bash
# From this directory
docker build -t <your-dockerhub>/alamgpt-video-worker:v1 .
docker push <your-dockerhub>/alamgpt-video-worker:v1
```

Then on RunPod → Serverless → New Endpoint:
- Container image: `<your-dockerhub>/alamgpt-video-worker:v1`
- GPU: 24–48 GB (your existing AMPERE_48 works well)
- Set env vars if using CogVideoX.
- Note the **Endpoint ID** — you'll give it to Alam GPT.

## Calling it from Alam GPT

The Lovable app calls RunPod server-side (never expose the key to the browser):

```
POST https://api.runpod.ai/v2/<ENDPOINT_ID>/runsync
Authorization: Bearer <RUNPOD_API_KEY>
Content-Type: application/json

{ "input": { "prompt": "..." } }
```

Store `RUNPOD_API_KEY` and `RUNPOD_VIDEO_ENDPOINT_ID` as **Supabase secrets** in the
Alam GPT project, and have the `/api/generate-video` edge function call the URL above,
then save the returned MP4 to Supabase Storage.

## Cost (approx, per short clip)

Serverless bills per second while the GPU runs. A few-second LTX clip is typically
tens of seconds of GPU time → **a few cents per clip**. Scales to zero when idle.
