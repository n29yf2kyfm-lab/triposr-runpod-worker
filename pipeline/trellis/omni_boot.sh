#!/usr/bin/env bash
# omni_boot.sh — LEG B: Hunyuan3D-Omni with BOUNDING-BOX control.
#
# WHY. Every generator this project has run is conditioned on a photograph, and
# the measured blocker on single-image meshes is the PERSPECTIVE BAKE: the far
# end of the car generates ~25% narrower because the camera's perspective enters
# the geometry, and no linear correction fixes a taper. Hunyuan3D-Omni accepts a
# point cloud, a voxel grid or a BOUNDING BOX as an additional control. The bbox
# mode is the owner's own OEM-dimensions idea made executable: published length,
# width and height become a generation control rather than a hope.
#
# READ THE CODE, NOT THE DOCSTRING. inference.py's own docstring says bbox is
# [x_min,y_min,z_min,x_max,y_max,z_max] — SIX numbers. The demo data it ships
# and the tensor the code builds are THREE numbers (normalised extents, max
# component 1.0). The docstring is wrong; the demo and the code agree.
#
# THE AXIS ORDER IS NOT DOCUMENTED ANYWHERE, so it is MEASURED rather than
# guessed: both plausible orderings are run in the same pod on the same image
# (length/height/width and length/width/height) and the output whose measured
# proportions match the published spec identifies the convention. Two 50-step
# generations cost about a minute each — far cheaper than a wrong assumption.
#
# NO `set -x` — an xtrace in a bootstrap leaked SB_KEY into a public bucket log
# on 2026-08-18 and the key had to be rotated.
export DEBIAN_FRONTEND=noninteractive
export PYTHONUNBUFFERED=1
LOG=/workspace/boot.log
mkdir -p /workspace
exec > >(tee -a "$LOG") 2>&1

SB="https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object"
PRE="${ST_PRE:-car-meshes/staging/sharptest}"
RUN="${ST_RUN:-runB}"

report()  { curl -s -X POST -H "apikey: ${SB_KEY}" -H "Authorization: Bearer ${SB_KEY}" \
              -H "x-upsert: true" -H "Content-Type: text/plain" \
              --data-binary @"$LOG" "$SB/$PRE/${RUN}_log.txt" >/dev/null 2>&1 || true; }
sb_file() { local code
            code=$(curl -s -o /tmp/put.out -w "%{http_code}" -X POST \
              -H "apikey: ${SB_KEY}" -H "Authorization: Bearer ${SB_KEY}" \
              -H "x-upsert: true" -H "Content-Type: application/octet-stream" \
              --data-binary @"$2" "$SB/$PRE/$1")
            echo "UPLOAD $1 -> HTTP $code ($(stat -c%s "$2") bytes)"; }
sb_get()  { curl -s -f -o "$2" -H "apikey: ${SB_KEY}" -H "Authorization: Bearer ${SB_KEY}" \
              "$SB/$PRE/$1"; }
stage()   { echo "=== STAGE:$1 ==="; report; }
die()     { echo "=== FAIL:$1 ==="; report; sleep infinity; }

FUSE_S="${ST_FUSE_S:-2400}"
( sleep "$FUSE_S"
  echo "=== FUSE: ${FUSE_S}s elapsed — self-terminating ==="; report
  runpodctl remove pod "$RUNPOD_POD_ID" >/dev/null 2>&1 || true
  curl -s -X DELETE -H "Authorization: Bearer ${RUNPOD_API_KEY}" \
       "https://rest.runpod.io/v1/pods/${RUNPOD_POD_ID}" >/dev/null 2>&1 || true ) &
echo "fuse armed: ${FUSE_S}s"

stage boot
nvidia-smi || die NO_GPU
python3 -c "import torch;print('torch',torch.__version__,torch.version.cuda,torch.cuda.get_device_name(0))" || die TORCH_BROKEN
TORCH_BEFORE=$(python3 -c "import torch;print(torch.__version__)")
echo "TORCH_BEFORE=$TORCH_BEFORE"
df -h / | tail -1

