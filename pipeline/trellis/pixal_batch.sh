#!/usr/bin/env bash
# Pixal3D TEST — does pixel-aligned conditioning beat Hi3DGen on a car?
#
# Pre-registered gate (MACHINE_PLAN, written BEFORE the run so it cannot be
# moved afterwards): must beat Hi3DGen's crease_density 145 / sharp_share
# 2.07% on the same Golf capture AND survive the owner's eye.
#
# BASE IMAGE IS OUR OWN trellis2-worker-4b. Pixal3D's README says "first
# follow the TRELLIS.2 installation" — that is o_voxel, cumesh, flex_gemm,
# nvdiffrast, torchsparse and spconv, all CUDA extensions we ALREADY built
# and shipped. Reusing that image turns an hour of source builds into a pip
# install. Read from the import graph, not the README.
#
# One README step is DELIBERATELY SKIPPED, verified by reading code:
#   * flash_attn -> ATTN_BACKEND=sdpa is supported in
#     pixal3d/modules/attention/full_attn.py and documented in the README.
#
# CORRECTION 2026-08-15: I previously skipped natten too, claiming it was
# "vestigial" because `grep -rn natten *.py` returned 0 hits. THAT WAS WRONG
# and cost a run ($0.29): natten is imported by the NAF upsampler that the
# image conditioner uses (`use_naf_upsample: True` in inference.py's
# IMAGE_COND_CONFIGS), reached through a dependency rather than a direct
# import, so grep could never see it. A grep for the package NAME is not a
# dependency analysis. Installed below from a PREBUILT wheel — never the
# README's `--no-build-isolation` source build (the flash-attn lesson).
set -x
export DEBIAN_FRONTEND=noninteractive
START=$(date +%s)
LOG=/workspace/boot.log
mkdir -p /workspace
exec > >(tee -a "$LOG") 2>&1

SB="https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object"
PRE="car-meshes/pixal_test"

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
echo "TORCH_BEFORE=$TORCH_BEFORE"
df -h /workspace | tail -1

stage native_check
# CHEAPEST POSSIBLE FAILURE: if this image lacks the TRELLIS.2 CUDA
# extensions the whole plan is void — find out in 20 seconds, not 20 minutes.
#
# v1 OF THIS CHECK WAS ITSELF WRONG and failed a healthy image ($0.05,
# 2026-08-15) — the exact "a safety check that is itself wrong costs exactly
# as much as no safety check" trap in CLAUDE.md. It demanded torchsparse AND
# spconv; both are ALTERNATIVE sparse-conv backends, imported lazily by
# pixal3d/modules/sparse/conv/conv.py via
#   importlib.import_module(f'..conv_{config.CONV}')
# and the default in config.py is CONV='flex_gemm', which the image HAS.
# Only the four genuinely-on-the-default-path extensions are hard.
python3 - <<'PY' || die NATIVE_MISSING
import importlib, traceback
hard = ["o_voxel", "cumesh", "flex_gemm", "nvdiffrast"]
soft = ["torchsparse", "spconv", "utils3d"]   # alt backends / pip-installable
missing = []
for m in hard + soft:
    try:
        importlib.import_module(m); print("ok", m)
    except Exception:
        missing.append(m)
        if m in hard:
            traceback.print_exc()
print("MISSING:", missing)
bad = [m for m in missing if m in hard]
if bad:
    raise SystemExit(f"image lacks TRELLIS.2 extensions on the default "
                     f"path: {bad}")
PY

stage clone
cd /workspace
git clone --depth 1 https://github.com/TencentARC/Pixal3D pixal || die CLONE
cd pixal

