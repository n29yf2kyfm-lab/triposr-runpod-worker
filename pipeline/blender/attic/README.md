# attic/ — retired scripts. DO NOT run these on library assets.

Kept for reference only (methods, lessons, one-off history). Each has a
specific reason it must not re-enter the pipeline:

| Script | Why it is here |
|---|---|
| `automotive_refinery.py` | Stage 3b **clears ALL materials on every mesh** (glass/trim destroyed) and applies one paint. The header comment promising to keep the baked texture is not implemented. Its own 2026-07-14 verdict deprecates it in favour of the tint pipeline. |
| `build_golf.py` | Proven-negative experiment (recorded 2026-07-13): a car built from primitives + subsurf does not read as that car. Kept as documentation of the limit. |
| `fix_bmw5.py` | One-off for one specific GLB — hardcodes `Object_9..20`; recolours the wrong objects on anything else. |
| `palette_recolour.py` | One-off; UV point-sampling under-covers large palette patches on high-res atlases. Superseded by `generic_recolour.py` (multiply-tint). |

Production set lives one directory up. Recolour = `generic_recolour.py`
(offline) / the render worker's tint mode (serve time). Assembly =
`prop_fix.py` → `cabin_assembly.py` (→ optional `wheel_replace.py`).
