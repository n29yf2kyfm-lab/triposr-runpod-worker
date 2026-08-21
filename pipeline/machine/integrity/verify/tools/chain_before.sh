#!/usr/bin/env bash
# Baseline render chain.  Each stage stamps its own exit code and the chain
# writes a DONE marker; terminal state is read from those artefacts, never from
# pgrep (CLAUDE.md: `pgrep -f` matches the harness wrapper and a wait loop can
# never exit).
V=/tmp/claude-0/-home-user-triposr-runpod-worker/34795087-6986-5aae-b59f-cce8aae2f506/scratchpad/integrity/verify
SRC="$V/../SOURCE_LOCKED/GOLF_ALL_GATES_SOURCE.glb"
R="$V/renders"
B="blender -b --factory-startup --python $V/tools/rig.py --"
cd "$V" || exit 1
rm -f "$R/CHAIN_BEFORE.done"

run () {  # run <tag> <extra args...>
  tag="$1"; shift
  mkdir -p "$R/$tag"
  $B --glb "$SRC" --out "$R/$tag" --label "BEFORE_$tag" "$@" \
      > "$R/$tag.log" 2>&1
  echo "STAGE_${tag}_EXIT=$?" >> "$R/CHAIN_BEFORE.stamps"
}

: > "$R/CHAIN_BEFORE.stamps"

# 1. shipped materials, same eight cameras -- the Stage 7 concealment control
run before_original --mats original --views canon --res 1100x825 --samples 32

# 2. face orientation: front faces blue, back faces red
run before_faceorient --mats faceorient --views canon --res 1100x825 --samples 8 --nomask

# 3. backface culling ON, same neutral materials as the baseline sheet
run before_cullon --mats neutral --views canon --res 1100x825 --samples 32 --cull --nomask

# 4. material-ID sheet
run before_matid --mats matid --views canon --res 1100x825 --samples 8 --nomask

# 5. wireframe
run before_wire --mats wire --views canon --res 1100x825 --samples 12 --nomask

# 6. world-space normals
run before_normal --mats normal --views canon --res 1100x825 --samples 8 --nomask

# 7. neutral clay
run before_clay --mats clay --views canon --res 1100x825 --samples 24 --nomask

# 8. orthographic elevations
run before_ortho --mats neutral --views ortho --res 1100x825 --samples 24

# 9. isolation proofs
run before_iso_wheels --mats neutral --views canon --res 1000x750 --samples 24 --isolate tyre,rim
run before_iso_glass  --mats neutral --views canon --res 1000x750 --samples 24 --isolate glass
run before_iso_int    --mats neutral --views canon --res 1000x750 --samples 24 --isolate interior

# 10. RENDER-BASED negative controls: C4 has one primitive with reversed
#     winding.  The face-orientation sheet must go red there and the
#     culling-ON sheet must show a hole.  Without these two, C4 is only
#     proven invisible to counts, which proves nothing.
mkdir -p "$R/ctrl_C4_faceorient" "$R/ctrl_C4_cullon"
$B --glb "$V/ctrl/_keep_C4.glb" --out "$R/ctrl_C4_faceorient" --label CTRL_C4_FACEORIENT \
   --mats faceorient --views canon --res 1100x825 --samples 8 --nomask \
   > "$R/ctrl_C4_faceorient.log" 2>&1
echo "STAGE_ctrlC4_faceorient_EXIT=$?" >> "$R/CHAIN_BEFORE.stamps"
$B --glb "$V/ctrl/_keep_C4.glb" --out "$R/ctrl_C4_cullon" --label CTRL_C4_CULLON \
   --mats neutral --views canon --res 1100x825 --samples 24 --cull --nomask \
   > "$R/ctrl_C4_cullon.log" 2>&1
echo "STAGE_ctrlC4_cullon_EXIT=$?" >> "$R/CHAIN_BEFORE.stamps"

echo "CHAIN_BEFORE_COMPLETE $(date -u +%H:%M:%S)" > "$R/CHAIN_BEFORE.done"
cat "$R/CHAIN_BEFORE.stamps" >> "$R/CHAIN_BEFORE.done"
