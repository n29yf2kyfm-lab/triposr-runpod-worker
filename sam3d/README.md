# SAM 3D Objects — RunPod Serverless Worker

RunPod serverless worker for [Meta's **SAM 3D Objects**](https://github.com/facebookresearch/sam-3d-objects) — single-image 3D reconstruction. Sits alongside the TripoSR (root) and TRELLIS (`trellis/`, `trellis2/`) workers as an alternative image→3D backend.

## ⚠️ Read first — how this differs from the other workers

| | TripoSR / TRELLIS | **SAM 3D Objects** |
|---|---|---|
| Input | 1 image | **1 image + a segmentation mask** |
| Output | GLB **mesh** | **Gaussian splat `.ply`** (not a mesh) |
| Web viewer | `<model-viewer>` / three.js GLB | **splat renderer** (e.g. [GaussianSplats3D](https://github.com/mkkellogg/GaussianSplats3D)) |
| GPU | works on ~24 GB | **≥ 32 GB VRAM required** |
| Weights | open | **gated — SAM License** |

The Gaussian-splat output is the big one: it will **not** load in a plain GLB viewer. If the sparecarpart "360 viewer" expects GLB, you'll need either a splat-capable viewer or a mesh-extraction step (not provided by the upstream inference notebook).

## 🔑 License — check before commercial use

The code and the `facebook/sam-3d-objects` checkpoints are released under the **SAM License**, *not* MIT/Apache. Commercial use on a live site (sparecarpart) is **not automatically granted** — review [the LICENSE](https://github.com/facebookresearch/sam-3d-objects/blob/main/LICENSE) before shipping to production. This worker is wired up; the licensing decision is yours.

## Input

```json
{
  "input": {
    "image_url": "https://example.com/alternator.jpg",
    "mask_b64": "<optional 1-channel PNG mask, >0 = the object>",
    "seed": 42
  }
}
```

- `image_url` **or** `image_b64` (one required).
- `mask_b64` *optional*. If omitted, the whole frame is treated as the object — acceptable for a tightly-cropped part photo, but a real **SAM 3 / foreground mask is the single biggest quality lever**. Generate it upstream (Meta SAM 3, or a background remover such as the BiRefNet the `trellis2` worker already uses) and pass it here.

## Output

```json
{
  "status": "success",
  "format": "gaussian-splat-ply",
  "bytes": 4823192,
  "ply_b64": "<base64 gaussian-splat PLY>",
  "message": "Gaussian splat PLY generated successfully"
}
```

Large splats can exceed RunPod's inline response cap (the `trellis2` worker hit this and switched to a Supabase upload). The handler warns via a `warning` field when the payload is likely to be dropped; for production, add an object-store upload following the `trellis2` delivery pattern.

## Build

```bash
# facebook/sam-3d-objects is gated: accept the SAM License on huggingface.co,
# then pass a token whose account has access.
docker build --build-arg HF_TOKEN=hf_xxx -t <you>/sam3d-worker:v1 sam3d/
```

The build mirrors upstream [`doc/setup.md`](https://github.com/facebookresearch/sam-3d-objects/blob/main/doc/setup.md): a `micromamba` env (`sam3d-objects`), the two-step `pytorch3d` install, the `kaolin` find-links + `patching/hydra` inference step, then the gated checkpoint download into `checkpoints/hf/`. The `pytorch3d`/`kaolin`/`hydra` steps are the fragile part of the build — they use upstream's exact commands and index URLs.

## Deploy

Serverless endpoint on a **≥ 32 GB VRAM** GPU (A6000 / L40S / A100 / H100). Env overrides:

| Env | Default | Purpose |
|---|---|---|
| `SAM3D_ROOT` | `/app/sam-3d-objects` | repo location in the image |
| `SAM3D_TAG` | `hf` | checkpoint tag → `checkpoints/<tag>/pipeline.yaml` |
| `SAM3D_CONFIG` | `…/checkpoints/hf/pipeline.yaml` | full pipeline config path |
| `SAM3D_MAX_INLINE_BYTES` | `9437184` | size above which the inline PLY is flagged as likely-dropped |

## Status

Worker code + build follow the upstream documented API (`Inference(config)(image, mask, seed)` → `output["gs"].save_ply(...)`). **Not yet run end-to-end on a GPU** — the ≥32 GB VRAM requirement means it can't be smoke-tested in this environment. Recommend a one-off pod bootstrap (as `trellis2/pod_setup.sh` does) to validate before wiring it into the site.
