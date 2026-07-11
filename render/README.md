# GPU Render Worker (serverless)

Cinematic car renders on the GPU, mirroring the TRELLIS worker's shape: built by
CI into `alamk123/ai-mechanic:render-latest` and served by a RunPod **serverless**
endpoint that scales to zero.

Given a car GLB + a DVLA colour + an optional UK plate, it returns a hero PNG:
dark studio backdrop, three-point lighting (key/rim/fill + wheel kick), clearcoat
gloss on the body-paint material, reflective floor, and AgX high-contrast grade —
the same look as the local `cine_render.py`, but Cycles **GPU** (OPTIX→CUDA→CPU
fallback), ~10–25 s/frame instead of minutes.

## Input

```json
{ "input": {
    "glb_url": "https://…/model.glb",   // or glb_b64, or glb_path(+glb_base)
    "glb_auth": "Bearer …",             // optional, for private-bucket URLs
    "colour": "blue",                    // optional body recolour (DVLA colour)
    "plate": "LV24 TGN",                 // optional UK plate on the front bumper
    "az": 40, "elev": 0.15, "zfrac": 0.32,
    "samples": 160, "width": 1600, "height": 900
} }
```

One of `glb_b64` / `glb_url` / `glb_path`(+`glb_base`) is required. `colour` only
repaints the detected body-paint material (glass/wheels/trim untouched); on
single-material models it is ignored so nothing overspills.

## Output

```json
{ "status": "success", "png_b64": "<base64 PNG>",
  "device": "OPTIX|CUDA|CPU", "seconds": 14.2 }
```

## Deploy

CI builds on pushes touching `render/`. Create a RunPod **serverless** endpoint
from `alamk123/ai-mechanic:render-latest` on a 24 GB Ampere/Ada GPU
(`ATTN`-free — this is plain Cycles), execution timeout ~120 s, min 0 / max N
workers. Higher `max` = pre-warm the library faster (same GPU-hours).

## Pre-warm

To fill the cache: for each library GLB × colour, call `/run` with a signed
`glb_url` (or `glb_b64`), take `png_b64`, and upload it to the render cache
bucket keyed by make/model/colour. First view of any car is then a cache hit.
