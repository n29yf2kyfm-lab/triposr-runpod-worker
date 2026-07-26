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

## Design system

[`DESIGN.md`](DESIGN.md) is a plain-markdown, AI-agent-readable design document in the
[awesome-design-md](https://github.com/voltagent/awesome-design-md) format. Point your
coding agent at it to generate UI that matches the **TripoSR Studio** look — a dark
render-viewport aesthetic with a violet→cyan signature.

[`web/index.html`](web/index.html) is a static **preview** of that system: a visual catalog
of the tokens, typography, and components rendered exactly as `DESIGN.md` specifies. It's
self-contained and offline — no networking, no backend calls. Open it in any browser.
