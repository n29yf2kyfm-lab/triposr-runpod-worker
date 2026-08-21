# STAGE 1 — BASELINE. Golf Mk8 root repair.

Status: **COMPLETE**. Nothing was modified; this stage only measures.

## Blocking gates declared up front

- **BLOCKED: EXACT YEAR/TRIM UNCONFIRMED.** No reference set supplied. Per the
  brief this is reported rather than guessed, and it hard-blocks Stage 3 and
  constrains Stages 6-8. No trim-specific lamp, bumper, wheel, badge or
  dimension has been invented anywhere in this report.
- **BLOCKED: MOBILE PERFORMANCE UNMEASURABLE.** No physical device is reachable
  from this environment. FPS/memory/load-time on a named device cannot be
  produced and will not be claimed.

## Input

| | |
|---|---|
| source | `car-meshes/staging/golfmk8/source/golfsrc.{00..03}` |
| reassembled | `GOLF_SOURCE.glb` |
| bytes | 65,125,312 |
| sha256 | `6fc6d30811a861a211e120a93d4acef1ab2754420e9151af9a6210de3dccbbe1` |
| backup | untouched; every tool reads it, none writes it |

The asset previously rendered for the owner (`car_glass_rebuilt.glb`, sha
`a26b63e2…`) is a DESCENDANT of this file. It is not the baseline.

## Measured statistics

dimensions 4.282 x 1.789 x 1.455 m · triangles 985,227 · vertices 592,715 ·
objects 6 · materials 6 · draw calls 6 · animations 0 · cameras 0 · lights 0 ·
textures 2 unique 4096x4096 PNG referenced by 4 image entries.

**glTF Validator: 30 ERRORS** (`ACCESSOR_VECTOR3_NON_UNIT` x30), 0 warnings,
1 info, 20 hints (`BUFFER_VIEW_TARGET_MISSING` x20,
`ACCESSOR_INDEX_TRIANGLE_DEGENERATE` x1). The baseline does not pass.

Topology: boundary_edges 203,703 across 14,643 open components ·
nonmanifold_edges 6,628 · inverted_faces 6,802 in 164 components ·
inconsistent_winding_edges 285 · degenerate/zero-area 6 · loose_vertices 3 ·
duplicate_faces 0 · negative scale 0 · mirrored 0 · hidden 0.

Intersections: carpaint/interior 3,112 face pairs · glass/interior 1,325 ·
Rim_Alloy/interior 766 · carpaint/glass 558 · Tyre_Rubber/carpaint 140.

UVs on carpaint and Rim_Alloy only. None on glass, Tyre_Rubber, Lamp_Lens,
interior.

## The two findings that change the plan

**1. THE FRONT TYRES ARE 194 mm OFF THE GROUND.** Measured per half-model:

    front tyres  z_min = +193.8 mm      rear tyres  z_min = +11.5 mm
    whole model  z_min =   +0.3 mm  (the interior)

Wheelbase 2.540 m from wheel-component centres, so the car sits **nose-up
4.11 deg**. The whole-model bbox reads +0.3 mm, which is precisely why a bbox
grounding test passes it — the failure this project has already recorded once.
This is a plausible ROOT CAUSE for the brief's observed "uneven wheel-arch gaps"
and for the side profile reading wrong, and it is cheap to correct.

**2. THE SOURCE IS BETTER THAN ITS DESCENDANT.** Present here and ABSENT or lost
in `car_glass_rebuilt.glb`: both headlamps, both tail lamps, all four door
handles, visible door shut lines, UVs, and textures. The downstream pipeline
destroyed them. That is the central input to the Stage 2 decision.

## Brief defects NOT confirmed against this baseline

Reported because the brief asserts them and the measurements disagree.

- **#10 estate/MPV proportions — NOT CONFIRMED.** 4.282 x 1.789 x 1.455 m,
  height/length 0.340, which is hatchback proportion; an MPV sits above 0.45.
  All 8 views read as a five-door hatchback. Cannot be checked against a Golf
  Mk8 reference (BLOCKED), but it is not estate-like.
- **#8 dissolved shut lines — NOT CONFIRMED IN THE SOURCE.** Door shut lines and
  four door handles are visible in views 3 and 7. They are missing DOWNSTREAM.
- **#4 broken, asymmetric headlamps — NOT CONFIRMED.** Both present and broadly
  symmetric in view 1. They are SOFT (no internal LED structure), not broken.
- **#5 floating badge — NOT CONFIRMED.** The badge reads as mounted on the
  grille bar in views 1 and 2. Needs a close-up to settle; recorded UNKNOWN.
- **#11 undersized wheels — PARTIALLY CONFIRMED, WEAK.** Largest wheel/tyre
  components measure 589-621 mm outer diameter. Whether that is correct cannot
  be decided without the reference set (BLOCKED). The arch-gap complaint is
  better explained by finding 1.

## Defects CONFIRMED by eye across all 8 views

Every one of the 8 fixed-camera views was examined at full resolution.

