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

stage fetch_image
cd /workspace
curl -fsSL "$SB/public/$PRE/golf.png" -o golf.png || die FETCH_GOLF
# HARD GUARD: with rembg disabled, an image without a real alpha mask would
# silently take the dead path. Assert the contract instead.
python3 - <<'PY' || die INPUT_NOT_RGBA_CUTOUT
import numpy as np
from PIL import Image
im = Image.open('/workspace/golf.png')
print('input', im.size, im.mode)
assert im.mode == 'RGBA', f'need RGBA cutout, got {im.mode}'
a = np.array(im)[:, :, 3]
assert not np.all(a == 255), 'alpha is all-255 — not a cutout'
print('alpha OK: %d levels, car frac %.3f' % (len(np.unique(a)),
                                              float((a > 24).mean())))
PY

stage infer
cd /workspace/pixal
export ATTN_BACKEND=sdpa
# be EXPLICIT about the sparse backend rather than trusting a default that a
# future release could change — flex_gemm is what this image actually carries
export SPARSE_CONV_BACKEND=flex_gemm
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export HF_HOME=/workspace/hf
# standard 1536 first; fall back to low-VRAM 1536, then 1024. Each attempt
# logs its own outcome so a fallback can never be mistaken for a clean run.
OK=0
for MODE in "--resolution 1536" "--low_vram --resolution 1536" "--low_vram --resolution 1024"; do
  echo "=== ATTEMPT: $MODE ==="
  if timeout 2700 python3 inference.py --image /workspace/golf.png \
        --output /workspace/pixal_golf.glb $MODE 2>&1 | tail -60; then
    if [ -s /workspace/pixal_golf.glb ]; then
      echo "INFER_OK mode='$MODE'"; echo "$MODE" > /workspace/MODE; OK=1; break
    fi
    echo "RC=0 but NO OUTPUT FILE — treating as failure (documented trap)"
  fi
  echo "ATTEMPT FAILED: $MODE"
  report "log.txt"
done
[ "$OK" = "1" ] || die INFER_ALL_MODES

stage measure
ls -la /workspace/pixal_golf.glb
sb_file pixal_golf.glb /workspace/pixal_golf.glb
# crease_density is THE pre-registered number; compute it on the pod so the
# verdict does not depend on getting the file home
curl -fsSL "$SB/public/$PRE/crease_density.py" -o /workspace/crease_density.py || true
if [ -f /workspace/crease_density.py ]; then
  python3 /workspace/crease_density.py /workspace/pixal_golf.glb 2>&1 | tail -20 \
    > /workspace/crease.txt || true
  cat /workspace/crease.txt
  sb_file crease.txt /workspace/crease.txt
fi
python3 - <<'PY' 2>&1 | tail -20
import trimesh, numpy as np
m = trimesh.load('/workspace/pixal_golf.glb', force='mesh')
print("faces", len(m.faces), "verts", len(m.vertices))
print("bbox", np.round(m.bounds[1]-m.bounds[0], 3))
a = m.face_adjacency_angles
print("sharp_share(>45deg) %.4f" % float((a > np.pi/4).mean()))
print("watertight", m.is_watertight, "bodies", len(m.split(only_watertight=False)))
PY

echo "=== PIXAL_OK ==="
report "log.txt"
sleep infinity
