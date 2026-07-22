#!/usr/bin/env bash
# Premium material-split for a raw TRELLIS car GLB:
#   render 15 views -> Grounded-SAM masks (if GSAM_EP set, else classical HSV)
#   -> occlusion-aware back-project + geometry-fused vote -> recolourable
#   body/glass/trim GLB (interior kept neutral behind see-through glass).
# Usage: GSAM_EP=<id> RUNPOD_KEY=<key> segment.sh raw.glb out.glb [paint_hex]
set -e
D="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RAW="$1"; OUT="$2"; HEX="${3:-}"
WORK="$(mktemp -d)"
blender -b -P "$D/render_views.py"     -- "$RAW"  "$WORK" >/dev/null 2>&1
python3      "$D/masks_and_vote.py"       "$WORK"
blender -b -P "$D/assign_materials.py" -- "$WORK" "$OUT" $HEX 2>&1 | grep -E "STEPB_DONE" || true
rm -rf "$WORK"
echo "SEGMENT_DONE -> $OUT"
