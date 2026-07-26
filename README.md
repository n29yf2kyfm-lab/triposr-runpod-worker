# TripoSR RunPod Serverless Worker

RunPod serverless worker for [TripoSR](https://github.com/VAST-AI-Research/TripoSR) — fast 3D model generation from a single image.

## Fixes in this version (v10.1)

- **Bug 1 fixed**: `unsupported operand type(s) for /: 'Image' and 'float'` — PIL resize now casts to `int`
- **Bug 2 fixed**: `AttributeError: 'torchmcubes_module' has no attribute 'mcubes_cuda'` — torchmcubes rebuilt from source with CUDA support
- **Bug 3 fixed**: Bulletproof VRAM detection

## Input

```json
{
  "input": {
    "image_url": "https://example.com/car.jpg"
  }
}
```

Or base64:

```json
{
  "input": {
    "image_b64": "<base64 encoded image>"
  }
}
```

## Output

```json
{
  "status": "success",
  "glb_b64": "<base64 encoded GLB file>",
  "message": "GLB generated successfully"
}
```

## Docker Image

`mehabualam/triposr-worker:v10.1`

## Deployment

Endpoint ID: `mj7aiqksmbnkw1` on RunPod (AMPERE_48 GPU)
# Trigger rebuild - secrets now configured

## Web UI

A demo front-end lives in [`web/index.html`](web/index.html): drop an image, call the
worker, and view the returned GLB in an interactive 3D viewer. Open it in a browser and
add your RunPod endpoint ID + API key under **Endpoint settings**.

The UI follows the [`DESIGN.md`](DESIGN.md) design system — a plain-markdown, AI-agent-readable
design document in the [awesome-design-md](https://github.com/voltagent/awesome-design-md)
format. Point your coding agent at `DESIGN.md` to generate UI that matches TripoSR Studio.
