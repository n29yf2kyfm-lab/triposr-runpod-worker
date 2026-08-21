# CHECKPOINT — GATE 3 v7, front fascia rebuild (Golf Mk8 test bed)

**State: verification complete; deliverable uploaded and verified in the bucket.**

## The deliverable is NOT local-only (Rule Zero after rollback #6)

`car-meshes/staging/gate3_v7/glb/`, chunked to <=22 MB parts with a MANIFEST,
each upload confirmed by LISTING the prefix and comparing byte counts:

| object | bytes | sha256 |
|---|---|---|
| `GOLF_V7_FRONT_GATE.glb` (part_00 + part_01) | 28,397,676 | `3f681443004b2b243e66ac14e69437081e4512dcc4a2801ecac30ee0d99f0dd0` |
| `GOLF_V7_STRIPPED.glb` (part_00 + part_01) | 27,504,368 | in its MANIFEST |

Reassemble: `cat GOLF_V7_FRONT_GATE.glb.part_* > GOLF_V7_FRONT_GATE.glb`

## Base used, and why

`car_rebound.glb` (sha `5380761c…`, 28,703,944 B) — the base named in the brief.

A grounded alternative exists (`staging/merge/glb/car_merged.glb`, sha
`09897d20…`, all four tyres at 0.000 mm) and was downloaded, sha-verified and
evaluated. **Not adopted.** It is not a rigid re-pose of `car_rebound` (mean
20.1 mm / max 652 mm residual after a best-fit rigid transform; body rotated
4.7 deg), and this chain's datum detector is pose-calibrated: on that pose it
ran off the top of its search window and returned an identical y for all three
tangent thresholds, i.e. a zero-width band and a 656 mm "front face" against the
real car's 554. A guard now makes that failure loud (`plan7.py`,
`DATUM_UNTRUSTED`) and is negative-controlled: it fires on the merged pose and
stays silent on `car_rebound`. Adopting the grounded car needs the detector
recalibrated for its pose first — it must NOT be worked around by widening the
window until a number appears.

**The grounding correction changes nothing here**: this fascia is anchored to the
fascia (bumper lowest edge + bonnet leading edge), never to the ground.

## Tools (all in git, `pipeline/machine/gate3v7/`)

`survey.py` → `front_tex.py` → `plan7.py` → `strip.py` → `rebuild7.py` →
`finish.py`, with `coverage.py`, `verify7.py`, `tex_view.py`, `shoot.py`,
`geo7.py`, `upload_chunked.sh`. Re-runnable end to end from the base GLB.

## Headline measurements

* strip: 3 melt nodes deleted whole + 57,696 faces cut; 985,227 → 911,368
* coverage: holes **0.1 cm2** of a 5,926 cm2 footprint; new parts frontmost 97.0%
* symmetry: worst L/R deviation **5.9e-05 mm** (v6: 29.7 mm)
* evidence pack (54 objects) at `car-meshes/staging/gate3_v7/evidence/`
* provenance: **0.0** of any component's faces are original geometry
* self-intersections: 1,714 total, **200 within one shell** (v6: 10,258)
* winding inconsistent: none · not watertight: none · degenerate faces: 0
* centreline: badge/plate/grille/blade all 0.0000 mm
* validator E0 W0 · glass_probe clear/proven · respray red→blue reaches the new
  bumper and moves nothing else

## Corrections issued (see the final report)

1. base y extent is **1.4554 m**, not the 1.7798 m in the brief
2. tyre minima are FL +183.2 / FR +189.6 / RL +0.3 / RR +14.7 mm — front axle in
   the air, not a 324 mm offset (coordinator has since confirmed)
3. the v6 builder scripts named in the brief are **not** in git; what survived is
   the gate3v6 render/verify rigs plus an older `pipeline/machine/gate3/`
4. my own z=0.000 centreline was withdrawn: the car is bowed 140 mm nose-to-tail
5. trimesh drops every KHR material extension on ANY glTF round-trip — found by
   reading the written file, not by glass_probe, which still passed
6. gate3v6/rig.py's `beauty` pass is NOT material-preserving (it assigns the same
   neutral clay as `matte`), so no rig pass could judge whether the lamps read;
   `native_render.py` was written for that and it settles it — they do
