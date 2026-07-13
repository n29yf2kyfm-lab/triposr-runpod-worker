#!/usr/bin/env bash
# optimise.sh — produce web-delivery GLBs from an approved master, without
# breaking object hierarchy or animation. Free tools only (glTF-Transform MIT,
# meshoptimizer MIT). KTX2 step is optional and skipped if no encoder present.
#
# Usage: pipeline/optimise.sh <in_master.glb> <out_dir> [basename]
# Produces:  <base>.draco.glb   (Draco geometry + WebP textures — widest support)
#            <base>.meshopt.glb (Meshopt geometry + WebP — best runtime decode)
# Keeps the input master untouched. Run the validator on outputs afterwards.
set -euo pipefail
IN="${1:?need input GLB}"; OUT="${2:?need output dir}"; BASE="${3:-$(basename "${IN%.*}")}"
mkdir -p "$OUT"
GT="npx --yes @gltf-transform/cli"

echo "== inspect (before) =="
$GT inspect "$IN" | sed -n '1,20p' || true

# 1) lossless housekeeping — safe, preserves names/hierarchy/animation
#    dedup: merge identical accessors/textures | prune: drop unused | resample: tidy anim
$GT dedup "$IN" "$OUT/$BASE.tmp.glb"
$GT prune "$OUT/$BASE.tmp.glb" "$OUT/$BASE.tmp.glb" --keep-leaves true --keep-attributes false
# 2) resize textures to a sane web cap (2K) + WebP (small, universally decoded)
$GT resize "$OUT/$BASE.tmp.glb" "$OUT/$BASE.tmp.glb" --width 2048 --height 2048
$GT webp   "$OUT/$BASE.tmp.glb" "$OUT/$BASE.tmp.glb" --quality 90

# 3a) Draco variant (geometry compression, widest loader support)
$GT draco "$OUT/$BASE.tmp.glb" "$OUT/$BASE.draco.glb"
# 3b) Meshopt variant (quantise + compress; fastest GPU-side decode)
$GT meshopt "$OUT/$BASE.tmp.glb" "$OUT/$BASE.meshopt.glb"
rm -f "$OUT/$BASE.tmp.glb"

echo "== sizes =="
ls -la "$OUT/$BASE.draco.glb" "$OUT/$BASE.meshopt.glb" | awk '{print $5, $9}'
echo "== OPTIONAL KTX2 (skipped unless toktx present) =="
if command -v toktx >/dev/null 2>&1; then
  $GT uastc "$OUT/$BASE.draco.glb" "$OUT/$BASE.draco.ktx2.glb" --level 4 --rdo 4 --zstd 18
  echo "wrote $OUT/$BASE.draco.ktx2.glb"
else
  echo "toktx not installed -> staying on WebP (install KTX-Software to enable KTX2/Basis)"
fi
echo "== DONE. Validate outputs:  node pipeline/validate.js $OUT/$BASE.draco.glb =="
