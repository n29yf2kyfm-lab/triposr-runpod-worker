#!/usr/bin/env bash
# PartCrafter — part-native image->3D, 16 parts. Pod bootstrap.
#
# WHY THIS IS IN THE REPO NOW. The only working version lived in the BUCKET
# (partcrafter_run/bootstrap16b.sh) and could not be re-run: it reports through
# a SIGNED UPLOAD URL, and Supabase signed upload URLs are ONE-TIME (measured:
# first PUT 200, every later PUT 400) as well as time-limited — that token
# expired long ago. A run recipe that can only be used once is not a recipe.
# This version uses the service key, so it is re-runnable.
#
# num_parts=16 IS DELIBERATE AND MEASURED. At 10 parts the greenhouse fuses
# into the body shell (one part held 67.9% of the car); at 16 the canopy comes
# out as its own closed mesh. Do not lower it.
#
# --rmbg IS KEPT AND THE INPUT IS OPAQUE. The recorded good runs fed PartCrafter
# an opaque render with --rmbg on; our source is an RGBA cutout, so the caller
# composites it onto white first rather than changing two variables at once.
#
# PARTS ARE UPLOADED AS SEPARATE FILES, not only as a tarball. The whole point
# of this stage is per-part geometry for label transfer; a tgz forces the next
# stage to unpack a blob and guess at names.
set -x
export DEBIAN_FRONTEND=noninteractive
LOG=/workspace/boot.log
mkdir -p /workspace
exec > >(tee -a "$LOG") 2>&1

SB="https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object"
PRE="${PC_PRE:-car-meshes/staging/hybrid_van2}"
IN_NAME="${PC_IN:-van_pc_rgb.png}"
NPARTS="${PC_PARTS:-16}"
LOGKEY="${PC_LOGKEY:-pc_log.txt}"
RUN_ID="${RUNPOD_POD_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"

report() { ( set +x
  for _k in "$1" "$(echo "$1" | sed 's/\.txt$//')_${RUN_ID}.txt"; do
    curl -s -X POST -H "apikey: ${SB_KEY}" -H "Authorization: Bearer ${SB_KEY}" \
         -H "x-upsert: true" -H "Content-Type: text/plain" \
         --data-binary @"$LOG" "$SB/$PRE/$_k" >/dev/null 2>&1
  done ) || true; }
sb_file() { ( set +x
  _code=$(curl -s -o /tmp/put.out -w "%{http_code}" -X POST \
       -H "apikey: ${SB_KEY}" -H "Authorization: Bearer ${SB_KEY}" \
       -H "x-upsert: true" -H "Content-Type: application/octet-stream" \
       --data-binary @"$2" "$SB/$PRE/$1")
  case "$_code" in
    2*) echo "upload $1 OK ($_code, $(stat -c%s "$2" 2>/dev/null) bytes)" ;;
    *)  echo "UPLOAD_FAILED $1 http=$_code body=$(head -c 200 /tmp/put.out)"; exit 1 ;;
  esac ) ; }
stage() { echo "=== STAGE:$1 ==="; report "$LOGKEY"; }
FUSE_MIN="${PC_FUSE_MIN:-45}"
fuse() {
  echo "=== FUSE: holding ${FUSE_MIN}m then self-terminating ==="
  sleep $(( FUSE_MIN * 60 ))
  ( set +x; curl -s -X DELETE -H "Authorization: Bearer ${RUNPOD_API_KEY}" \
      "https://rest.runpod.io/v1/pods/${RUNPOD_POD_ID}" >/dev/null 2>&1 ) || true
  echo "=== FUSE: delete requested; the launcher's external 404 check is the real guard ==="
  sleep 600
}
die() { echo "=== FAIL:$1 ==="; report "$LOGKEY"; fuse; }

# pip that does NOT swallow its own error (no pipefail => `| tail` returns 0,
# and the tail throws away the reason — paid for on the Step1X texture run).
pipq() { local _l="${2:-/workspace/pip.log}"; pip install $1 > "$_l" 2>&1; local _r=$?
         [ "$_r" -ne 0 ] && { echo "PIP FAILED (rc=$_r): $1"; tail -30 "$_l"; }; return $_r; }

stage boot
nvidia-smi || die NO_GPU
python3 -c "import torch;print('torch',torch.__version__,torch.cuda.get_device_name(0))" || die TORCH_BROKEN
df -h /workspace | tail -1

stage clone
cd /workspace
git clone --depth 1 https://github.com/wgsxm/PartCrafter.git || die CLONE
cd PartCrafter

stage deps
# X CLIENT LIBRARIES, not just xvfb. Run 2 died at inference with
#   AttributeError: 'NoneType' object has no attribute 'XRenderFindVisualFormat'
# which is pyglet failing to dlopen libXrender. CLAUDE.md records "pyrender
# importing pyglet/X11 and needing xvfb-run" and I read that as "xvfb is
# enough" -- it is not. xvfb provides a DISPLAY; it does not provide the client
# .so files pyglet loads. scripts/inference_partcrafter.py imports
# src.utils.render_utils -> pyrender AT MODULE SCOPE (line 17), so the import
# must resolve even though we never render a preview.
apt-get update -qq && apt-get install -y -qq \
  xvfb libgl1 libglu1-mesa libglib2.0-0 \
  libxrender1 libxext6 libsm6 libice6 libx11-6 libxi6 \
  libxcursor1 libxinerama1 libxrandr2 2>&1 | tail -2
