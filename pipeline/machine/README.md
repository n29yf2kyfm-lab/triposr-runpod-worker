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

## Live repair harness (`blender_live.py` + `blender_cmd.py`)

Every other stage above is one cold `blender -b` per operation. The live
harness keeps ONE scene resident behind a unix socket and takes JSON
commands, so an iterative repair — nudge, render, judge, nudge again —
does not pay boot+import per nudge.

```sh
B=pipeline/machine/blender_cmd.py
python3 $B start  --sock /tmp/golf.sock --glb car.glb   # ~3.0 s, paid once
python3 $B calibrate --sock /tmp/golf.sock              # PROVE Standard, not AgX
python3 $B select --sock /tmp/golf.sock --regex glass
python3 $B snapshot --sock /tmp/golf.sock --name pre --mode verts
python3 $B apply  --sock /tmp/golf.sock --repair translate --dz 0.01
python3 $B render --sock /tmp/golf.sock --out /tmp/a.png --az 45
python3 $B undo   --sock /tmp/golf.sock                 # revert if it looked wrong
python3 $B stop   --sock /tmp/golf.sock --clean
python3 $B replay /tmp/golf.sock.jsonl --glb car.glb    # the session, as a batch
```

Measured on `golf_final.glb` (65 MB, 592,715 verts / 983,512 faces):

| | cold `blender -b` | live session |
|---|---|---|
| one 700px/16spp view | 8.24–9.18 s | 4.31–4.51 s |
| info / select / measure | 8.2 s | 3–5 ms server-side |
| glTF import | 3.18 s every time | 3.18 s once |

* **Blender's own undo does NOT work in `-b`** — `ed.undo` raises
  `poll() failed, context is incorrect` and the mutation survives. Use
  `snapshot`/`restore`/`undo`: `mode=blend` is full fidelity
  (0.13 s / 0.6 s, 158 MB, capped at 4 and refuses under 2 GB free),
  `mode=verts` is geometry-only (0.01 s / 0.02 s, 7 MB) and REPORTS what
  it could not restore instead of silently restoring nothing.
* `calibrate` renders a 0.22 emission card and asserts sRGB 129.1 ±3 —
  the executable form of the AgX trap that once produced a false
  white-tyre verdict. Run it before trusting any render from a session.
* Judge geometry with `measure`, not `object.bound_box`: bound_box is
  cached and does not move when a `foreach_set` moves the mesh.
* The repair argument is `repair`, not `op` — `op` is the request's own
  reserved field.

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