stage fetch_input
sb_get omni_in.png /workspace/omni_in.png || die FETCH_IMAGE
python3 -c "from PIL import Image;im=Image.open('/workspace/omni_in.png');print('image',im.size,im.mode)" || die BAD_IMAGE

stage clone
cd /workspace
git clone --depth 1 https://github.com/Tencent-Hunyuan/Hunyuan3D-Omni.git omni || die CLONE
cd omni && ls

stage apt
apt-get -qq update >/dev/null 2>&1
# pymeshlab needs libOpenGL.so.0 or its postprocess dies — a paid lesson from
# the 2026-08-12 Hunyuan run.
apt-get -qq install -y libgl1 libgomp1 libglib2.0-0 libopengl0 >/dev/null 2>&1
echo "apt ok"

stage deps
# NOT requirements.txt. That file pins deepspeed, realesrgan, rembg, gradio,
# cupy and a torchaudio+cu124 build that none of the CLI inference path
# imports, and it moves torch. The import graph of inference.py + hy3dshape
# was scanned instead, and this is what it actually needs.
pip install -q --no-cache-dir "numpy<2" einops omegaconf trimesh pymeshlab \
    scikit-image scipy opencv-python-headless "huggingface_hub<1.0" \
    "transformers==4.46.0" "diffusers==0.30.0" "timm" torchdiffeq peft \
    "pytorch-lightning==1.9.5" pyyaml tqdm 2>&1 | tail -6 || die PIP_BASE
pip install -q --no-cache-dir diso 2>&1 | tail -4 || echo "diso pip failed"
PYG_URL="https://data.pyg.org/whl/torch-${TORCH_BEFORE}.html"
pip install -q --no-cache-dir torch-cluster -f "$PYG_URL" 2>&1 | tail -4
TORCH_AFTER=$(python3 -c "import torch;print(torch.__version__)")
echo "TORCH_AFTER=$TORCH_AFTER"
[ "$TORCH_BEFORE" = "$TORCH_AFTER" ] || { echo "deps MOVED torch — repinning"
  pip install -q --no-cache-dir --force-reinstall "torch==$TORCH_BEFORE" 2>&1 | tail -3; }
python3 -c "import torch;assert torch.cuda.is_available();print('cuda ok',torch.__version__)" || die TORCH_CLOBBERED
python3 -c "import trimesh,transformers,diffusers,skimage,pytorch_lightning;print('deps ok')" || die DEPS_IMPORT

stage import_check
cd /workspace/omni
python3 -c "
from hy3dshape.pipelines import Hunyuan3DOmniSiTFlowMatchingPipeline
from hy3dshape.postprocessors import FloaterRemover, DegenerateFaceRemover
print('omni imports ok')
" 2>&1 | tail -20 || die OMNI_IMPORT

stage preflight_all
# LEG A cost three pod cycles to my own install list. Every module the later
# stages need is proven HERE, before 13 GB of weights are pulled.
python3 - <<'PFA' || die PREFLIGHT_IMPORTS
import importlib, sys
need = ["torch", "numpy", "trimesh", "einops", "omegaconf", "skimage", "scipy",
        "cv2", "pymeshlab", "transformers", "diffusers", "timm", "torchdiffeq",
        "peft", "pytorch_lightning", "torch_cluster", "huggingface_hub", "yaml",
        "PIL", "tqdm"]
miss = []
for m in need:
    try:
        importlib.import_module(m)
    except Exception as e:
        miss.append("%s: %s: %s" % (m, type(e).__name__, e))
print("preflight imports:", len(need) - len(miss), "/", len(need), "ok")
if miss:
    print("MISSING:")
    for x in miss:
        print("  ", x)
    sys.exit(1)
PFA