pipq "torch==2.5.1 torchvision==0.20.1 --index-url https://download.pytorch.org/whl/cu124" /workspace/pip_torch.log || die TORCH_PIN
python3 -c "import torch;assert torch.__version__.startswith('2.5.1')" || die TORCH_PIN_ASSERT
pipq "torch-cluster -f https://data.pyg.org/whl/torch-2.5.1+cu124.html" /workspace/pip_cluster.log || echo "torch_cluster wheel unavailable (lazy)"
# THE REQUIREMENTS FILE IS AT settings/requirements.txt, NOT requirements.txt.
# Run 1 died here: I had the working script in front of me and retyped the path
# wrong, and CLAUDE.md already records "settings/requirements.txt path" as one
# of the four original PartCrafter bootstrap failures. Paid twice. Assert the
# paths EXIST before handing them to pip, so a typo dies by name instead of as
# a pip error 6 minutes into a rented pod.
for f in settings/requirements.txt scripts/inference_partcrafter.py src; do
  [ -e "$f" ] || { echo "MISSING EXPECTED PATH: $f"; ls -la; die REPO_LAYOUT_CHANGED; }
done
echo "repo layout verified: settings/requirements.txt, scripts/, src/"
pipq "huggingface_hub -r settings/requirements.txt" /workspace/pip_reqs.log || die REQS

# ASSERT THE EAGER IMPORT CHAIN BEFORE SPENDING INFERENCE MINUTES. Run 2 got
# all the way to STAGE:infer and died on a missing X .so -- a deps problem
# surfacing as an inference failure. Import exactly what the script imports at
# module scope, under xvfb so the conditions match, and fail in deps instead.
xvfb-run -a -s "-screen 0 1280x1024x24" python3 -c "
import pyrender, pyglet, torch
from src.utils.render_utils import render_views_around_mesh
from src.pipelines.pipeline_partcrafter import PartCrafterPipeline
from src.models.briarmbg import BriaRMBG
print('eager import chain OK (pyrender/pyglet/X libs resolve)')
" || die EAGER_IMPORTS

stage fetch_input
curl -fsSL "$SB/public/$PRE/$IN_NAME" -o /workspace/car.png || die FETCH_INPUT
python3 -c "
from PIL import Image; im=Image.open('/workspace/car.png'); print('input',im.size,im.mode)
assert im.size[0]>=512, 'input too small'" || die INPUT_BAD

stage infer
cd /workspace/PartCrafter
# xvfb: the pipeline imports pyrender, which pulls pyglet/X11 even headless.
PYTHONPATH=/workspace/PartCrafter timeout 2400 xvfb-run -a -s "-screen 0 1280x1024x24" \
  python3 scripts/inference_partcrafter.py \
    --image_path /workspace/car.png --num_parts "$NPARTS" --tag van16 --rmbg \
    > /workspace/inference.log 2>&1
INFER_RC=$?
tail -30 /workspace/inference.log
echo "INFER_RC=$INFER_RC"
sb_file "pc_inference.log" /workspace/inference.log || true
[ "$INFER_RC" -eq 0 ] || die INFER

stage collect
# The script writes results/<tag>/... ; find the parts wherever they land
mapfile -t GLBS < <(find /workspace/PartCrafter/results -name '*.glb' | sort)
echo "found ${#GLBS[@]} glb files"
[ "${#GLBS[@]}" -ge 2 ] || die NO_PARTS      # 1 file = a fused blob, not parts

stage upload
i=0
for g in "${GLBS[@]}"; do
  base=$(basename "$g" .glb)
  sb_file "parts/pc_${base}.glb" "$g" || die UPLOAD_PART
  i=$((i+1))
done
echo "uploaded $i part files under $PRE/parts/"

stage measure
python3 - <<'PY' 2>&1 | tail -25
import glob, trimesh, numpy as np
fs = sorted(glob.glob('/workspace/PartCrafter/results/**/*.glb', recursive=True))
tot = 0; rows = []
for f in fs:
    try:
        m = trimesh.load(f, force='mesh', process=False)
        rows.append((f.split('/')[-1], len(m.faces), float(m.area)))
        tot += float(m.area)
    except Exception as e:
        rows.append((f.split('/')[-1], -1, 0.0))
for n, fc, a in rows:
    print(f"  {n:34s} faces={fc:>8} area={a:8.4f} share={(a/tot*100 if tot else 0):5.1f}%")
print(f"  parts={len(rows)} total_area={tot:.4f}")
PY

echo "=== PARTCRAFTER_OK ==="
report "$LOGKEY"
fuse
