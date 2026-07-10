# TRELLIS.2 RunPod Serverless Worker

RunPod serverless worker for [TRELLIS.2](https://github.com/microsoft/TRELLIS.2) (Microsoft) —
the 4B-parameter **image-to-3D** model that generates high-resolution meshes with full PBR
materials (Base Color / Roughness / Metallic / Opacity) via its field-free sparse-voxel
("O-Voxel") representation.

Upgraded from TRELLIS v1 (`TRELLIS-image-large`), which produced softer geometry and left
holes / black-glass artifacts on harder inputs. TRELLIS.2 adds sharper features, opacity/
transparency, and a `remesh` post-process that closes those surface holes.

## Input

Image-to-3D (URL or base64):

```json
{
  "input": {
    "image_url": "https://example.com/car.jpg",
    "seed": 1,
    "decimation_target": 500000,
    "texture_size": 2048
  }
}
```

`decimation_target` (target face count) and `texture_size` are optional knobs. TRELLIS.2-4B
is image-to-3D only — a text `prompt` is rejected here; the on-pod handler turns a prompt
into a reference image *before* calling this endpoint.

## Output

```json
{
  "status": "success",
  "glb_b64": "<base64 encoded GLB file>",
  "glb_path": "/runpod-volume/outputs/<job_id>.glb",
  "mode": "image",
  "model": "microsoft/TRELLIS.2-4B",
  "message": "GLB generated successfully"
}
```

## Deployment notes

- **Requires a GPU with ≥24GB VRAM** (TRELLIS.2-4B). RunPod's AMPERE_24 pool
  (RTX 3090 / A5000 / A6000) qualifies; the Dockerfile targets `TORCH_CUDA_ARCH_LIST=8.6+PTX`
  for that pool with PTX JIT for newer GPUs.
- **New image tags** — CI pushes `alamk123/ai-mechanic:trellis2-latest` and
  `:trellis2-<sha>`, deliberately separate from the v1 tags (`trellis-latest` / `trellis-v1`)
  so the working v1 endpoint keeps serving until a new endpoint is pointed at v2.
- Weights + HF cache read from the mounted RunPod network volume
  (`HF_HOME=/runpod-volume/hf_cache`) so cold starts don't redownload the multi-GB
  TRELLIS.2-4B checkpoint. The volume must be in the endpoint's data center (region-locked).
- Every generated GLB is persisted to `/runpod-volume/outputs/<job_id>.glb`; nothing prunes
  this yet, so it grows unbounded until a cleanup is added.
- GLB export uses `remesh=True` (closes holes), `extension_webp=False` (PNG textures for
  universal loader compatibility), `decimation_target=500000`, `texture_size=2048`.
- Env: `ATTN_BACKEND=flash-attn` (set `xformers` as a fallback on GPUs without
  flash-attention), `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`,
  `OPENCV_IO_ENABLE_OPENEXR=1`.

## Build

`setup.sh`'s `getopt` CLI silently no-ops in a non-interactive container (proven on the v1
image — the whole `. ./setup.sh` step ran in <1s and installed nothing), so the Dockerfile
replicates `setup.sh`'s exact commands directly: PyTorch 2.6.0 + cu124, the basic deps, then
each CUDA extension (flash-attn 2.7.3, nvdiffrast v0.4.0, JeffreyXiang's nvdiffrec renderutils
fork, CuMesh, FlexGEMM, and the in-repo o-voxel) with `--no-build-isolation`.

## Known unknowns

Written from TRELLIS.2's documented `setup.sh` and pipeline API but **not build-tested on a
GPU** in this environment. Likely first-build failure points, to fix forward from the CI log:

1. Extension compilation (CuMesh / FlexGEMM / o-voxel / nvdiffrec) against
   `torch==2.6.0`+`cu124` — a version pin or extra system dep may need adjusting.
2. Exact API surface (`Trellis2ImageTo3DPipeline.run()` return shape,
   `o_voxel.postprocess.to_glb(...)` kwargs) matching the current upstream `main`.
3. VRAM headroom for the 4B model at `texture_size`/`decimation_target` on a 24GB card.

Build via CI (this branch is wired into the workflow) and fix forward from the first error
before pointing a production endpoint at `:trellis2-latest`.
