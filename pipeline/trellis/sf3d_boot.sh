#!/usr/bin/env bash
# Stable Fast 3D (SF3D) — Stability AI's image-to-3D, the last untried open
# family. Run as a straight A/B against Pixal3D on the SAME cutouts.
#
# WHY IT IS WORTH A RUN, stated before the run so it cannot be rationalised
# afterwards. Two capabilities nothing else we have tested ships:
#   * DE-LIGHTING as a designed stage. Pixal's open defect is baked lighting
#     in the texture (sky reflections painted into the glazing), which the
#     production brief forbids in base colour.
#   * per-object material parameters (roughness / metallic) + a UV-unwrapped
#     mesh, i.e. it emits the material split our seg chain has to reconstruct.
#
# PRE-REGISTERED GATE: SF3D generates in UNDER A SECOND against Pixal's ~12
# minutes at 1536, so the prior is that it LOSES on surfacing. It is worth
# keeping only if it beats Pixal on the eye, or if its de-lit texture is
# visibly cleaner on the glazing. crease_density is recorded as evidence,
# never as the verdict (a noisy mesh scores high — the documented trap).
#
# SPAR3D is the successor and the one we actually want (point-cloud stage,
# aimed squarely at the single-view backside failure). Its weights are still
# gated to this account — measured 403 on model.safetensors while SF3D
# returned 206 — so this script takes MODEL as an argument and will run
# SPAR3D unchanged the moment access is granted.
set -x
export DEBIAN_FRONTEND=noninteractive
export PYTHONUNBUFFERED=1
LOG=/workspace/boot.log
mkdir -p /workspace
exec > >(tee -a "$LOG") 2>&1

SB="https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object"
PRE="${SF3D_PRE:-car-meshes/sf3d}"
REPO="${SF3D_REPO:-https://github.com/Stability-AI/stable-fast-3d}"
MODEL="${SF3D_MODEL:-stabilityai/stable-fast-3d}"

report() { ( set +x
  curl -s -X POST -H "apikey: ${SB_KEY}" -H "Authorization: Bearer ${SB_KEY}" \
       -H "x-upsert: true" -H "Content-Type: text/plain" \
       --data-binary @"$LOG" "$SB/$PRE/$1" >/dev/null 2>&1 ) || true; }
sb_file() { ( set +x
  curl -s -o /tmp/put.out -w "%{http_code}" -X POST \
       -H "apikey: ${SB_KEY}" -H "Authorization: Bearer ${SB_KEY}" \
       -H "x-upsert: true" -H "Content-Type: application/octet-stream" \
       --data-binary @"$2" "$SB/$PRE/$1" ) || true; echo " <- upload $1"; }
stage() { echo "=== STAGE:$1 ==="; report "log.txt"; }
die()   { echo "=== FAIL:$1 ==="; report "log.txt"; sleep infinity; }

stage boot
nvidia-smi || die NO_GPU
python3 -c "import torch;print('torch',torch.__version__,torch.version.cuda,torch.cuda.get_device_name(0))" || die TORCH_BROKEN
TORCH_BEFORE=$(python3 -c "import torch;print(torch.__version__)")
which nvcc && nvcc --version || die NO_NVCC   # the custom kernels need it
df -h /workspace | tail -1

stage gate_check
# CHEAPEST POSSIBLE FAILURE, first: prove this account can actually pull the
# weights before paying for a clone, a deps install and two kernel builds.
# Measured 2026-08-19: SPAR3D 403 "not in the authorized list", SF3D 206.
GC=$(curl -sL -o /dev/null -w "%{http_code}" -H "Authorization: Bearer ${HF_TOKEN}" \
     -r 0-1023 "https://huggingface.co/${MODEL}/resolve/main/model.safetensors")
echo "weights preflight ${MODEL} -> HTTP $GC"
case "$GC" in 200|206) : ;; *) die GATED_NO_ACCESS ;; esac

stage clone
cd /workspace
git clone --depth 1 "$REPO" sf3d || die CLONE
cd sf3d
ls -la

