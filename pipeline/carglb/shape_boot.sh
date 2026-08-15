#!/usr/bin/env bash
# car-glb SHAPE + STRUCTURE stage — one pod boot, two generator runs.
#   1. Hi3DGen on the f34 view      -> shape.glb  (EXPERIMENT WINNER 2026-08-15:
#      crease_density 145 vs Hunyuan 37; real window openings, shut lines)
#   2. PartCrafter num_parts=16     -> parts.glb  (the canopy/wheel labels)
# Every pin below was PAID FOR: xformers from bare pypi drags in a new torch
# ('torchvision::nms does not exist'); latest diffusers registers a
# flash-attn-3 op torch 2.4 cannot parse ('Parameter q has unsupported type').
# Env: SB_KEY, HF_TOKEN, HF_HOME, CARGLB_JOB (staging subfolder).
set -x
export DEBIAN_FRONTEND=noninteractive PIP_ROOT_USER_ACTION=ignore
export SPCONV_ALGO=native ATTN_BACKEND=xformers SPARSE_ATTN_BACKEND=xformers
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
# critical uploads must SAY whether they landed — a swallowed 400 on parts.glb
# cost a full attempt (the bucket has a per-file size cap; big files bounce)
put_c() { C=$( set +x; curl -s -o /dev/null -w '%{http_code}' -X POST \
  -H "apikey: ${SB_KEY}" -H "Authorization: Bearer ${SB_KEY}" \
  -H "x-upsert: true" -H "Content-Type: application/octet-stream" \
  --data-binary @"$2" "$SB/$PRE/$1" ); echo "PUT $1 ($(stat -c%s "$2")B) -> $C"; }
report() { put shape_log.txt "$LOG"; }
stage() { echo "=== STAGE:$1 ==="; report; }
die()   { echo "=== FAIL:$1 ==="; report; sleep infinity; }

stage boot
nvidia-smi || die NO_GPU
apt-get update -qq && apt-get install -y -qq --no-install-recommends libopengl0 libegl1 libgl1 xvfb libxrender1 libxext6 2>&1 | tail -1

stage clone
cd /workspace
git clone --depth 1 https://github.com/Stable-X/Hi3DGen hi3 || die CLONE_HI3
git clone --depth 1 https://github.com/wgsxm/PartCrafter pc || die CLONE_PC

stage deps
cd /workspace/hi3
pip install -q -r requirements.txt 2>&1 | tail -2
pip install -q spconv-cu121 2>&1 | tail -1
pip install -q xformers==0.0.27.post2 --no-deps 2>&1 | tail -1
pip install -q diffusers==0.31.0 2>&1 | tail -1
python3 -c "import torch, torchvision, xformers, spconv; from torchvision import transforms; from diffusers.models.autoencoders import autoencoder_kl; assert torch.cuda.is_available(); print('STACK_OK', torch.__version__, torchvision.__version__)" || die STACK
report

stage photos
curl -fsSL "$SB/public/$PRE/f34.png" -o /workspace/f34.png || die PHOTO

stage shape
# idempotent resume: if a previous run already uploaded the shape, skip the
# whole Hi3DGen pass (a PartCrafter failure should not re-bill the shape)
if curl -fsSL "$SB/public/$PRE/shape.glb" -o /workspace/results/shape.glb 2>/dev/null && [ -s /workspace/results/shape.glb ]; then
  echo "SHAPE_RESUMED from bucket"
else
cd /workspace/hi3
timeout 3000 python3 - <<'PY' || die SHAPE
import os, sys
os.environ['SPCONV_ALGO'] = 'native'
sys.path.insert(0, '/workspace/hi3')
import torch
from PIL import Image
from huggingface_hub import snapshot_download
os.makedirs('weights', exist_ok=True)
for mid in ("Stable-X/trellis-normal-v0-1", "Stable-X/yoso-normal-v1-8-1", "ZhengPeng7/BiRefNet"):
    p = os.path.join('weights', mid.split('/')[-1])
    if not os.path.exists(p):
        snapshot_download(repo_id=mid, local_dir=p, force_download=False)
from hi3dgen.pipelines import Hi3DGenPipeline
pipe = Hi3DGenPipeline.from_pretrained("weights/trellis-normal-v0-1")
pipe.cuda()
normal_predictor = torch.hub.load("hugoycj/StableNormal", "StableNormal_turbo",
                                  trust_repo=True, yoso_version='yoso-normal-v1-8-1',
                                  local_cache_dir='./weights')
img = Image.open('/workspace/f34.png')
img = pipe.preprocess_image(img, resolution=1024)
normal = normal_predictor(img, resolution=768, match_input_resolution=True, data_type='object')
out = pipe.run(normal, seed=1, formats=["mesh"], preprocess_image=False,
               sparse_structure_sampler_params={"steps": 50, "cfg_strength": 3},
               slat_sampler_params={"steps": 6, "cfg_strength": 3})
mesh = out['mesh'][0].to_trimesh(transform_pose=True)
mesh.export('/workspace/results/shape.glb')
print('SHAPE_OK', len(mesh.vertices))
PY
put shape.glb /workspace/results/shape.glb
fi
report

stage parts
cd /workspace/pc
grep -viE '^(torch|torchvision)([=<>]|$)' settings/requirements.txt > /tmp/rpc.txt
pip install -q -r /tmp/rpc.txt 2>&1 | tail -2
# PartCrafter's requirements may float diffusers again — re-pin and re-assert
pip install -q diffusers==0.31.0 numpy==1.26.4 2>&1 | tail -1
# torch_cluster is imported by the VAE but absent from PartCrafter's own
# requirements — full static import scan found it as the ONLY gap. PyG wheel
# index, matching the image's torch (same pattern as P3-SAM's torch-scatter).
pip install -q torch-cluster -f https://data.pyg.org/whl/torch-2.4.0+cu124.html 2>&1 | tail -1
# assert the EXACT import chain the inference script runs, not a proxy
python3 -c "import sys; sys.path.insert(0,'/workspace/pc'); from src.pipelines.pipeline_partcrafter import PartCrafterPipeline; import torch; assert torch.cuda.is_available(); print('PC_STACK_OK')" || die PC_STACK
# PYTHONPATH: the script imports 'src.*' relative to the REPO ROOT — the
# exact trap CLAUDE.md recorded from the first PartCrafter deployment
# xvfb: the script's render_utils imports pyrender -> pyglet -> X11 at module
# level — the FOURTH trap from CLAUDE.md's original PartCrafter deployment list
timeout 2400 env PYTHONPATH=/workspace/pc xvfb-run -a python3 scripts/inference_partcrafter.py \
  --image_path /workspace/f34.png \
  --num_parts 16 --output_dir /workspace/results/pc --tag job --seed 0 || die PARTS
[ -s /workspace/results/pc/job/object.glb ] || die PARTS_NO_OBJECT
put_c parts.glb /workspace/results/pc/job/object.glb
# fallback for the size cap: each part individually (small) + a count marker
N=0
for f in /workspace/results/pc/job/part_*.glb; do
  [ -s "$f" ] || continue
  put_c "$(basename "$f")" "$f"
  N=$((N+1))
done
echo "$N" > /workspace/results/nparts.txt
put_c nparts.txt /workspace/results/nparts.txt
report

stage verify
[ -s /workspace/results/shape.glb ] || die MISSING_SHAPE
[ -s /workspace/results/pc/job/object.glb ] || die MISSING_PARTS
echo "=== SHAPE_ALL_OK ==="
report
sleep infinity
