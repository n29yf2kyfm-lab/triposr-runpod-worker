#!/usr/bin/env bash
# Step1X-3D TEXTURE stage — runs on an existing geometry mesh.
#
# The geometry bootstrap (step1x_boot.sh) deliberately excluded this half
# because it is the expensive one. Here is what it actually costs, established
# by AST-walking the import chain FROM THE PACKAGE ROOT locally rather than
# discovering one dependency per rented pod:
#
#   EAGER, hard-required by step1x_3d_texture_synthesis_pipeline:
#     pytorch3d    <- pipeline:14 -> ig2mv_sdxl_pipeline:55 -> texture_sync.project:2
#     nvdiffrast   <- pipeline:21 -> utils/render.py:8
#     xatlas       <- pipeline:24 (also utils/render.py:17)
#     cupy         <- texture_sync/voronoi.py:8
#     cv2, matplotlib, scipy
#   LAZY: custom_rasterizer (mesh_render.py:174), diso
#   NOT NEEDED: kaolin. It is in requirements.txt and on NO import path.
#
# THE ONE EXPENSIVE ITEM IS pytorch3d: PyPI ships MACOS-ONLY wheels (checked:
# 0.7.4 has cp38/39/310 macosx and nothing else) and the official prebuilt
# index has no py311_cu124_pyt251 build (403). So it must be compiled. We
# compile it ONCE and CACHE THE WHEEL IN THE BUCKET, so every later texture
# run is a pip install. TORCH_CUDA_ARCH_LIST is pinned to the ONE card the pod
# actually has -- derived at runtime, not guessed -- which is the difference
# between a ~15 minute build and a ~60 minute one.
#
# TWO TRAPS THIS AVOIDS BY CONSTRUCTION, both recorded in CLAUDE.md:
#   * BiRefNet: `AutoModelForImageSegmentation.from_pretrained("ZhengPeng7/
#     BiRefNet")` is built INSIDE `if remove_bg:`, so unlike Pixal3D's RMBG-2.0
#     -- which was constructed eagerly in three places before the code that
#     would have skipped it -- passing remove_bg=False genuinely skips it. Our
#     input is an RGBA cutout, so background removal is dead code anyway. We
#     composite to RGB on white ourselves and keep the download off the pod.
#   * nvdiffrast context: the wrapper DEFAULTS to context_type="gl", which on a
#     headless pod means EGL. The pipeline's own call site passes "cuda"
#     (pipeline:237), so no GL/EGL dev stack is needed. Verified before writing.
set -x
export DEBIAN_FRONTEND=noninteractive
START=$(date +%s)
LOG=/workspace/boot.log
mkdir -p /workspace
exec > >(tee -a "$LOG") 2>&1

SB="https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object"
PRE="${S1X_PRE:-car-meshes/staging/step1x_van}"
IN_NAME="${S1X_IN:-van.png}"
MESH_NAME="${S1X_MESH:-step1x_label.glb}"
OUT_NAME="${S1X_OUT:-step1x_textured.glb}"
WHEEL_KEY="${S1X_WHEEL:-wheels/pytorch3d-py311-cu124-pyt251-sm80.whl}"

