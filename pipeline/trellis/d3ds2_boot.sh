#!/usr/bin/env bash
# Direct3D-S2 (DreamTech, MIT, NeurIPS 2025) — leg C of the sharpness experiment.
#
# THE QUESTION: every generator this project has measured works at 512-1024^3 and the
# owner's ruling records that a shut line (2-4mm) is smaller than the grid the model
# draws on. Direct3D-S2 is NATIVE 1024^3 with Spatial Sparse Attention — architecturally
# unlike TRELLIS.2 / PartCrafter / Hunyuan3D-2 / Hi3DGen / SF3D / Pixal3D, all already
# measured. So: can a different 1024^3 GENERATOR produce sharpness from scratch?
#
# PRE-REGISTERED GATE (written before this script was run, in the scratchpad CHECKPOINT
# and unchanged since): crease/diag >= 216.6 (80% of the input's measured 270.7) AND a
# visible door shut line at the locked `door` camera. crease_density is EVIDENCE, never
# a verdict — a melted blob once scored a "3x gain". The RENDER is the arbiter.
#
# DEPENDENCY FACTS ESTABLISHED BY READING THE CODE LOCALLY, not by trial on a rented GPU:
#   * flash_attn is MANDATORY and UNCONDITIONAL — `from flash_attn import
#     flash_attn_varlen_func` at import time in the SSA module, no try/except. It goes
#     in from a PREBUILT WHEEL; a source build is 30+ minutes.
#   * torchsparse is the backend the CHECKPOINTS WERE TRAINED WITH. conv_spconv.py
#     exists but binds weights as spconv module parameters rather than the functional
#     the torchsparse path uses, so the spconv route risks a silent layout/key
#     mismatch. Build torchsparse; it needs libsparsehash-dev (from their Dockerfile).
#   * vox2seq is NOT needed. It is imported lazily inside serialized_attn, and the VAE
#     defaults to attn_mode="swin" -> the "windowed" branch. Verified in base.py.
#   * udf_ext IS needed (third_party/voxelize, a CUDA extension) — mesh2index is on the
#     main path via latent_index.
#   * BiRefNet is NEVER constructed when the input image is RGBA — preprocess() checks
#     image.mode first. So an RGBA cutout bypasses background removal entirely. This is
#     unlike Pixal3D, which built RMBG eagerly in three places and had to be patched.
#
# THE FUSE IS THE POINT. The operator container running this has restarted twice today
# and killed one predecessor outright. An in-pod fuse is the ONLY ceiling that survives
# the operator's death, and CLAUDE.md records that the RunPod-INJECTED pod key could not
# delete its own pod — so this one uses the account key and tries runpodctl as well.
set -x
export DEBIAN_FRONTEND=noninteractive
export PYTHONUNBUFFERED=1
LOG=/workspace/boot.log
mkdir -p /workspace
exec > >(tee -a "$LOG") 2>&1

SB="https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object"
PRE="${D3D_PRE:-car-meshes/staging/direct3d}"
MAXSEC="${D3D_MAXSEC:-3000}"

report() { ( set +x
  curl -s -X POST -H "apikey: ${SB_KEY}" -H "Authorization: Bearer ${SB_KEY}" \
       -H "x-upsert: true" -H "Content-Type: text/plain" \
       --data-binary @"$LOG" "$SB/$PRE/log.txt" >/dev/null 2>&1 ) || true; }
sb_file() { ( set +x
  curl -s -o /tmp/put.out -w "%{http_code}" -X POST \
       -H "apikey: ${SB_KEY}" -H "Authorization: Bearer ${SB_KEY}" \
       -H "x-upsert: true" -H "Content-Type: application/octet-stream" \
       --data-binary @"$2" "$SB/$PRE/$1" ) || true; echo " <- upload $1"; }

selfdestruct() { ( set +x
  echo "=== SELF_DESTRUCT firing for pod ${RUNPOD_POD_ID} ==="
  report
  curl -s -X DELETE -H "Authorization: Bearer ${RUNPOD_API_KEY}" \
       "https://rest.runpod.io/v1/pods/${RUNPOD_POD_ID}" || true
  sleep 10
  runpodctl remove pod "${RUNPOD_POD_ID}" || true
  sleep 20
  # Last resort: if the pod somehow survives, stop burning GPU.
  pkill -9 -f python3 || true ) ; }

