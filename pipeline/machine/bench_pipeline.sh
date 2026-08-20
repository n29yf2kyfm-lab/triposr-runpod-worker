#!/usr/bin/env bash
# bench_pipeline.sh — put EVERY generator's output for one photo through the
# SAME studio pipeline and the SAME audit, so "which machine is best" is
# answered on finished cars rather than on raw output or a vendor's viewer.
#
# WHY THIS SHAPE. Raw generator output is not comparable to a shipped car.
# Measured tonight on the live catalogue: raw Pixal is ONE material with no
# glazing at all (n_materials=1, verdict opaque) and would be an automatic
# scrap under the owner's ruling, while the SAME mesh through the chain comes
# back "clear (proven)" with a real glass material at alpha 0.353. A comparison
# of raw meshes therefore measures the wrong thing — it ranks generators on a
# property the pipeline replaces. Every candidate gets the full chain.
#
# It also fixes the comparison's biggest confound: crease density divides by
# the bounding-box diagonal, so a normalised mesh (diag ~1.3) and a
# metre-scaled one (diag 4.5) are not on the same footing. canon --spec puts
# every car at the real vehicle's dimensions first, so the numbers compare.
#
# RESUMABLE ON PURPOSE. The container has rolled back mid-run twice in one
# session and each rollback cost a ~20 minute chain. Every stage skips when its
# output already exists and every finished car is pushed to the bucket
# immediately, so a reset costs one car and not the wave.
#
# Run: bench_pipeline.sh <raw_glb_dir> <work_dir> <spec.json>
#   raw_glb_dir holds <machine>.glb, one per generator.
set -u
RAW="${1:?raw glb dir}"; WORK="${2:?work dir}"; SPEC="${3:?spec json}"
R=/home/user/triposr-runpod-worker
SB="https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object"
PRE="${BENCH_PRE:-car-meshes/bench}"
mkdir -p "$WORK"

# CREDENTIALS ARE LOADED HERE, not left to the caller. A relaunch that forgot
# to source the env file died one line in and the failure was indistinguishable
# from a healthy start — it logged its count and exited (CLAUDE.md).
set -a; . /root/.alam3d_env; set +a
: "${SB_KEY:?SB_KEY missing after sourcing /root/.alam3d_env}"

upload() { # Supabase storage needs BOTH headers; Authorization alone returns
           # 403 "Invalid Compact JWS", which reads exactly like an expired key
  curl -s -o /dev/null -w "%{http_code}" -X POST \
    -H "apikey: ${SB_KEY}" -H "Authorization: Bearer ${SB_KEY}" \
    -H "x-upsert: true" -H "Content-Type: application/octet-stream" \
    --data-binary @"$2" "$SB/$PRE/$1"; echo " <- $1"; }

for g in "$RAW"/*.glb; do
  M=$(basename "$g" .glb)
  W="$WORK/$M"; mkdir -p "$W"
  echo "=================== $M ==================="

  if [ ! -f "$W/canon.glb" ]; then
    python3 "$R/pipeline/machine/canon.py" "$g" "$W/canon.glb" --spec "$SPEC" \
      > "$W/canon.log" 2>&1 || { echo "CANON FAILED $M"; tail -3 "$W/canon.log"; continue; }
  fi
  grep -E "scaled to spec|canonical extents" "$W/canon.log" | tail -2

  if [ ! -f "$W/car_labels_r.npy" ]; then
    python3 "$R/pipeline/machine/machine.py" seg --canon "$W/canon.glb" \
      --work "$W" > "$W/seg.log" 2>&1 || { echo "SEG FAILED $M"; tail -5 "$W/seg.log"; continue; }
  fi
  if [ ! -f "$W/car_final.glb" ]; then
    python3 "$R/pipeline/machine/machine.py" finish --canon "$W/canon.glb" \
      --work "$W" --tag "$M" > "$W/finish.log" 2>&1 || { echo "FINISH FAILED $M"; tail -5 "$W/finish.log"; continue; }
  fi
  grep -E "GLASS BAND GATE|share:" "$W/finish.log" | tail -2

  upload "${M}_final.glb" "$W/car_final.glb"

  if [ ! -f "$W/views/a045.png" ]; then
    blender -b --python "$R/pipeline/machine/eyeball_views.py" -- \
      "$W/car_final.glb" "$W/views" > "$W/render.log" 2>&1 \
      || echo "RENDER FAILED $M"
  fi
  python3 "$R/pipeline/trellis/crease_density.py" "$W/car_final.glb" 2>/dev/null | tail -1
  echo "DONE $M"
done
echo "BENCH_PIPELINE_COMPLETE"
