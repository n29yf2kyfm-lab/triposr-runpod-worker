#!/usr/bin/env bash
# Priority chain, corrected classifier.  Ordered so that the comparisons the
# verdict actually rests on land FIRST, because the container has been rolling
# back roughly every 40 minutes and a chain that finishes in dependency order
# is worth more than one that finishes in tidy order.
V=/tmp/claude-0/-home-user-triposr-runpod-worker/34795087-6986-5aae-b59f-cce8aae2f506/scratchpad/integrity/verify
SRC="$V/../SOURCE_LOCKED/GOLF_ALL_GATES_SOURCE.glb"
AFT="$V/after/car_integrity_repaired.glb"
C4="$V/ctrl/_keep_C4.glb"
R="$V/renders"; B="blender -b --factory-startup --python $V/tools/rig.py --"
cd "$V" || exit 1
rm -f "$R/CHAIN_P.done"; : > "$R/CHAIN_P.stamps"
run () { tag="$1"; glb="$2"; shift 2; mkdir -p "$R/$tag"
  $B --glb "$glb" --out "$R/$tag" --label "$tag" "$@" > "$R/$tag.log" 2>&1
  echo "STAGE_${tag}_EXIT=$?" >> "$R/CHAIN_P.stamps"; }

# 1-2 the A/B pair the wheel verdict rests on, both with the corrected classifier
run P_AFTER_neutral  "$AFT" --mats neutral --views canon --res 1100x825 --samples 32
run P_BEFORE_neutral "$SRC" --mats neutral --views canon --res 1100x825 --samples 32
# 3 face orientation after (before already rendered; that shader has no classifier)
run P_AFTER_faceorient "$AFT" --mats faceorient --views canon --res 1100x825 --samples 8 --nomask
# 4-5 RENDER-BASED NEGATIVE CONTROLS: C4 has one primitive with reversed winding.
#     Without these the cull sheet and the faceorient sheet are unproven.
run P_CTRL_C4_faceorient "$C4" --mats faceorient --views canon --res 1100x825 --samples 8 --nomask
run P_CTRL_C4_cullon     "$C4" --mats neutral --views canon --res 1100x825 --samples 24 --cull --nomask
# 6 after culling, to pair with the control
run P_AFTER_cullon "$AFT" --mats neutral --views canon --res 1100x825 --samples 24 --cull --nomask
# 7 orthographic elevations (deliverable)
run P_AFTER_ortho "$AFT" --mats neutral --views ortho --res 1100x825 --samples 24
# 8 per-view fit sheet (the 75-85% occupancy question)
run P_AFTER_perview "$AFT" --mats neutral --views canon --res 1100x825 --samples 24 --fit per_view
# 9-11 isolation proofs
run P_AFTER_iso_wheels "$AFT" --mats neutral --views canon --res 1000x750 --samples 24 --isolate tyre,rim
run P_AFTER_iso_glass  "$AFT" --mats neutral --views canon --res 1000x750 --samples 24 --isolate glass
run P_AFTER_iso_int    "$AFT" --mats neutral --views canon --res 1000x750 --samples 24 --isolate interior
# 12-14 remaining diagnostic sheets
run P_AFTER_matid  "$AFT" --mats matid  --views canon --res 1100x825 --samples 8  --nomask
run P_AFTER_normal "$AFT" --mats normal --views canon --res 1100x825 --samples 8  --nomask
run P_AFTER_wire   "$AFT" --mats wire   --views canon --res 1100x825 --samples 12 --nomask
run P_AFTER_clay   "$AFT" --mats clay   --views canon --res 1100x825 --samples 24 --nomask
run P_AFTER_original "$AFT" --mats original --views canon --res 1100x825 --samples 32
echo "CHAIN_P_COMPLETE $(date -u +%H:%M:%S)" > "$R/CHAIN_P.done"; cat "$R/CHAIN_P.stamps" >> "$R/CHAIN_P.done"
