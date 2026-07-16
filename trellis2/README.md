# TRELLIS.2 RunPod Serverless Worker

RunPod serverless worker for [TRELLIS.2](https://github.com/microsoft/TRELLIS.2)
(`microsoft/TRELLIS.2-4B`) — Microsoft's 4B-parameter image-to-3D model built on
**O-Voxel** structured latents, producing high-resolution geometry with full
**PBR materials** (base color, roughness, metallic, opacity) exported as GLB.

This is the "own upgrade" of the `trellis/` (TRELLIS v1) worker in this repo.

## What changed from the v1 (`trellis/`) worker

| | TRELLIS v1 (`trellis/`) | TRELLIS.2 (`trellis2/`) |
|---|---|---|
| Modalities | text-to-3D **and** image-to-3D | **image-to-3D only** |
| Model | `TRELLIS-text-xlarge` / `TRELLIS-image-large` | `microsoft/TRELLIS.2-4B` |
| Representation | sparse-conv structured latents (spconv) | **O-Voxel** (`o_voxel` extension) |
| Materials | vertex color / basic texture | **PBR** (basecolor/roughness/metallic/opacity) |
| GLB export | `postprocessing_utils.to_glb(...)` | `o_voxel.postprocess.to_glb(...)` |
| torch / CUDA | 2.4.0 / cu121 | **2.6.0 / cu124** |
| Extra CUDA exts | spconv, diffoctreerast, mip-splatting, nvdiffrast, kaolin | flash-attn, nvdiffrast, **nvdiffrec**, **CuMesh**, **FlexGEMM**, **o-voxel** |
| Min GPU VRAM | ~16GB | **≥24GB** (4B weights) |

**If you depend on text-to-3D, keep the v1 worker** — TRELLIS.2 removed it.

## Input

Image-to-3D via URL or base64 (same shape as the other workers):

```json
{
  "input": {
    "image_url": "https://example.com/car.jpg",
    "seed": 1
  }
}
```

```json
{
  "input": {
    "image_b64": "<base64 encoded image>"
  }
}
```

A `prompt` field is rejected with a clear error — TRELLIS.2 does not do text-to-3D.

## Output

```json
{
  "status": "success",
  "glb_b64": "<base64 encoded GLB file>",
  "glb_path": "/runpod-volume/outputs/<job_id>.glb",
  "mode": "image",
  "message": "GLB generated successfully"
}
```

The GLB is a **PBR** asset with WebP-compressed textures (`extension_webp=True`),
ready for Blender / Unity / Unreal.

## Code layout — the model code lives HERE

The TRELLIS.2 source is **vendored into this repo** at `TRELLIS.2/` (from
`microsoft/TRELLIS.2` at the commit in `TRELLIS.2/UPSTREAM_COMMIT`) and is now
maintained as our own project: modify the pipeline/model code directly in
`TRELLIS.2/trellis2/` and `TRELLIS.2/o-voxel/`, and the Docker build picks it
up — no upstream clone at build time, no drift. Training-only code, demo apps,
and 40MB of assets/third-party headers were stripped; the full delta vs
upstream is documented in `TRELLIS.2/WORKER_CHANGES.md`.

## Build

`.github/workflows/trellis2-docker-build.yml` builds and pushes on any push to
`trellis2/**` on `main`, tagged `alamk123/ai-mechanic:trellis2-v1`,
`:trellis2-latest`, and `:trellis2-<sha>`. Dependencies install before the
source `COPY`, so code edits reuse every cached extension-build layer and only
rebuild `o-voxel` onward.

The Dockerfile bypasses TRELLIS.2's `setup.sh` and installs each of its flags
explicitly (`--basic --flash-attn --nvdiffrast --nvdiffrec --cumesh --o-voxel
--flexgemm`), carrying over every build fix the v1 worker earned the hard way:
`--no-build-isolation` for extensions whose `setup.py` imports torch, a
`setuptools>=64` upgrade before nvdiffrast, and an explicit
`TORCH_CUDA_ARCH_LIST` so a GPU-less CI runner compiles for the right SMs.

## Deployment notes

- **≥24GB GPU required.** The 4B model plus O-Voxel decode won't fit on the
  AMPERE_24-minimum pools the v1 worker targeted comfortably — prefer L40S / A100
  / H100 (Ada/Hopper), which is also why `TORCH_CUDA_ARCH_LIST` covers `8.0;8.6;8.9;9.0`.
- Model weights + HF cache live on the mounted RunPod **network volume**
  (`HF_HOME=/runpod-volume/hf_cache`) so multi-GB checkpoints aren't redownloaded
  on every cold start. As with v1, if you reuse the existing region-locked volume
  the endpoint's GPU pool must be in that volume's data center.
- Every GLB is persisted to `/runpod-volume/outputs/<job_id>.glb`. Nothing prunes
  this directory — it grows unbounded until something cleans it up.
- `texture_size=4096` / `decimation_target=1,000,000` in the handler match
  `example.py`'s defaults; lower them to trade fidelity for speed and file size.

## Known unknowns (not yet GPU-build-tested)

Written from TRELLIS.2's published `setup.sh`, `README`, and `example.py`, but
**not build-tested on a GPU in this environment** — same honest caveat as the v1
worker. Most likely first-build failure points:

1. **Extension compilation** (flash-attn 2.7.3, CuMesh, FlexGEMM, nvdiffrec,
   o-voxel) against `torch==2.6.0 + cu124`. flash-attn in particular may fall back
   to a long source build if no matching wheel is found (`MAX_JOBS=4` caps it).
2. **The `pipeline.run()` seed kwarg** — `example.py` calls `run(image)` with no
   seed; the handler passes `seed=` and falls back to no-seed on `TypeError`.
3. **`o_voxel.postprocess.to_glb` field names** (`mesh.attrs` / `.coords` /
   `.layout` / `.voxel_size`) matching the object `run()` actually returns.

Run a real build via the CI workflow and fix forward from whatever surfaces
before pointing a production endpoint at this image.