stage deps
pip install -q -U setuptools==69.5.1 wheel 2>&1 | tail -3
# TORCH GUARD (documented trap): a requirements.txt that moves torch breaks
# the kernels compiled against it. Install, then ASSERT, then repin.
pip install -q -r requirements.txt 2>&1 | tail -12 || die REQUIREMENTS
TORCH_AFTER=$(python3 -c "import torch;print(torch.__version__)")
echo "TORCH_AFTER=$TORCH_AFTER (before=$TORCH_BEFORE)"
if [ "$TORCH_BEFORE" != "$TORCH_AFTER" ]; then
  echo "requirements.txt MOVED TORCH — reinstalling the image pin"
  pip install -q --force-reinstall "torch==$TORCH_BEFORE" 2>&1 | tail -3
fi
python3 -c "import torch;assert torch.cuda.is_available();print('cuda ok',torch.__version__)" || die TORCH_CLOBBERED

stage kernels
# texture_baker + uv_unwrapper are CUDA extensions built at install time.
# TORCH_CUDA_ARCH_LIST keeps the build to THIS card instead of every arch,
# which is the difference between ~2 min and ~20 (the flash-attn lesson).
export TORCH_CUDA_ARCH_LIST=$(python3 -c "import torch;m,n=torch.cuda.get_device_capability(0);print(f'{m}.{n}')")
echo "building for sm_${TORCH_CUDA_ARCH_LIST}"
pip install -q ./texture_baker/ 2>&1 | tail -6 || die TEXTURE_BAKER
pip install -q ./uv_unwrapper/  2>&1 | tail -6 || die UV_UNWRAPPER
python3 -c "import texture_baker, uv_unwrapper; print('kernels ok')" || die KERNEL_IMPORT

stage fetch_manifest
cd /workspace/sf3d
curl -fsSL "$SB/public/$PRE/batch.json" -o batch.json || die FETCH_MANIFEST
python3 -c "import json;d=json.load(open('batch.json'));print('cars:',len(d));assert d" || die BAD_MANIFEST
curl -fsSL "$SB/public/$PRE/crease_density.py" -o /workspace/crease_density.py \
  && echo "MEASURE: crease_density.py fetched" \
  || echo "MEASURE UNAVAILABLE: measure locally instead"

stage warmup
# First call downloads the weights and JITs; do it ONCE on the repo's own
# example so a weights or API failure is not billed per car.
python3 run.py demo_files/examples/fish.png --output-dir /workspace/warm \
  2>&1 | tail -20 || die WARMUP
ls -la /workspace/warm/* || die WARMUP_NO_OUTPUT

DONE=0; FAILED=0
for TAG in $(python3 -c "import json;print(' '.join(json.load(open('batch.json'))))"); do
  stage "car_${TAG}_fetch"
  curl -fsSL "$SB/public/$PRE/in_${TAG}.png" -o "/workspace/in_${TAG}.png" \
    || { echo "FETCH FAILED $TAG"; FAILED=$((FAILED+1)); continue; }

  stage "car_${TAG}_infer"
  rm -rf "/workspace/o_${TAG}"
  if ! python3 run.py "/workspace/in_${TAG}.png" \
        --output-dir "/workspace/o_${TAG}" \
        --texture-resolution 2048 2>&1 | tail -25; then
    echo "INFER FAILED $TAG"; FAILED=$((FAILED+1)); report "log.txt"; continue
  fi
  GLB=$(find "/workspace/o_${TAG}" -name '*.glb' | head -1)
  if [ -z "$GLB" ]; then
    echo "RC=0 but NO GLB for $TAG (documented trap)"
    FAILED=$((FAILED+1)); report "log.txt"; continue
  fi

  stage "car_${TAG}_upload"
  ls -la "$GLB"
  sb_file "out_${TAG}.glb" "$GLB"
  if [ -f /workspace/crease_density.py ]; then
    echo "MEASURE $TAG" | tee -a /workspace/crease_all.txt
    python3 /workspace/crease_density.py "$GLB" 2>&1 | tail -4 \
      | tee -a /workspace/crease_all.txt \
      || echo "MEASURE FAILED $TAG" | tee -a /workspace/crease_all.txt
  else
    echo "MEASURE SKIPPED $TAG" | tee -a /workspace/crease_all.txt
  fi
  DONE=$((DONE+1))
  echo "=== PROGRESS: done=$DONE failed=$FAILED ==="
  report "log.txt"
done

stage measure
[ -f /workspace/crease_all.txt ] && sb_file crease.txt /workspace/crease_all.txt
echo "BATCH COMPLETE: done=$DONE failed=$FAILED"
[ "$DONE" -gt 0 ] || die NO_CARS_PRODUCED
echo "=== SF3D_OK ==="
report "log.txt"