stage weights
python3 - <<'PY' || die WEIGHTS
import os, time
from huggingface_hub import snapshot_download
for a in range(1, 4):
    try:
        p = snapshot_download("tencent/Hunyuan3D-Omni",
                              token=os.environ.get("HF_TOKEN"),
                              local_dir="/workspace/omni_ckpt",
                              ignore_patterns=["assets/*", "*_ema.bin"])
        print("weights at", p)
        break
    except Exception as e:
        print(f"attempt {a}: {type(e).__name__}: {e}")
        if a == 3:
            raise
        time.sleep(10 * a)
PY
du -sh /workspace/omni_ckpt

stage build_control
cd /workspace/omni
# Overwrite the demo's OWN data.json and drop the images beside it, rather than
# sed-ing a path inside inference.py. A global sed once rewrote the substring
# inside a FILENAME and produced a URL that 400'd, and the failure was silent.
python3 - <<'BC' || die BUILD_CONTROL
import json, shutil, os
d = "/workspace/omni/demos/bbox"
os.makedirs(d, exist_ok=True)
L, W, H = 4.284, 1.789, 1.456          # VW Golf Mk8 published, metres
m = max(L, W, H)
lhw = [round(L/m, 6), round(H/m, 6), round(W/m, 6)]   # length, height, width
lwh = [round(L/m, 6), round(W/m, 6), round(H/m, 6)]   # length, width, height
for tag in ("golfLHW", "golfLWH"):
    shutil.copy("/workspace/omni_in.png", f"{d}/{tag}.png")
data = {"image": [f"./demos/bbox/golfLHW.png", f"./demos/bbox/golfLWH.png"],
        "bbox": [lhw, lwh]}
json.dump(data, open(f"{d}/data.json", "w"), indent=1)
print(json.dumps(data))
BC
cat /workspace/omni/demos/bbox/data.json

stage infer
cd /workspace/omni
# from_pretrained takes a LOCAL PATH when it exists (pipeline_generation_sit_omni.py:52),
# so the weights already on disk are used instead of being downloaded twice.
python3 inference.py --control_type bbox --repo_id /workspace/omni_ckpt \
        --save_dir /workspace/omni_out 2>&1 | tail -60
RC=${PIPESTATUS[0]}
echo "INFERENCE RC=$RC"
[ "$RC" = "0" ] || die INFER_RC_$RC
find /workspace/omni_out -name '*.glb' | tee /workspace/globs.txt
[ -s /workspace/globs.txt ] || die NO_GLB_PRODUCED

stage measure_upload
sb_get crease_density.py /workspace/crease_density.py || true
sb_get crease2.py /workspace/crease2.py || true
: > /workspace/report.txt
while read -r g; do
  b=$(basename "$g")
  echo "== $b" >> /workspace/report.txt
  python3 - "$g" >> /workspace/report.txt <<'PY'
import sys, trimesh, numpy as np
m = trimesh.load(sys.argv[1], process=False, force='mesh')
e = np.sort(m.bounding_box.extents)[::-1]
print("faces", len(m.faces), "extents(sorted desc)", np.round(e, 4).tolist(),
      "ratios vs longest", np.round(e / e[0], 4).tolist())
print("Golf Mk8 published ratios: 1.0, 0.4176 (width), 0.3399 (height)")
PY
  [ -f /workspace/crease_density.py ] && python3 /workspace/crease_density.py "$g" >> /workspace/report.txt 2>&1
  [ -f /workspace/crease2.py ] && python3 /workspace/crease2.py "$g" >> /workspace/report.txt 2>&1
  sb_file "${RUN}_${b}" "$g"
done < /workspace/globs.txt
cat /workspace/report.txt
sb_file "${RUN}_report.txt" /workspace/report.txt

echo "=== OMNI_OK ==="
report
runpodctl remove pod "$RUNPOD_POD_ID" >/dev/null 2>&1 || true
curl -s -X DELETE -H "Authorization: Bearer ${RUNPOD_API_KEY}" \
     "https://rest.runpod.io/v1/pods/${RUNPOD_POD_ID}" >/dev/null 2>&1 || true
sleep infinity