# HARD CEILING, armed before anything can fail. Never let this exceed the budget.
( sleep "$MAXSEC"; echo "=== TIMED_OUT after ${MAXSEC}s ==="; selfdestruct ) &
FUSE_PID=$!
echo "fuse armed pid=$FUSE_PID ceiling=${MAXSEC}s"

stage() { echo "=== STAGE:$1 ==="; report; }
die()   { echo "=== FAIL:$1 ==="; report; sleep 60; selfdestruct; sleep infinity; }

stage boot
nvidia-smi || die NO_GPU
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
which nvcc && nvcc --version | tail -2 || die NO_NVCC
df -h /workspace | tail -1
python3 -c "import torch;print('image torch',torch.__version__,torch.version.cuda)" || die TORCH_BROKEN

stage gate_check
# Cheapest possible failure first: prove the weights are pullable before paying for
# a 10-minute dependency build.
GC=$(curl -sL -o /dev/null -w "%{http_code}" -H "Authorization: Bearer ${HF_TOKEN}" \
     -r 0-1023 "https://huggingface.co/wushuang98/Direct3D-S2/resolve/main/direct3d-s2-v-1-1/model_sparse_1024.ckpt")
echo "weights preflight -> HTTP $GC"
case "$GC" in 200|206) : ;; *) die GATED_NO_ACCESS ;; esac

stage apt
apt-get update -qq && apt-get install -y -qq libsparsehash-dev libgl1 libglib2.0-0 git \
  || die APT

stage clone
cd /workspace
git clone --depth 1 https://github.com/DreamTechAI/Direct3D-S2.git d3ds2 || die CLONE
cd d3ds2 && ls

stage torch
# Deliberate, asserted torch move: the repo is built for torch 2.5.1 + triton 3.1.0,
# and the image ships 2.4.0 (triton 3.0). cu124 is chosen to MATCH the image's CUDA
# 12.4 toolkit, so nvcc builds the two CUDA extensions against the same runtime.
pip install -q torch==2.5.1 torchvision==0.20.1 --index-url https://download.pytorch.org/whl/cu124 2>&1 | tail -5
python3 -c "
import torch,sys
print('torch',torch.__version__,'cuda',torch.version.cuda,'avail',torch.cuda.is_available())
assert torch.__version__.startswith('2.5.1'), torch.__version__
assert torch.cuda.is_available()
import triton; print('triton',triton.__version__)
" || die TORCH_PIN
export TORCH_PIN=$(python3 -c "import torch;print(torch.__version__)")
export TORCH_CUDA_ARCH_LIST=$(python3 -c "import torch;m,n=torch.cuda.get_device_capability(0);print(f'{m}.{n}')")
export MAX_JOBS=4
echo "building CUDA extensions for sm_${TORCH_CUDA_ARCH_LIST} only (keeps builds minutes, not tens of minutes)"

stage flash_attn
# PREBUILT WHEEL, NEVER SOURCE. Installed BEFORE requirements.txt so that its
# unpinned `flash-attn` line is already satisfied and pip does not start a source build.
FA="https://github.com/Dao-AILab/flash-attention/releases/download/v2.7.4.post1/flash_attn-2.7.4.post1+cu12torch2.5cxx11abiFALSE-cp311-cp311-linux_x86_64.whl"
pip install -q "$FA" 2>&1 | tail -5 || die FLASH_ATTN_WHEEL
python3 -c "from flash_attn import flash_attn_varlen_func; print('flash_attn ok')" || die FLASH_ATTN_IMPORT

stage torchsparse
git clone --depth 1 https://github.com/mit-han-lab/torchsparse /workspace/torchsparse || die TS_CLONE
pip install -q /workspace/torchsparse 2>&1 | tail -15 || die TORCHSPARSE_BUILD
python3 -c "import torchsparse; print('torchsparse', torchsparse.__version__)" || die TORCHSPARSE_IMPORT