1. **Glazing torn — worst defect.** Pale/white torn regions across windscreen,
   both front door glasses, rear door glass, quarter glass and backlight.
   Materially WORSE on the left than the right, so the two sides are not
   equivalent and neither may be inferred from the other.
2. **A-pillar / windscreen surround torn**, white fragments running into the
   mirror area (views 2, 3, 8).
3. **Body panel waviness** — large irregular ripples across both sides' doors
   and quarters; worst on the RIGHT side (view 7).
4. **Front lower bumper / splitter melted** (views 1, 2, 8).
5. **Rear lower bumper / valance torn with holes** (views 4, 5, 6).
6. ~~**Roof spike artefact** near the rear roof, visible in 6 of 8 views.~~
   **RETRACTED 2026-08-21 after zooming. It is the SHARK-FIN ROOF AERIAL.**
   Measured: the tip narrows to a 103 x 31 mm footprint at x=+1.25, y=+0.057 --
   rear roof, on the centreline, which is where that aerial belongs. At 5x it
   shows the correct dark grey swept fin profile in both the rear and right-side
   crops. It reads as a spike ONLY at thumbnail scale. Evidence:
   `repair/SPIKE_ZOOM.png`. No action taken; deleting it would have removed a
   real component. This is the documented "zoom before writing anything down"
   failure, made again.
7. **Wheel-arch liners** read as flat grey patches with ragged edges.
8. **Lamp internals blank** — head and tail lenses have no internal structure.
9. **No rear number-plate recess** on the hatch (view 5).
10. **No semantic part structure whatsoever** — 6 objects grouped by MATERIAL.
    `Rim_Alloy` holds 60 disconnected components and `Tyre_Rubber` 41, mixed
    with trim, so no wheel, door, lamp or panel is addressable as a part. Stage
    10's naming scheme cannot be satisfied by renaming; it needs segmentation.

## Evidence

`car-meshes/staging/golfmk8/stage1/` — `BASELINE_8VIEW.png`,
`validator_baseline.json`, `baseline_scan.json`.

---

# REPAIR LEDGER

## R1 — ground and level

- **defect** front tyres airborne; car pitched nose-up
- **evidence** `stage1/baseline_scan.json`, per-half z measurement
- **root cause** whole-scene pitch. front tyre z_min +193.8 mm vs rear +11.5 mm
  over a 2.414 m wheelbase = **+4.318 deg nose-up**. Whole-model z_min reads
  +0.3 mm (the interior), which is why a bbox grounding test passes it.
- **action** rigid rotate about Y to level the axle contact points, then drop
- **objects changed** all root nodes (transform only; no geometry touched)
- **before/after** `repair/R1_BEFORE_AFTER.png`
- **verification** front **-0.00 mm**, rear **+0.00 mm**, residual pitch
  **0.0000 deg**; rigidity by total triangle area 63.607986 -> 63.607986 m2
  (**0.005 ppm**); glTF Validator **30 errors -> 0**
- **result** **PASS**
- **remaining uncertainty** the round-trip duplicated shared texture bufferViews
  (see R2). Ride height is now level but has NOT been checked against a Golf Mk8
  reference (BLOCKED).
- **my own error** the first rigidity test compared axis-aligned bbox extents and
  reported FAIL at 9.2/12.2 mm. An AABB is not rotation-invariant; the test was
  wrong, not the repair. Replaced with total surface area.

## R2 — texture dedupe and downsize

- **defect** 65.1 MB file, 57.4% textures, 4096x4096, over every perf gate; plus
  R1's regression to 102.3 MB
- **root cause** two unique textures referenced by four image entries; R1's
  exporter split the two SHARED bufferViews into four copies
- **action** collapse by SHA-256 of payload, repoint textures, downsize to 2048,
  re-encode by ROLE (colour->JPEG, data->PNG), drop alpha only where every
  referencing material is `alphaMode: OPAQUE`
- **verification** 102.3 -> **34.2 MB**; textures 74.70 -> **6.55 MB** (19.2% of
  file); images 4 -> 2; validator **0/0/0/0**; metallicRoughness **bit-exact**
  (PSNR inf, max abs err 0); baseColor PSNR **33.18 dB** at q90
  (q95 = 34.41 dB / +0.45 MB, q98 = 35.04 dB / +1.09 MB -- measured, q90 kept)
- **result** **PASS**
- **remaining uncertainty** still 34.2 MB against a 20 MB gate. The remaining
  27.6 MB is GEOMETRY, not textures.

## R3 — floating debris

- **defect claimed** "roof spike artefact" in 6 of 8 views
- **result** **NO ACTION — TARGET MISIDENTIFIED.** It is the shark-fin roof
  aerial. See the retraction in the Stage 1 defect list.