stage deps
# TORCH GUARD, the documented trap: a requirements.txt that upgrades torch
# silently breaks every CUDA extension compiled against the image's build
# (they are the entire reason we chose this image). Install, then ASSERT.
pip install -q -r requirements.txt 2>&1 | tail -8
pip install -q https://github.com/LDYang694/Storages/releases/download/20260430/utils3d-0.0.2-py3-none-any.whl 2>&1 | tail -2
# MoGe-2: upstream inference.py grew a camera-estimation import since the
# 2026-08-15 run (`from moge.model.v2 import MoGeModel`) — the 2026-08-19
# rerun died INFER_ALL_MODES on exactly this. Weights auto-download from HF.
pip install -q git+https://github.com/microsoft/MoGe.git 2>&1 | tail -2 || die MOGE_INSTALL
# MoGe drags huggingface-hub to >=1.x which breaks the image's transformers
# (<1.0 required — measured: run 2 died on ImportError at inference start).
# Same clobber class as the torch guard: repin, then assert BOTH imports.
pip install -q "huggingface-hub>=0.34.0,<1.0" 2>&1 | tail -2
python3 -c "import transformers" || die HUB_REPIN
python3 -c "from moge.model.v2 import MoGeModel" || die MOGE_IMPORT
# spconv as a PREBUILT-wheel fallback backend (~30s, never a source build —
# the flash-attn lesson). flex_gemm is the default and is already present;
# this only buys SPARSE_CONV_BACKEND=spconv as a retry if flex_gemm misbehaves.
pip install -q spconv-cu124 2>&1 | tail -2 || echo "spconv wheel unavailable — flex_gemm only"
# natten: PREBUILT wheel matching this image exactly (torch 2.6.0 + cu124 +
# cp310, confirmed present in the SHI-Labs index). The README asks for 0.21.0
# built from source; the index tops out at 0.17.5, so if the NAF upsampler
# needs a newer API this will fail LOUDLY at import rather than after a
# 30-minute build.
PYTAG=$(python3 -c "import sys;print(f'cp{sys.version_info.major}{sys.version_info.minor}')")
NATTEN_WHL="https://github.com/SHI-Labs/NATTEN/releases/download/v0.17.5/natten-0.17.5%2Btorch260cu124-${PYTAG}-${PYTAG}-linux_x86_64.whl"
echo "natten wheel: $NATTEN_WHL"
pip install -q "$NATTEN_WHL" 2>&1 | tail -3 || die NATTEN_WHEEL
python3 -c "import natten; print('natten', natten.__version__)" || die NATTEN_IMPORT
TORCH_AFTER=$(python3 -c "import torch;print(torch.__version__)")
echo "TORCH_AFTER=$TORCH_AFTER (before=$TORCH_BEFORE)"
if [ "$TORCH_BEFORE" != "$TORCH_AFTER" ]; then
  echo "requirements.txt MOVED TORCH — reinstalling the image's pin"
  pip install -q --force-reinstall "torch==$TORCH_BEFORE" 2>&1 | tail -3
fi
python3 - <<'PY' || die NATIVE_BROKEN_BY_DEPS
import torch, o_voxel, cumesh, flex_gemm, utils3d
assert torch.cuda.is_available()
print("post-deps OK: torch", torch.__version__, "+ native extensions intact")
PY

stage patch_rembg
# briaai/RMBG-2.0 is GATED on HuggingFace (403, measured 2026-08-15) and the
# pipeline's from_pretrained builds it EAGERLY — so it dies before reaching
# the code that would skip it. And it WOULD skip it: preprocess_image checks
#   if input.mode == 'RGBA' and not np.all(alpha == 255): has_alpha = True
# and only calls rembg when has_alpha is False. Our capture contract REQUIRES
# background-removed RGBA (carglb's capture gate enforces it), so background
# removal is dead code for us. Make the eager load non-fatal.
# The two later uses are already safe: one is guarded `is not None`, the
# other sits inside the no-alpha branch we never take.
# THERE ARE THREE construction sites, not one — pixal3d_image_to_3d.py (the
# pipeline inference.py actually uses), trellis2_image_to_3d.py and
# trellis2_texturing.py. v1 of this patch hit only the texturing one, the run
# still 403'd, and $0.32 bought the lesson: patch EVERY site and ASSERT THE
# COUNT rather than trusting the first grep hit.
python3 - <<'PY' || die PATCH_REMBG
import ast, glob
old = ("        pipeline.rembg_model = getattr(rembg, "
       "args['rembg_model']['name'])(**args['rembg_model']['args'])\n")
new = ("        try:\n"
       "            pipeline.rembg_model = getattr(rembg, "
       "args['rembg_model']['name'])(**args['rembg_model']['args'])\n"
       "        except Exception as _e:\n"
       "            print(f'[patched] rembg unavailable ({type(_e).__name__})"
       " - RGBA-input-only mode')\n"
       "            pipeline.rembg_model = None\n")
