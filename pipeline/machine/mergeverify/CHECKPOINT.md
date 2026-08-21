# CHECKPOINT — INDEPENDENT VERIFIER (merged Golf Mk8)

Working dir `.../scratchpad/mergeverify/` · branch `claude/lovable-connection-ki7jch`
Tools + report committed at `pipeline/machine/mergeverify/` (commits 51d6f9f, beb0e84,
bd73f7c — all pushed). Evidence bucket-backed at `car-meshes/staging/mergeverify/`
(verified by LISTING the prefix and by a byte-identical round-trip of MERGE_VERIFY.json).

## STATE
Harness **built, calibrated and control-proven** on the six source cars.
**The merged car has NOT been published** — `staging/merged/`, `merge_all/`, `final/`,
`mergebuild/`, `golf_merged/` all EMPTY as of the last poll. Every "measured on the
merged car" cell is honestly NOT TESTED.

## DELIVERABLES (bucket + git)
`MERGE_VERIFY.md` (17-row table, 12 controls, acceptance list A1–A20) ·
`MERGE_VERIFY.json` · `verify_merged.py` (one-command runner) ·
`evidence/` (hole_selftest, throughglass, specks_final, respray, provenance, waviness,
nodetrees, rigid_transform, LIGHT_CALIB, ROOF_BEFORE_AFTER.png, orient render)

## SCORE ON THE GATES' OWN FILES
13 of 17 checks reproduce exactly · 1 direction-only (waviness, definition differs) ·
1 with ±2 pp placement sensitivity (hidden melt) · 1 pending (contiguous-hole control) ·
1 gate deliverable FAILS the material set on its own file (rear v2).

## THE FOUR FINDINGS THE MERGE MUST ACT ON
1. **rear2_v4.glb material table is not shippable** — `extensionsUsed` ABSENT,
   `carpaint` = [1,1,1,1] metallic 1 rough 1 (glTF-defaults flat-shell signature),
   `Rim_Alloy` the same, `Tyre_Rubber` 0.0484 not 0.0288. Geometry win is real.
   `glass_probe` still says clear/proven on it.
2. **rebound → merged is ONE RIGID TRANSFORM** for body+glazing+bumpers: 4.7301° about
   [0.1105,−0.4826,0.8689], t = [−0.47,−101.61,+11.87] mm, max residual **0.1225 µm**.
   Wheels are not part of it (8.0–8.7 mm; FL/RL ~177.5° re-seats). So glass relabelling
   + v7 front kit can be TRANSPORTED, not re-derived; wheels come from car_merged.
3. **Front and rear kits use different lateral datums** — +27.30 mm vs ≈ −70 mm
   (each on its own end's axle centre; spread ~105 mm). Unstated anywhere.
4. **glass and v7 do NOT carry the grounding fix** (tyres still 183/189 mm up).

## CONTROLS THAT FIRED (16) — nc/
NC1 +5.000 mm → 5.0000 · NC2 glazing→2.5% → 0.9894→0.0238 m² · NC3 KHR stripped →
detected · NC4 normals → 30/30 · NC5 windscreen→carpaint → respray Δ 5.5→40 ·
NC6 +3.000 mm → 3.000030 · NC7 8% body deleted → receded 17, **lost 0** ·
NC8 flat paint → detected · NC9 contiguous 150 mm roof hole → receded 4, lost 0, fires
on exactly the 3 roof-viewing directions · NC10 empty-but-named node → caught (a name
check says 20/20) · NC11 two names on one mesh → caught (name check says 20/20) ·
NC12a/b/c deliberate validator errors → 2/1/1 errors while the good file stays 0 ·
2 natural controls.

## STILL NOT PROVEN TO FAIL — ONE ITEM, and it is a finding not a gap
The hole test's LOST class never fires on this car: NC7 (8% scattered) and NC9
(contiguous 150 mm roof disc) both gave lost=0. It fires on a synthetic icosphere
(72/144 rays). The cabin stops every ray — so a hole test asking only "did the ray hit
something" can never fire here. Ray spacing is ~97 mm at 32x32; use 64x64 for holes
below ~150 mm.

## ALSO VERIFIED RATHER THAN QUOTED
glass gate "no vertex moved, no face deleted" TRUE (985,227 faces unchanged; max
centroid move 0.0135 um vs a 0.238 um float32 ULP) — but referenced verts rise +2,740
because a repartition splits vertices at node boundaries: the files share a SURFACE,
not a vertex array. Cabin gate's −3,544 / −149,302 face deltas: both exact.
Cabin's 28 components are 0% coincident with car_rebound = provably constructed.

## SIX OF MY OWN ERRORS ARE RECORDED IN THE REPORT
wrong speck denominator · glazing-contaminated zone + reversed band names ·
empty-by-construction panel mask · linear-vs-sRGB matID mask · a 1 nm tolerance on
float32 data · one use of `pgrep -f` (a read, not a wait — still should not have been used).

## NEXT WHEN THE MERGED CAR LANDS
`SRC_GLB=src/car_rebound.glb python3 verify_merged.py <merged.glb> meta/merged`
then `run_respray.py`, `run_throughglass.py`, `run_specks.py`, and a hole test against
`src/car_merged.glb`. Fill the "merged" column; check A1–A20.