stage deps
cd /workspace/d3ds2
pip install -q -r requirements.txt 2>&1 | tail -20 || die REQUIREMENTS
pip install -q -e . 2>&1 | tail -5 || die PIP_E
# TORCH GUARD: requirements.txt must not have moved torch out from under the freshly
# compiled extensions. Assert, repin, re-assert.
TA=$(python3 -c "import torch;print(torch.__version__)")
echo "TORCH_AFTER=$TA (pin=$TORCH_PIN)"
if [ "$TA" != "$TORCH_PIN" ]; then
  echo "requirements MOVED TORCH — repinning"
  pip install -q torch==2.5.1 torchvision==0.20.1 --index-url https://download.pytorch.org/whl/cu124 2>&1 | tail -3
fi
python3 -c "import torch;assert torch.cuda.is_available();print('cuda ok',torch.__version__)" || die TORCH_CLOBBERED
# IMPORT TORCH FIRST. udf_ext is a torch CUDA extension and links against libc10.so,
# which is only on the loader path once torch has been imported. Checking it bare gives
# "ImportError: libc10.so: cannot open shared object file" on a PERFECTLY GOOD BUILD —
# which is exactly what killed run 1 at 39 minutes, with every real dependency in place.
# The library's own call site (direct3d_s2/utils/mesh.py) imports torch first; a
# preflight that does not mirror the real import order is testing something else.
# This is the documented "a safety check that is itself wrong costs exactly as much as
# no safety check" failure, reproduced. Mirror the real import order.
python3 -c "import torch, udf_ext; print('udf_ext ok')" || die UDF_EXT

stage import_check
# Import the REAL module the way the real script does, before spending on weights.
cd /workspace/d3ds2
python3 -c "
import os
os.environ.setdefault('SPARSE_BACKEND','torchsparse')
os.environ.setdefault('ATTN_BACKEND','flash_attn')
from direct3d_s2.pipeline import Direct3DS2Pipeline
print('pipeline import ok')
" || die IMPORT_GRAPH

stage weights
# Pull weights HERE with retries. hf_hub_download resumes from cache, so a mid-transfer
# TCP drop costs seconds instead of the whole run (the SF3D lesson).
python3 - <<'PY' || die WEIGHTS
import os, time
from huggingface_hub import hf_hub_download
repo="wushuang98/Direct3D-S2"; sub="direct3d-s2-v-1-1"
files=["config.yaml","model_dense.ckpt","model_sparse_512.ckpt",
       "model_sparse_1024.ckpt","model_refiner.ckpt","model_refiner_1024.ckpt"]
for fn in files:
    for att in range(1,6):
        try:
            p=hf_hub_download(repo, f"{sub}/{fn}", token=os.environ.get("HF_TOKEN"))
            print("have",fn,os.path.getsize(p)); break
        except Exception as e:
            print(f"attempt {att} {fn}: {type(e).__name__}: {e}")
            if att==5: raise
            time.sleep(5*att)
PY

stage dino
# DINOv2 comes from torch.hub, i.e. GitHub, not HF. Pre-cache it so the first inference
# does not stall on a 1.2GB download mid-run (the recorded Hi3DGen hubconf trap).
python3 -c "
import torch
m=torch.hub.load('facebookresearch/dinov2','dinov2_vitl14_reg',pretrained=True)
print('dinov2 cached', sum(p.numel() for p in m.parameters()))
" || die DINO

stage fetch_inputs
cd /workspace
curl -fsSL "$SB/public/$PRE/batch.json" -o batch.json || die FETCH_MANIFEST
curl -fsSL "$SB/public/$PRE/crease_density.py" -o /workspace/crease_density.py || echo "MEASURE UNAVAILABLE"
for TAG in $(python3 -c "import json;print(' '.join(json.load(open('batch.json'))))"); do
  curl -fsSL "$SB/public/$PRE/in_${TAG}.png" -o "/workspace/in_${TAG}.png" || die FETCH_IMG_$TAG