LOGKEY="${S1X_LOGKEY:-tex_log.txt}"
RUN_ID="${RUNPOD_POD_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"
report() { ( set +x
  for _k in "$1" "$(echo "$1" | sed "s/\.txt$//")_${RUN_ID}.txt"; do
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
FUSE_MIN="${S1X_FUSE_MIN:-75}"
fuse() {
  echo "=== FUSE: holding ${FUSE_MIN}m then self-terminating ==="
  sleep $(( FUSE_MIN * 60 ))
  ( set +x; curl -s -X DELETE -H "Authorization: Bearer ${RUNPOD_API_KEY}" \
      "https://rest.runpod.io/v1/pods/${RUNPOD_POD_ID}" >/dev/null 2>&1 ) || true
  echo "=== FUSE: delete requested; the launcher's external 404 check is the real guard ==="
  sleep 600
}
die()   { echo "=== FAIL:$1 ==="; report "$LOGKEY"; fuse; }

stage boot
nvidia-smi || die NO_GPU
python3 -c "import torch;print('torch',torch.__version__,torch.version.cuda,torch.cuda.get_device_name(0))" || die TORCH_BROKEN
nvcc --version | tail -2 || die NO_NVCC          # pytorch3d NEEDS nvcc, unlike the geometry run
df -h /workspace | tail -1

stage clone
cd /workspace
git clone --depth 1 https://github.com/stepfun-ai/Step1X-3D s1x || die CLONE

stage deps_base
apt-get update -qq && apt-get install -y -qq libopengl0 libegl1 libglx0 2>&1 | tail -2
pip install -q torch==2.5.1 torchvision==0.20.1 --index-url https://download.pytorch.org/whl/cu124 2>&1 | tail -3
python3 -c "import torch;assert torch.__version__.startswith('2.5.1'),torch.__version__;assert torch.cuda.is_available()" || die TORCH_PIN

# The geometry package's eager training deps are STILL required: the texture
# pipeline imports step1x3d_geometry.models.pipelines.pipeline_utils (line 27),
# and step1x3d_geometry/__init__.py:52 does `from . import data, models,
# systems` unconditionally. Two earlier pods died on exactly this.
pip install -q \
  "diffusers==0.32.2" "transformers==4.48.0" "huggingface-hub>=0.26.2,<1.0" \
  "safetensors" "accelerate" "omegaconf==2.3.0" "einops==0.8.0" \
  "jaxtyping==0.2.28" "typeguard" "trimesh==4.3.2" "numpy==1.26.4" \
  "pillow==10.3.0" "scikit-image" "timm>=1.0" "opencv-python-headless" \
  "matplotlib" "scipy" "pymeshlab" "PyMCubes" "rembg==2.0.65" "onnxruntime" \
  "pytorch-lightning==2.2.4" "lightning-utilities==0.11.2" \
  "bs4==0.0.2" "beautifulsoup4" "tqdm" "packaging" \
  "mosaicml-streaming==0.11.0" "imageio==2.34.1" "wandb==0.18.6" \
  "xatlas" "cupy-cuda12x" 2>&1 | tail -5

python3 - <<'PY' || die PYMESHLAB_IO
import tempfile, os, trimesh, pymeshlab, importlib.metadata as md
m = trimesh.creation.icosphere(subdivisions=1)
p = os.path.join(tempfile.gettempdir(), "iotest.ply"); m.export(p)
ms = pymeshlab.MeshSet(); ms.load_new_mesh(p)
ms.save_current_mesh(p.replace(".ply", "_rt.ply"))
ms2 = pymeshlab.MeshSet(); ms2.load_new_mesh(p.replace(".ply", "_rt.ply"))
assert ms2.current_mesh().vertex_number() == len(m.vertices)
print("pymeshlab PLY round-trip ok, resolved version", md.version("pymeshlab"))
PY

stage pytorch3d
# CACHE FIRST. A prior run's wheel makes this stage ~30 seconds instead of ~15
# minutes, and the build is deterministic for a given (py, torch, cuda, sm).
cd /workspace
if curl -fsSL -H "apikey: ${SB_KEY}" -H "Authorization: Bearer ${SB_KEY}" \
     "$SB/$PRE/$WHEEL_KEY" -o /workspace/p3d.whl && [ -s /workspace/p3d.whl ]; then
  echo "pytorch3d wheel CACHE HIT ($(stat -c%s /workspace/p3d.whl) bytes)"
  pip install -q /workspace/p3d.whl 2>&1 | tail -3
else
  echo "pytorch3d wheel CACHE MISS — building from source"
  # Pin the arch list to THIS card. Derived, never guessed: building for every
  # architecture is the single biggest time sink in a pytorch3d build.
  ARCH=$(python3 -c "import torch;c=torch.cuda.get_device_capability(0);print(f'{c[0]}.{c[1]}')")
  echo "building for sm_${ARCH} with MAX_JOBS=$(nproc)"
  export TORCH_CUDA_ARCH_LIST="$ARCH"
  export MAX_JOBS=$(nproc)
  export FORCE_CUDA=1
  pip install -q "fvcore" "iopath" 2>&1 | tail -2
  git clone --depth 1 https://github.com/facebookresearch/pytorch3d.git /workspace/p3d_src || die P3D_CLONE
  cd /workspace/p3d_src
  python3 setup.py bdist_wheel > /workspace/p3d_build.log 2>&1
  P3D_RC=$?
  tail -25 /workspace/p3d_build.log
  echo "P3D_BUILD_RC=$P3D_RC"
  [ "$P3D_RC" -eq 0 ] || { sb_file "p3d_build.log" /workspace/p3d_build.log || true; die P3D_BUILD; }
  WHL=$(ls /workspace/p3d_src/dist/*.whl 2>/dev/null | head -1)
  [ -n "$WHL" ] || die P3D_NO_WHEEL
  pip install -q "$WHL" 2>&1 | tail -3
  # cache it before anything else can go wrong
  sb_file "$WHEEL_KEY" "$WHL" || echo "wheel cache upload failed — not fatal"
  cd /workspace
fi
python3 -c "import torch, pytorch3d; print('pytorch3d ok', pytorch3d.__version__)" || die P3D_IMPORT
python3 -c "import torch; from pytorch3d import _C; print('pytorch3d CUDA ext ok')" || die P3D_CUDA_EXT

stage nvdiffrast
pip install -q ninja 2>&1 | tail -1
pip install -q git+https://github.com/NVlabs/nvdiffrast.git 2>&1 | tail -3
python3 -c "import torch, nvdiffrast.torch as dr; print('nvdiffrast imports ok')" || die NVDIFFRAST
# nvdiffrast JIT-compiles on FIRST USE, not on import -- so an import check is
# not evidence it works. Build the actual CUDA context the pipeline builds.
python3 - <<'PY' || die NVDIFFRAST_CTX
import torch, nvdiffrast.torch as dr
ctx = dr.RasterizeCudaContext(device="cuda")   # the pipeline passes context_type="cuda"
print("nvdiffrast RasterizeCudaContext built ok")
PY

stage custom_rasterizer
cd /workspace/s1x/step1x3d_texture/custom_rasterizer
pip install -q . > /workspace/cr_build.log 2>&1 || { tail -20 /workspace/cr_build.log; die CUSTOM_RASTERIZER; }
python3 -c "import torch, custom_rasterizer; print('custom_rasterizer ok')" || die CR_IMPORT

stage import_gate
# ASSERT THE TEXTURE PIPELINE IMPORTS BEFORE SPENDING INFERENCE MINUTES. torch
# first: a torch CUDA extension only finds libc10 once torch is loaded (the
# udf_ext lesson that killed a $0.85 Direct3D-S2 run at minute 39).
cd /workspace/s1x
python3 - <<'PY' || die TEXTURE_IMPORT
import torch
from step1x3d_texture.pipelines.step1x_3d_texture_synthesis_pipeline import Step1X3DTexturePipeline
print("texture pipeline imports OK")
PY

stage fetch_inputs
cd /workspace
curl -fsSL -H "apikey: ${SB_KEY}" -H "Authorization: Bearer ${SB_KEY}" \
     "$SB/$PRE/$MESH_NAME" -o mesh_in.glb || die FETCH_MESH
curl -fsSL "$SB/public/$PRE/$IN_NAME" -o input.png || die FETCH_INPUT
python3 - <<'PY' || die INPUT_BAD
import trimesh, numpy as np
from PIL import Image
m = trimesh.load('/workspace/mesh_in.glb', force='mesh', process=False)
print('mesh in: faces', len(m.faces), 'verts', len(m.vertices),
      'bbox', np.round(m.bounds[1]-m.bounds[0], 3))
assert len(m.faces) > 1000, 'mesh is empty or trivial'
im = Image.open('/workspace/input.png'); print('image in:', im.size, im.mode)
# remove_bg=False below, so hand the pipeline a clean RGB composite rather
# than an RGBA it may not expect. White ground matches the studio convention.
if im.mode == 'RGBA':
    bg = Image.new('RGB', im.size, (255, 255, 255))
    bg.paste(im, mask=im.split()[3])
    bg.save('/workspace/input_rgb.png')
    print('composited RGBA -> RGB on white')
else:
    im.convert('RGB').save('/workspace/input_rgb.png')
PY

stage infer
cd /workspace/s1x
export HF_HOME=/workspace/hf
python3 - > /tmp/tex.out 2>&1 <<'PY'
import time, torch, trimesh
from step1x3d_texture.pipelines.step1x_3d_texture_synthesis_pipeline import Step1X3DTexturePipeline
from step1x3d_geometry.models.pipelines.pipeline_utils import remove_degenerate_face, reduce_face

t0 = time.time()
mesh = trimesh.load("/workspace/mesh_in.glb")
p = Step1X3DTexturePipeline.from_pretrained("stepfun-ai/Step1X-3D",
                                            subfolder="Step1X-3D-Texture")
mesh = remove_degenerate_face(mesh)
mesh = reduce_face(mesh)
# remove_bg=False: our conditioning image is already a cutout composited to
# white, so BiRefNet is dead code -- and skipping it keeps a ~1GB download and
# its trust_remote_code/timm requirements off the pod entirely.
# ARG ORDER IS (image, mesh) -- NOT (mesh, image). Caught by reading the
# signature before renting a GPU; I had written it reversed, which would have
# passed a Trimesh where a path was expected and burned the whole run. The
# repo's own inference.py:62 confirms the order.
out = p("/workspace/input_rgb.png", mesh, remove_bg=False, seed=2025)
out.export("/workspace/step1x_textured.glb")
print(f"textured: faces={len(out.faces)} verts={len(out.vertices)} {time.time()-t0:.0f}s")
PY
INFER_RC=$?
tail -40 /tmp/tex.out
echo "INFER_RC=$INFER_RC"
[ "$INFER_RC" -eq 0 ] || { sb_file "tex_infer.log" /tmp/tex.out || true; die INFER; }
[ -s /workspace/step1x_textured.glb ] || die NO_TEXTURED_OUTPUT

stage measure
ls -la /workspace/step1x_textured.glb
sb_file "$OUT_NAME" /workspace/step1x_textured.glb || die UPLOAD_TEXTURED
sb_file "$(echo "$OUT_NAME" | sed 's/\.glb$//')_${RUN_ID}.glb" /workspace/step1x_textured.glb || true
python3 - <<'PY' 2>&1 | tail -20
import trimesh, numpy as np
m = trimesh.load("/workspace/step1x_textured.glb", force="mesh", process=False)
print("faces", len(m.faces), "verts", len(m.vertices),
      "bbox", np.round(m.bounds[1]-m.bounds[0], 3))
v = m.visual
print("visual kind:", type(v).__name__)
try:
    print("uv present:", v.uv is not None and len(v.uv) > 0)
    img = getattr(getattr(v, "material", None), "baseColorTexture", None)
    print("baseColorTexture:", (img.size if img is not None else None))
except Exception as e:
    print("texture probe:", type(e).__name__, e)
PY

echo "=== STEP1X_TEX_OK ==="
report "$LOGKEY"
fuse
