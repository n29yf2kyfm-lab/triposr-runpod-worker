# pipeline/machine/gate3v6 — GATE 3 v6 evidence & proof-pack render rigs

Renders only. **Nothing in here modifies a GLB.**

    python3 run_proof.py <target.glb> <TAG> <outroot> \
            [--baseline <before.glb> --baseline-tag V0] [--only sheet|proof|baseline]
    python3 build_index.py <outroot> <TAG> --baseline-tag V0 --ref-dir <ref/>

Produces the 15-item proof package (each ≥ 2048 px), the canonical 8-view sheet
(per-tile fit, 75–85 % occupancy), a constant-scale companion sheet, and
`PROOF_INDEX.md` + `index.json`.

## Files
| file | side | what |
|---|---|---|
| `rig.py` | Blender | cameras, fit maths, materials, lights, zebra world, **exposure probe**, frame measurement |
| `render_job.py` | Blender | executes a list of views against ONE imported GLB, writes a DONE marker |
| `plan.py` | CPU | component discovery from transformed vertices, classification, explode ranks |
| `compose.py` | CPU | PIL composition: labels, 8-view sheet, symmetry map, legends, scale bars |
| `run_proof.py` | CPU | orchestrator (job specs → Blender → metadata) |
| `build_index.py` | CPU | composes deliverables and writes the index |
| `upload.sh` | CPU | Supabase upload **with verification of the written object** |

## AXIS / AZIMUTH CONTRACT — this is the thing renders keep getting burned on
Measured on `GOLF_V5_SOURCE_LOCKED.glb` and re-confirmed from the first render:
**the nose is at −X.** So for this file

    az 270 = FRONT      az 090 = REAR      az 000 = LEFT      az 180 = RIGHT
    az 305 / 315 = FRONT-LEFT 3/4          az 215 / 225 = FRONT-RIGHT 3/4
    az 045 = REAR-LEFT 3/4                 az 135 = REAR-RIGHT 3/4

(+Z is the car's LEFT, because the car faces −X.) This is the **inverse** of the
mapping in CLAUDE.md's rig note, which assumes nose-at-+X; `canon_dims.py`'s nose
rule gets this file wrong and does not warn. Camera placement is
`cam_x = R·sin(az)`, `cam_y_blender = −R·cos(az)` — see `rig.cam_position`.

## Container facts, fenced in code so they are not re-paid
* Blender 4.0.2, **Cycles only** (EEVEE cannot initialise — no EGL).
* **No OpenImageDenoiser**: `use_denoising=True` raises and the render dies
  *after* "Blender quit" prints, leaving stale frames. Every output path is
  unlinked before rendering and the runner writes its own `_DONE_*` marker —
  **grep for the marker, never for Blender's exit.**
* **Blender's bundled Python has no PIL.** Image reads inside Blender go through
  `rig.read_png_rgba()` (`bpy.data.images.load` + Non-Color colourspace).
* `blender -b --noaudio …` **fails**: `-b` swallows the next token as a filename.
* Cycles Wireframe node output is `"Fac"`, not `"Fact"`.
* View transform is **Standard**, never AgX.

## Exposure is measured, not assumed
`rig.auto_exposure()` renders a small alpha-masked probe of the *current* scene,
takes the p99.8 linear luminance of **car pixels only**, and sets
`view_settings.exposure` so the brightest surface lands just under clipping. The
same probe yields the exact silhouette coverage used for the populated-tile and
occupancy assertions. Every written frame is then re-read
(`rig.measure_render`) for its actual clipped-pixel fraction and background
level. A 0.22 world background must land at sRGB 129 — that is checked per view.

## Three bugs this rig had, caught by validating on the locked baseline first
1. `make_camera` never updated the depsgraph, so `matrix_world` was stale and
   **every view got the same ortho scale** (the side view's).
2. `project_extent` ignored `cd.shift_*` and the recentring sign was **inverted**,
   which framed the exploded views on empty background.
3. The first light rig ran ~5× hot and clipped **3.67 %** of the frame.

All three would have shipped wrong evidence that still *looked* like evidence.
Validate any change to this rig against `g3v6/locked/` before an expensive run —
`G3V6_RES_SCALE=0.2 G3V6_SAMP_SCALE=0.12` renders the whole package in ~90 s.

## Two things the rig deliberately does NOT do
* It does not judge. A render that suggests a defect is a **candidate**; verdicts
  belong to the verifier.
* It does not use glossy paint, bloom, dark materials or a dark background for
  any surface judgement — clay and neutral matte only, grey backgrounds only.
