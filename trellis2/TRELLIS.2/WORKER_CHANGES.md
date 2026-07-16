# Our changes vs upstream microsoft/TRELLIS.2

Vendored from `microsoft/TRELLIS.2` at the commit in [`UPSTREAM_COMMIT`](UPSTREAM_COMMIT).
This copy is the source of truth for the worker — modify code HERE, not by
patching upstream at build time. The Docker build (`../Dockerfile`) copies this
directory into the image and compiles `o-voxel` from it.

## Removed (lean inference project)

| Path | Why |
|---|---|
| `assets/` | ~20MB of demo images/HDRIs — not needed to serve requests |
| `data_toolkit/` | training-data tooling (Blender scripts, renderers) |
| `trellis2/datasets/`, `trellis2/trainers/` | training-only code; nothing in the inference path imports it (verified: `trellis2/__init__.py` and all remaining modules have zero references) |
| `train.py`, `app.py`, `app_texturing.py` | training entrypoint + gradio demos; the worker's entrypoint is `../handler.py` |
| `setup.sh` | replaced by explicit installs in `../Dockerfile` (its getopt CLI silently no-ops in Docker — see v1 worker history) |
| `o-voxel/third_party/eigen/` | 23MB of third-party headers we never modify; the Dockerfile fetches them at upstream's exact pinned commit (`21e4582d1739...`) into the same path at build time |
| `o-voxel/assets/` | docs imagery |

## Kept

- `trellis2/` — the full inference package (models, modules, pipelines,
  renderers, representations, utils)
- `o-voxel/` — the O-Voxel CUDA extension source (`o_voxel` python pkg + `src/`)
- `configs/` — model/vae configs
- `example.py`, `example_texturing.py` — upstream reference for the API
- `LICENSE` (MIT), upstream `README.md`

## Modified

| File | Change | Why |
|---|---|---|
| `trellis2/pipelines/trellis2_image_to_3d.py` | `from_pretrained` honors a `REMBG_MODEL` env var to override the background-removal checkpoint from `pipeline.json` | upstream pins `briaai/RMBG-2.0`, which is license-gated on HF (live deploy confirmed 403); `ZhengPeng7/BiRefNet` — the wrapper's own default — is public and equivalent |
| `trellis2/pipelines/rembg/BiRefNet.py` | `__call__` casts the input tensor to the model's parameter dtype (and the prediction back to fp32) | RMBG-2.0 ships fp32 so upstream never casts; ZhengPeng7/BiRefNet ships fp16 — fp32 input crashed with "Input type (float) and bias type (c10::Half)" (live-confirmed) |