n = 0
for p in glob.glob("/workspace/pixal/pixal3d/pipelines/*.py"):
    s = open(p).read()
    if old in s:
        s = s.replace(old, new)
        open(p, "w").write(s)
        ast.parse(s)
        n += 1
        print("patched", p)
assert n == 3, f"expected 3 rembg construction sites, patched {n} — repo changed"
print(f"patched {n}/3 rembg eager loads (all non-fatal now)")
PY

stage fetch_manifest
cd /workspace
curl -fsSL "$SB/public/$PRE/batch.json" -o batch.json || die FETCH_MANIFEST
python3 -c "import json;d=json.load(open('/workspace/batch.json'));print('batch cars:',len(d));assert d" || die BAD_MANIFEST

export ATTN_BACKEND=sdpa
export SPARSE_CONV_BACKEND=flex_gemm
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export HF_HOME=/workspace/hf

# BATCH LOOP. One pod, N cars: boot+deps (~3 min) and the ~10GB weight cache
# are paid ONCE instead of per car. Every car uploads its OWN result the
# moment it finishes, so a failure on car 4 can never lose cars 1-3 (the
# "upload cheap artefacts before expensive ones" rule, applied per item).
# A car that fails is logged and SKIPPED — one bad input must not sink the run.
DONE=0; FAILED=0
for TAG in $(python3 -c "import json;print(' '.join(json.load(open('/workspace/batch.json'))))"); do
  stage "car_${TAG}_fetch"
  cd /workspace
  curl -fsSL "$SB/public/$PRE/in_${TAG}.png" -o "in_${TAG}.png" || { echo "FETCH FAILED $TAG"; FAILED=$((FAILED+1)); continue; }
  python3 - "$TAG" <<'PY2' || { echo "NOT RGBA: $TAG"; FAILED=$((FAILED+1)); continue; }
import sys, numpy as np
from PIL import Image
t = sys.argv[1]
im = Image.open(f'/workspace/in_{t}.png')
assert im.mode == 'RGBA', f'need RGBA cutout, got {im.mode}'
a = np.array(im)[:, :, 3]
assert not np.all(a == 255), 'alpha all-255 — not a cutout'
print(f'{t}: {im.size} alpha levels {len(np.unique(a))} car frac {float((a>24).mean()):.3f}')
PY2

  stage "car_${TAG}_infer"
  cd /workspace/pixal
  OK=0
  for MODE in "--resolution 1536" "--low_vram --resolution 1536" "--low_vram --resolution 1024"; do
    echo "=== $TAG ATTEMPT: $MODE ==="
    if timeout 2700 python3 inference.py --image "/workspace/in_${TAG}.png" \
          --output "/workspace/out_${TAG}.glb" $MODE 2>&1 | tail -40; then
      if [ -s "/workspace/out_${TAG}.glb" ]; then
        echo "INFER_OK $TAG mode='$MODE'"; OK=1; break
      fi
      echo "RC=0 but NO OUTPUT FILE for $TAG (documented trap)"
    fi
    echo "ATTEMPT FAILED $TAG: $MODE"
    report "log.txt"
  done
  if [ "$OK" != "1" ]; then echo "CAR FAILED: $TAG"; FAILED=$((FAILED+1)); report "log.txt"; continue; fi

  stage "car_${TAG}_upload"
  ls -la "/workspace/out_${TAG}.glb"
  sb_file "out_${TAG}.glb" "/workspace/out_${TAG}.glb"
  if [ -f /workspace/crease_density.py ]; then
    python3 /workspace/crease_density.py "/workspace/out_${TAG}.glb" 2>&1 | tail -4 \
      | tee -a /workspace/crease_all.txt
  fi
  DONE=$((DONE+1))
  echo "=== PROGRESS: done=$DONE failed=$FAILED ==="
  report "log.txt"
done

stage measure
cp /workspace/crease_all.txt /workspace/crease.txt 2>/dev/null || true
[ -f /workspace/crease.txt ] && sb_file crease.txt /workspace/crease.txt
echo "BATCH COMPLETE: done=$DONE failed=$FAILED"
[ "$DONE" -gt 0 ] || die NO_CARS_PRODUCED
echo "=== PIXAL_OK ==="
report "log.txt"
