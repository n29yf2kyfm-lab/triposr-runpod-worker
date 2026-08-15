#!/usr/bin/env bash
# car-glb SHAPE + STRUCTURE stage — one pod boot, two generator runs.
#   1. Hunyuan3D-2mv on the labelled views  -> shape.glb   (the surface)
#   2. PartCrafter num_parts=16 on f34/front -> parts.glb  (the structure:
#      the canopy label is what makes glazing separable downstream)
# Recipe is the PROVEN one (yaris_mv_boot.sh + the PartCrafter runs): timm,
# torch pin + assert, xtrace-off puts, artefact asserts, fail = named stage.
# Env: SB_KEY, HF_TOKEN, HF_HOME, CARGLB_JOB (the staging subfolder).
set -x
export DEBIAN_FRONTEND=noninteractive PIP_ROOT_USER_ACTION=ignore
LOG=/workspace/boot.log
mkdir -p /workspace/results
exec > >(tee -a "$LOG") 2>&1
JOB="${CARGLB_JOB:?CARGLB_JOB not set}"
SB="https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object"
PRE="car-meshes/staging/carglb/$JOB"
put() { ( set +x
  curl -s -X POST -H "apikey: ${SB_KEY}" -H "Authorization: Bearer ${SB_KEY}" \
       -H "x-upsert: true" -H "Content-Type: application/octet-stream" \
       --data-binary @"$2" "$SB/$PRE/$1" >/dev/null 2>&1 ) || true; }
report() { put shape_log.txt "$LOG"; }
stage() { echo "=== STAGE:$1 ==="; report; }
die()   { echo "=== FAIL:$1 ==="; report; sleep infinity; }

stage boot
nvidia-smi || die NO_GPU
apt-get update -qq && apt-get install -y -qq --no-install-recommends libopengl0 libegl1 libgl1 2>&1 | tail -1

stage clone
cd /workspace
git clone --depth 1 https://github.com/Tencent/Hunyuan3D-2.git h2 || die CLONE_H2
git clone --depth 1 https://github.com/wgsxm/PartCrafter.git pc || true

stage deps
cd /workspace/h2
grep -viE '^(torch|torchvision)([=<>]|$)' requirements.txt > /tmp/r2.txt
pip install -q -r /tmp/r2.txt 2>&1 | tail -2
pip install -q -e . 2>&1 | tail -1
pip install -q timm 2>&1 | tail -1
pip install -q torch==2.5.1 torchvision==0.20.1 --index-url https://download.pytorch.org/whl/cu124 2>&1 | tail -1
python3 -c "import torch; assert torch.cuda.is_available(); print('TORCH_OK', torch.__version__)" || die TORCH
python3 -c "import sys; sys.path.insert(0,'/workspace/h2'); from hy3dgen.shapegen import Hunyuan3DDiTFlowMatchingPipeline; print('h2 ok')" || die IMPORT
report

stage photos
ANY=0
for V in front rear left right f34; do
  curl -fsSL "$SB/public/$PRE/$V.png" -o /workspace/$V.png && ANY=1
done
[ "$ANY" = "1" ] || die NO_PHOTOS

stage shape
timeout 3000 python3 - <<'PY' || die SHAPE
import os, sys
sys.path.insert(0, '/workspace/h2')
from PIL import Image
from hy3dgen.shapegen import (Hunyuan3DDiTFlowMatchingPipeline, FloaterRemover,
                              DegenerateFaceRemover, FaceReducer)
from huggingface_hub import list_repo_files
views = {}
mapping = {'front': 'front', 'rear': 'back', 'left': 'left', 'right': 'right'}
for local, key in mapping.items():
    p = f'/workspace/{local}.png'
    if os.path.exists(p):
        views[key] = Image.open(p)
print('views:', sorted(views))
files = list_repo_files('tencent/Hunyuan3D-2mv')
dits = sorted({f.split('/')[0] for f in files if f.split('/')[0].startswith('hunyuan3d-dit')})
pick = next((d for d in dits if 'mv' in d and 'turbo' not in d), dits[0])
pipe = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained('tencent/Hunyuan3D-2mv', subfolder=pick)
mesh = pipe(image=views, num_inference_steps=50, octree_resolution=380,
            num_chunks=20000, output_type='trimesh')[0]
m = FloaterRemover()(mesh); m = DegenerateFaceRemover()(m)
m = FaceReducer()(m, max_facenum=400000)
m.export('/workspace/results/shape.glb')
print('SHAPE_OK', len(m.vertices))
PY
put shape.glb /workspace/results/shape.glb
report

stage parts
# PartCrafter is a QUALITY upgrade, not a hard dependency of this stage —
# downstream refuses to gate without it, so a failure here is loud but the
# shape still uploads for inspection.
timeout 2400 python3 - <<'PY' || echo "PARTS_FAILED (non-fatal here, fatal downstream)"
import os, sys
sys.path.insert(0, '/workspace/pc')
from PIL import Image
img_path = '/workspace/f34.png' if os.path.exists('/workspace/f34.png') else '/workspace/front.png'
# PartCrafter's own inference entry (as proven in the 2026-08-12 runs)
os.chdir('/workspace/pc')
os.system(f"pip install -q -r requirements.txt 2>&1 | tail -1")
r = os.system(f"python3 inference.py --image {img_path} --num_parts 16 --output /workspace/results/parts_dir")
assert r == 0
# find the combined object glb
for root, _, fs in os.walk('/workspace/results/parts_dir'):
    for f in fs:
        if f.endswith('.glb'):
            import shutil; shutil.copy(os.path.join(root, f), '/workspace/results/parts.glb')
print('PARTS_OK')
PY
[ -s /workspace/results/parts.glb ] && put parts.glb /workspace/results/parts.glb
report

stage verify
[ -s /workspace/results/shape.glb ] || die MISSING_SHAPE
echo "=== SHAPE_ALL_OK ==="
report
sleep infinity
