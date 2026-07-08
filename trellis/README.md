# TRELLIS RunPod Serverless Worker

RunPod serverless worker for [TRELLIS](https://github.com/microsoft/TRELLIS) (Microsoft) —
structured-latent diffusion model for both **text-to-3D** and **image-to-3D** generation.

Replaces the earlier Hunyuan3D-2 deployment, which only supported image-to-3D despite the
handler expecting a text `prompt` — see repo history for the diagnosis.

## Input

Text-to-3D:

```json
{
  "input": {
    "prompt": "a small toy car, cinematic, high detail",
    "seed": 1
  }
}
```

Image-to-3D (URL or base64, same as the TripoSR worker):

```json
{
  "input": {
    "image_url": "https://example.com/car.jpg"
  }
}
```

## Output

```json
{
  "status": "success",
  "glb_b64": "<base64 encoded GLB file>",
  "mode": "text",
  "message": "GLB generated successfully"
}
```

## Deployment notes

- **Data center pinned to EU-SE-1.** Model weights and HF cache are read from the
  `hunyuan3d-models` network volume (`kyh32l0npu`, 200GB), which lives in EU-SE-1. Network
  volumes are region-locked, so the serverless endpoint's GPU pool must be EU-SE-1 or the
  volume can't be attached.
- `SPCONV_ALGO=native` is set deliberately — TRELLIS's default `auto` mode benchmarks
  multiple kernel algorithms on first run, which is slow and non-deterministic for a
  serverless cold start.
- CI (`.github/workflows/trellis-docker-build.yml`) builds and pushes on any push to
  `trellis/**` on `main`, tagged `alamk123/ai-mechanic:trellis-v1` and `:trellis-latest`.

## Known unknowns

This Dockerfile and handler were written from TRELLIS's documented `setup.sh` install flow
and published pipeline API, but have **not been build-tested on a GPU** in this environment.
The most likely failure points on first real build:

1. `setup.sh` CUDA extension compilation (spconv / nvdiffrast / diffoctreerast / kaolin)
   failing against `torch==2.4.0` + `cu121` — pin versions may need adjustment to whatever
   TRELLIS's `main` branch expects at build time.
2. Exact pipeline class/method names (`TrellisTextTo3DPipeline`, `TrellisImageTo3DPipeline`,
   `.run()`, `postprocessing_utils.to_glb()`) matching the current upstream API.

Run a real build via the CI workflow (or locally) and fix forward from whatever error surfaces
before pointing a production endpoint at this image.