- **two failed detectors, both recorded so they are not rebuilt.** A
  disconnected-outlier test flagged window-frame fragments as protruding
  700-990 mm, because the height envelope has no samples over a window aperture
  so anything there reads as protruding by the full roof height. A
  local-height-residual test then flagged 27,387 vertices across the whole car,
  because a car is not a height field -- for one (x,y) there is a roof, a sill
  and a floor. Both would have deleted real geometry.
- **what settled it** the direct question: the highest vertices narrow to a
  103 x 31 mm footprint at x=+1.25, y=+0.057, then a 5x crop.
- **genuinely found, deferred to the shell stage** the rear roof / backlight
  junction is torn, and there is a small hole in the roof skin.

## R4 — glazing rebuild

- **defect** torn glazing, worst visible defect in all 8 baseline views
- **evidence** `repair/R4_GLASS_BEFORE_AFTER.png`, `repair/r4_report.json`
- **root cause** every window shares ONE object called `glass`: 278 components,
  31,610 cm2, with pinholes, detached shards and unstitched inner skins.
- **action** classify components into windows SEMANTICALLY (dominant normal axis
  + position), fit one surface per window, emit fresh grid geometry, solidify.
- **verification** 4 named panes, each **1 component / 0 boundary edges**;
  footprint ratios 0.987-1.020; debris 258 components / 334.8 cm2 (1.06%)
  removed; validator **0/0/0/0**.
- **result** **PASS on integrity, INCOMPLETE on shape** -- see uncertainty.
- **remaining uncertainty, stated plainly.** The panes are watertight but their
  OUTLINES are the source's outlines. `Glass_Windscreen` emits 3,228 cm2 where a
  Golf windscreen is roughly 11,000-14,000 cm2, because the source's windscreen
  glass is largely ABSENT: its fragments span y -0.11..+0.58 plus a full-width
  cowl strip, so most of the right-hand side has no glass to fit. A surface fit
  cannot invent geometry that is not there. Closing this needs aperture-driven
  outlines (attempted on a previous car and defeated by fragment-soup body
  geometry) or a reference set -- and the reference set is BLOCKED.
- **my own error, corrected mid-repair** the first pass fitted each pane from its
  LARGEST member and built the windscreen out of the 1,414.7 cm2 cowl strip,
  emitting a 1,347 cm2 "windscreen". Fitting the whole semantic class instead
  took it to 3,228 cm2. Fitting the union is safe here only because the
  classifier guarantees every member is the same physical window.

## R5 — decimate to the triangle budget

- **defect** 1,056,016 triangles against a 250,000 gate; 40.0 MB against 20 MB
- **root cause** 62% of the mesh is INTERIOR (658,473 tris) seen only through glass
- **action** allocate the budget by visibility, not uniformly: interior -> 60,000
  (ratio 0.0911), body shell -> 120,000, rims/tyres/lamps kept whole. Glass panes
  EXCLUDED from decimation and re-emitted at half raster instead, because a
  collapse decimator punches holes in a closed thin shell.
- **verification**
  * **248,115 triangles**, **16.46 MB**, validator **0/0/0/0**, 9 draw calls
  * panes still **0 boundary edges** before AND after
  * dimensions moved at most **0.60 mm** (4.2733 -> 4.2734 x 1.7887 x 1.4682 m)
  * glass pane areas within **1%** of the full-raster emission
  * matched-camera render vs pre-decimation: only **4.86% / 4.99% of the frame
    changed at all**, mean 9.8 / 11.2 levels; only **0.086% / 0.129%** of pixels
    differ by more than 64 levels
  * a difference heat map shows the large changes concentrated on ALREADY-TORN
    geometry -- the shattered A-pillar surround, ragged greenhouse edges, the
    tail-lamp region. Clean panels are near-black. Decimation spent its losses
    on noise, not on surface.
- **result** **PASS**
- **my own error** the first quality figure was PSNR over a "car only" mask built
  by excluding grey pixels. It reported 69.4% of the frame as car, because the
  studio backdrop and floor are not exactly neutral grey -- so identical
  floor pixels inflated the score. Replaced with the measure that does not need a
  mask: how many pixels changed, by how much.
- **remaining uncertainty** PSNR is measured against the PRE-DECIMATION render,
  which proves decimation cost little. It does NOT prove the asset is good --
  the shell defects it preserved are still there.

# GATE STATUS after R1-R5

| gate | baseline | now | |
|---|---|---|---|
| GLB <= 20 MB | 65.1 MB | **16.46 MB** | PASS |
| triangles <= 250,000 | 985,227 | **248,115** | PASS |
| textures <= 2048 | 4096 | **2048** | PASS |
| validator errors | **30** | **0** | PASS |
| tyres grounded | +193.8 mm front | **0.00 mm** | PASS |
| glazing watertight | 278 components | **4 panes, 0 boundary edges** | PASS |
| mobile FPS on a named device | - | - | **BLOCKED, no device** |
| proportions vs reference | - | - | **BLOCKED, no references** |
| shell free of tears | - | - | **FAIL, not attempted** |
| semantic hierarchy | 6 material groups | 6 + 4 panes | **FAIL** |
