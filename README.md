# TRELLIS.2 RunPod Serverless Worker

Image-to-3D generation for Expert Car Check Pro, powered by
[microsoft/TRELLIS.2-4B](https://github.com/microsoft/TRELLIS.2) (MIT licence).

The worker lives in [`trellis/`](trellis/) — see its
[README](trellis/README.md) for the build, API, and deployment details.

## Pipeline (one engine, one endpoint)

- **Generation:** a single-image TRELLIS.2-4B worker (`trellis/handler.py`),
  built by CI (`.github/workflows/trellis-docker-build.yml`) and served by one
  RunPod serverless endpoint (`trellis2-v2`, scale-to-zero, execution timeout).
- **Rendering:** premium GLB → hero render (HDRI studio + tinted glass + DVLA
  paint + AgX) runs on the render pod, not here.

## Input

```json
{ "input": { "image_b64": "<base64 image>", "seed": 1,
             "decimation_target": 120000, "texture_size": 1024 } }
```

`image_url` is also accepted. Plain photos are background-removed on-worker with
the free, MIT-licensed ZhengPeng7/BiRefNet; a pre-cut RGBA image skips that step.

## Output

```json
{ "status": "success", "glb_b64": "<base64 GLB>", "mode": "image",
  "model": "microsoft/TRELLIS.2-4B" }
```

## History

This repo began as a TripoSR worker and briefly hosted TripoSR/Hunyuan3D
experiments; those have been removed. It is now solely the TRELLIS.2 worker.