done
ls -la /workspace/*.png

stage infer
cat > /workspace/run_d3d.py <<'PY'
import os, sys, json, time, traceback
os.environ.setdefault('SPARSE_BACKEND','torchsparse')
os.environ.setdefault('ATTN_BACKEND','flash_attn')
import torch, trimesh
from PIL import Image
from direct3d_s2.pipeline import Direct3DS2Pipeline

tags = json.load(open('/workspace/batch.json'))
pipe = Direct3DS2Pipeline.from_pretrained('wushuang98/Direct3D-S2',
                                          subfolder='direct3d-s2-v-1-1')
pipe.to('cuda:0')
print('PIPELINE_READY', flush=True)

for tag in tags:
    p = f'/workspace/in_{tag}.png'
    im = Image.open(p)
    # Assert the RGBA bypass really is taken: an RGB image would silently pull in
    # BiRefNet and change what the model is conditioned on.
    print(f'{tag}: mode={im.mode} size={im.size}', flush=True)
    assert im.mode == 'RGBA', f'{tag} is {im.mode}, expected RGBA (BiRefNet bypass)'
    t0 = time.time()
    try:
        out = pipe(p, sdf_resolution=1024, remesh=False, remove_interior=True)
        mesh = out['mesh']
        dt = time.time() - t0
        op = f'/workspace/out_{tag}.glb'
        mesh.export(op)
        print(f'DONE {tag} {dt:.1f}s verts={len(mesh.vertices)} faces={len(mesh.faces)} '
              f'-> {op} {os.path.getsize(op)}', flush=True)
        # UPLOAD THE MOMENT IT EXISTS, not in a later stage. Run 1's meshes would have
        # been uploaded only by `collect`, so a fuse firing during a second inference
        # would have destroyed the first car's result too. Upload as it lands.
        import subprocess as _sp
        sb = os.environ.get('SB_HOST', 'https://tfkvthprsntexrcuqpyd.supabase.co') \
             + '/storage/v1/object/' + os.environ.get('D3D_PRE', 'car-meshes/staging/direct3d')
        k = os.environ.get('SB_KEY', '')
        rc = _sp.run(['curl', '-s', '-o', '/dev/null', '-w', '%{http_code}',
                      '-X', 'POST', '-H', f'apikey: {k}', '-H', f'Authorization: Bearer {k}',
                      '-H', 'x-upsert: true', '-H', 'Content-Type: application/octet-stream',
                      '--data-binary', f'@{op}', f'{sb}/out_{tag}.glb'],
                     capture_output=True, text=True)
        print(f'IMMEDIATE_UPLOAD {tag} -> HTTP {rc.stdout}', flush=True)
    except Exception:
        traceback.print_exc()
        print(f'INFER_FAILED {tag}', flush=True)
PY
python3 /workspace/run_d3d.py 2>&1 | tail -60
RC=${PIPESTATUS[0]}
echo "run_d3d rc=$RC"

stage collect
DONE=0
for TAG in $(python3 -c "import json;print(' '.join(json.load(open('/workspace/batch.json'))))"); do
  G="/workspace/out_${TAG}.glb"
  if [ -s "$G" ]; then
    ls -la "$G"; sb_file "out_${TAG}.glb" "$G"; DONE=$((DONE+1))
    if [ -f /workspace/crease_density.py ]; then
      echo "MEASURE $TAG" | tee -a /workspace/crease_all.txt
      python3 /workspace/crease_density.py "$G" 2>&1 | tail -4 | tee -a /workspace/crease_all.txt
    fi
  else
    echo "NO OUTPUT for $TAG (RC=0-but-no-mesh trap)"
  fi
done
[ -f /workspace/crease_all.txt ] && sb_file crease.txt /workspace/crease_all.txt
sb_file boot.log "$LOG"
echo "COMPLETE done=$DONE"
[ "$DONE" -gt 0 ] || die NO_MESH_PRODUCED
echo "=== D3DS2_OK ==="
report
# Success path self-destructs too: results are already in the bucket, so there is
# nothing left worth paying for.
selfdestruct
sleep infinity
