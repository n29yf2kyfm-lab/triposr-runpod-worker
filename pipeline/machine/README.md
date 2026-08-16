# The Machine — photos → gated 3D car, end to end

This directory is the owner's own 3D machine: every stage proven in the
2026-08 experiments, wired into one chain. `machine.py` drives it.

## The chain

| stage | tool | where it runs | proven on |
|---|---|---|---|
| geometry | Pixal3D (TencentARC, MIT weights) | RunPod A100 80GB pod, ~12 min, ~$0.65 | Golf 2026-08-15: crease 271.6, catalogue-grade — the only generator to break the surfacing ceiling |
| canonicalise | `canon.py` | local CPU | Pixal output is CAMERA space; this puts length on X, Y up, grounded |
| 2D-seg labels | `../trellis/seg_views.py` → `seg_masks.py` → `seg_project.py` → `seg_refine.py` | local (Blender CPU + DINO/SAM CPU) | gseg Golf 2026-08-16 |
| glass boundary | `seg_boundary.py` | local CPU | per-window 2D stencils; killed the ragged borders + tailgate smear (v2, 2026-08-16) |
| surface denoise | `surface_clean.py` | local CPU | bilateral NORMAL filter — edge-preserving. NOT Taubin (measured: Taubin kills creases 145→36; bilateral cut noise while panels stayed crisp) |
| assemble | `../trellis/seg_assemble.py` | local CPU | textured `carpaint` body, factor-BLEND glass, quadrant tyre/rim, lamp lens |
| gates | `machine.py gates` | local | glass_probe clear/proven + no flat/alpha shell, else hard stop |
| production | render endpoint `ng8oiz4p2l0xa0` | RunPod serverless | 4 rubric views + BLUE CONTROL — the control is the verdict |
| eye | `../agent/wave_agent.py` eye stage (EYE_RUBRIC) | claude CLI | advisory SCRAP/PASS/UNSURE |
| owner | — | — | **nothing ships without the owner's sign-off** |

## Pixal3D pod deployment (paid-for facts, do not re-derive)

* Base env = our own `trellis2-worker-4b` image (template `i1mk2n9dap`) —
  already carries o_voxel/cumesh/flex_gemm/nvdiffrast + torch 2.6.0+cu124.
* `natten` prebuilt wheel `natten-0.17.5+torch260cu124-cp310` (NEVER source).
  torchsparse/spconv NOT needed. `ATTN_BACKEND=sdpa` removes flash_attn.
* `briaai/RMBG-2.0` is gated (403) and eagerly built in THREE modules — our
  inputs are RGBA cutouts so patch all three sites and assert the count.
* Full `--resolution 1536` fits an A100 80GB, ~12 min, no fallback.
* Pod-side fuse (self-delete at 45 min via the injected pod-scoped key) is
  the standard ceiling; watch `runtime.uptimeInSeconds` + GPU util, never
  `desiredStatus`.

## Rules the machine inherits

* The render is the arbiter — no metric or gate overrules the blue/red
  control or the eye.
* Glass is exhaustive after `seg_boundary`: it exists only inside a stamped
  window stencil, so smears cannot survive.
* Labels are per-face on the concatenated mesh in `sc.geometry.values()`
  order; `surface_clean` moves vertices only, so labels survive it.
* Balance floor before any GPU spend; verify with the GraphQL `myself`
  query. Credentials from `~/.alam3d_env`, never in the repo.

## Current state (2026-08-16)

v2 Golf (`car-meshes/staging/gseg/golf_seg2.glb`): all material gates pass,
glass borders straightened, panel noise halved (crease metric 635→380 with
creases surviving the render check). Remaining gap to catalogue: Pixal's
own panel micro-structure and soft shut lines — generator-bound, not
material- or boundary-bound.
