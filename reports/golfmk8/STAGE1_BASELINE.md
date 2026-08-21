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
6. **Roof spike artefact** near the rear roof, visible in 6 of 8 views.
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
