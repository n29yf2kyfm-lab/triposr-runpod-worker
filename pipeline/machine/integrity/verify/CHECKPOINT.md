# VERIFIER CHECKPOINT — Stages 7/8/9

Agent: INDEPENDENT glTF QA VERIFIER. Owns Stages 7, 8, 9.
Working dir: `.../scratchpad/integrity/verify/` — never enters `.../integrity/work/`.
Committed: `pipeline/machine/integrity/verify/` @ 7777398, pushed.
Bucket: `car-meshes/staging/integrity/verify/evidence/` (every upload verified by listing).

## DONE — rigs built and calibrated on the LOCKED SOURCE (baseline column)
- Source sha re-verified `400d994a…b21084f`, never modified.
- **Three ledgers balance exactly.** L1 verts 1,899,971 = 602,815 referenced + 1,297,156
  unreferenced; Blender = 602,815 exactly. L2 tris 928 = 4 degenerate + 924 duplicate
  INDEX triples (per primitive, extras-beyond-first) — reproduces coordinator's 924.
  L3 bbox agrees to 4e-7 m over 83 objects → nothing lost on import.
- **68.3% of declared positions are unreferenced.** Dual bbox now reported: declared
  x-min −2.176595 vs referenced-only −2.147268 (29.3 mm). Viewer sees referenced-only.
- **Stage 8 cameras verified by world direction**: azimuth err 0.0000°, aim err <0.014°,
  one height (2.618 m), one lens (85 mm), elevation 9°. No blank tile.
  Nose asserted −X by 4/4 interior-geometry signals. Exterior `_L/_R` suffixes are on the
  OPPOSITE side to automotive convention (naming only, but a camera named from a node
  name would be mirrored).
- **Exposure calibrated numerically**: bg 129.09 sRGB8 vs 129.13 predicted for Standard;
  clipped fraction 0.000000 in all eight tiles.
- **7/7 injected negative controls fired, each returning the injected magnitude exactly.**
- Backface culling reimplemented in-shader — Cycles ignores `use_backface_culling`, so
  the flag would have produced two identical sheets and a PASS on a dead test.

## BASELINE DEFECTS MEASURED (repair agent's to fix; mine to hold the numbers)
- **Wheel parity broken**: worst L/R surface-area difference **30.28%** (front discs),
  rear discs 23.67% with a **15.30%** vertical-span difference. Zero negative
  determinants, so mirroring is ruled out — the two sides are different meshes.
- **+Y-side wheels render with NO rim face** (5× zoom, same-image control): black void
  where the −Y side shows a full 10-spoke alloy.
- Body speckle across panels; a dark gash near the rear roof rail; glazing artefacts.
- Glazing: probe=clear, area 3.2884 m² = 3.58% of surface.
- Ground: all four tyres 0.000 m; lowest object `Arch_Liner` at −4.587 mm.

## RUNNING
`tools/chain_before.sh` → renders/CHAIN_BEFORE.done (stamps per stage).
original · faceorient · cullon · matid · wire · normal · clay · ortho ·
iso wheels/glass/interior · C4 render controls.

## NEXT
1. Stage 7 concealment diff (neutral vs original, same views).
2. Transform table + rear-artifact isolation + ground-contact crop.
3. model-viewer/Chromium harness (independent web viewer).
4. Stage 9 on the repaired GLB when the repair agent publishes.

## UPDATE 20:0x — Stage 7 honesty test FOUND A FAULT IN MY OWN RIG, and it is fixed
`conceal_diff.py` compares the neutral sheet against the shipped-material sheet on the
same eight cameras. Silhouette IoU = 1.000000 on all eight (materials cannot move
geometry, confirmed). But the worst local tile ratio was **0.058**, and the crop shows
why: the shipped RED render resolves seats, headrests and the B-pillar through the
glazing while my neutral glass went milky. My diagnostic set was CONCEALING the interior
— the exact failure the brief names. Cause: with transmission the base colour is the
transmission tint, and this car stacks `Glass_*` panes plus a separate
`Body_Glass_Reverted` shell, so a 0.6-luminance tint compounds to opacity across
interfaces. Fixed: glass base 0.880/0.915/0.940, roughness 0.02, transmission 0.98,
transmission bounces 8 -> 32. Re-rendering as `before_neutral2`; the diff will be re-run
and BOTH numbers reported.

## FINDINGS ADDED
- **Wheel void root-cause narrowed**: face-orientation render shows RED (backfacing)
  concentrated on the +Y-side wheels. Right-side views carry **3.72x** the backfacing
  pixel fraction of left-side views (0.03824 vs 0.01029). Determinants are all +1, so
  mirroring is ruled out. Rim outboard-facing area is present on both sides (L/R
  0.78-0.95), so it is not bulk-missing geometry. Handing the mechanism to the repair
  agent; my job is the measurement and it is recorded in `faceorient_before.json`.
- **model-viewer reports the car as 4.262953 m long** — the DECLARED accessor bbox,
  not the 4.233626 m of geometry a user can actually see. So the 1,297,156 unreferenced
  positions are not merely dead payload: they move the product viewer's own bounding
  box by 29.3 mm, which sets its framing and orbit radius.
- Independent viewer harness works: LOADED=true, 8/8 azimuths populated, material
  toggles operate (glass / Tyre_Rubber / carpaint). Single glazing material `glass`,
  alphaMode BLEND, baseColor alpha 0.161.
- `pipeline/machine/viewer_check.py` has a latent crash (KeyError 'bbox_min_y') when a
  model reports 0x0x0 dims: the printout is guarded by `if d:` but the field is only set
  when `scale > 0`. It took the run down before any console output was written.
