#!/usr/bin/env bash
# Stage 9 render chain for a repaired GLB.   usage: chain_after.sh <glb> <tag>
# Mirrors chain_before.sh exactly -- same cameras, same lens, same lighting,
# same samples -- so before/after tiles are comparable pixel for pixel.
# Stamps each stage's exit code and writes a DONE marker; terminal state is read
# from those artefacts, never from pgrep.
V=/tmp/claude-0/-home-user-triposr-runpod-worker/34795087-6986-5aae-b59f-cce8aae2f506/scratchpad/integrity/verify
GLB="$1"; TAG="$2"
R="$V/renders"
B="blender -b --factory-startup --python $V/tools/rig.py --"
cd "$V" || exit 1
rm -f "$R/CHAIN_${TAG}.done"; : > "$R/CHAIN_${TAG}.stamps"

run () {
  sub="$1"; shift
  mkdir -p "$R/${TAG}_${sub}"
  $B --glb "$GLB" --out "$R/${TAG}_${sub}" --label "${TAG}_${sub}" "$@" \
      > "$R/${TAG}_${sub}.log" 2>&1
  echo "STAGE_${sub}_EXIT=$?" >> "$R/CHAIN_${TAG}.stamps"
}

run neutral    --mats neutral    --views canon --res 1100x825 --samples 32
run faceorient --mats faceorient --views canon --res 1100x825 --samples 8  --nomask
run original   --mats original   --views canon --res 1100x825 --samples 32
run cullon     --mats neutral    --views canon --res 1100x825 --samples 32 --cull --nomask
run matid      --mats matid      --views canon --res 1100x825 --samples 8  --nomask
run wire       --mats wire       --views canon --res 1100x825 --samples 12 --nomask
run normal     --mats normal     --views canon --res 1100x825 --samples 8  --nomask
run clay       --mats clay       --views canon --res 1100x825 --samples 24 --nomask
run ortho      --mats neutral    --views ortho --res 1100x825 --samples 24
run iso_wheels --mats neutral    --views canon --res 1000x750 --samples 24 --isolate tyre,rim
run iso_glass  --mats neutral    --views canon --res 1000x750 --samples 24 --isolate glass
run iso_int    --mats neutral    --views canon --res 1000x750 --samples 24 --isolate interior
run perview    --mats neutral    --views canon --res 1100x825 --samples 24 --fit per_view

echo "CHAIN_${TAG}_COMPLETE $(date -u +%H:%M:%S)" > "$R/CHAIN_${TAG}.done"
cat "$R/CHAIN_${TAG}.stamps" >> "$R/CHAIN_${TAG}.done"
