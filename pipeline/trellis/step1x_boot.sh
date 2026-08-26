#!/usr/bin/env bash
# Step1X-3D (stepfun-ai, Apache-2.0, PUBLIC ungated weights) — GEOMETRY ONLY.
#
# WHY GEOMETRY ONLY, AND WHY THAT MAKES THIS CHEAP. Read from the IMPORT GRAPH,
# not the README (the recorded method). The repo's requirements.txt asks for
# pytorch3d and nvdiffrast from git — two SOURCE BUILDS — plus kaolin and two
# custom CUDA extensions lifted from Hunyuan3D 2.0. Every one of those is
# referenced ONLY by step1x3d_texture:
#
#     pytorch3d           4 texture files, 0 geometry
#     nvdiffrast          2 texture files, 0 geometry
#     custom_rasterizer   2 texture files, 0 geometry
#
# So a geometry run needs NO source build at all. We have our own material
# chain, so the texture stage is not wanted anyway.
#
# THE REPO'S OWN inference.py CANNOT BE USED. It imports the TEXTURE pipeline at
# module scope (line 6), so it would drag in every one of those deps before
# reaching a geometry-only call. This bootstrap writes its own driver.
#
# THE TRAINING DEPS *ARE* ON THE PATH. This header previously claimed the
# opposite -- "the pipeline never reaches data/Objaverse.py" -- and that was
# WRONG, proven by a rented pod: step1x3d_geometry/__init__.py line 52 does
# `from . import data, models, systems` UNCONDITIONALLY, so importing anything
# in the package executes data/ and systems/ first. Two pods died on this
# (pytorch_lightning at line 37, then streaming at line 52).
#
# MY AST SCAN MISSED IT for a reason worth keeping: it walked the chain FROM
# the pipeline module, but Python executes the package __init__ BEFORE any
# submodule, so the scan had a blind spot at precisely the entry point. Scan
# from the PACKAGE ROOT, not from the module you intend to call.
#
# Owner ruling: pin the deps rather than patch the import out. mosaicml-streaming
# provides `streaming`; imageio and wandb complete data/ and systems/.
#
# LAZY vs EAGER, which decides what must be installed:
#   lazy (inside functions) -> diso, torch_cluster, sageattention, fpsample
#   EAGER                   -> rembg, at module scope in pipeline.py
# rembg is dead code for us (our input is an RGBA cutout and the pipeline skips
# background removal when alpha is present), but an eager import still has to
# resolve — the same trap Pixal3D's RMBG-2.0 set, where the model was built
# before the code that would have skipped it.
set -x
export DEBIAN_FRONTEND=noninteractive
START=$(date +%s)
LOG=/workspace/boot.log
mkdir -p /workspace
exec > >(tee -a "$LOG") 2>&1

SB="https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object"
PRE="${S1X_PRE:-car-meshes/staging/step1x_van}"
IN_NAME="${S1X_IN:-input.png}"

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
nvcc --version | tail -2 || echo "no nvcc — diso may need a wheel"
df -h /workspace | tail -1

stage clone
cd /workspace
git clone --depth 1 https://github.com/stepfun-ai/Step1X-3D s1x || die CLONE
cd s1x

stage deps
# libOpenGL: pymeshlab's IO PLUGINS are Qt plugins linked against libOpenGL.so.0.
# Without it `libio_base.so` -- the plugin that registers PLY/OBJ/STL -- refuses
# to load, and pymeshlab then knows NO FILE FORMATS AT ALL. That is exactly how
# pod 3 died: the model generated fine, all 50 diffusion steps ran, and the
# pipeline's own remove_floater() blew up on `Unknown format for load: ply`
# AFTER the expensive part. CLAUDE.md already records this from the Hunyuan3D-2
# deployment ("pymeshlab's postprocess needs libOpenGL.so.0 (libopengl0) or
# FloaterRemover dies"); it was paid a second time here.
apt-get update -qq && apt-get install -y -qq libopengl0 libegl1 libglx0 2>&1 | tail -2
# Pin torch to what the project is tested on AND what the torch_cluster wheel
# index is built for. Doing this first so everything else compiles against it.
pip install -q torch==2.5.1 torchvision==0.20.1 --index-url https://download.pytorch.org/whl/cu124 2>&1 | tail -3
python3 -c "import torch;assert torch.__version__.startswith('2.5.1'),torch.__version__;assert torch.cuda.is_available();print('torch pinned',torch.__version__)" || die TORCH_PIN

# ONLY the geometry-path deps. Deliberately NOT requirements.txt, which carries
# both source builds plus deepspeed/wandb/mosaicml/apex training machinery.
pip install -q \
  "diffusers==0.32.2" "transformers==4.48.0" "huggingface-hub>=0.26.2,<1.0" \
  "safetensors" "accelerate" "omegaconf==2.3.0" "einops==0.8.0" \
  "jaxtyping==0.2.28" "typeguard" "trimesh==4.3.2" "numpy==1.26.4" \
  "pillow==10.3.0" "scikit-image" "timm==0.9.16" "opencv-python-headless" \
  "pymeshlab" "PyMCubes" "rembg==2.0.65" "onnxruntime" \
  "pytorch-lightning==2.2.4" "lightning-utilities==0.11.2" \
  "bs4==0.0.2" "beautifulsoup4" "tqdm" "packaging" \
  "mosaicml-streaming==0.11.0" "imageio==2.34.1" "wandb==0.18.6" 2>&1 | tail -5

# TORCH GUARD, again: pytorch-lightning is the classic dep that quietly moves
# torch, and the torch_cluster wheel below is built for exactly 2.5.1+cu124.
python3 -c "import torch;assert torch.__version__.startswith('2.5.1'),torch.__version__" \
  || { echo "a dep MOVED TORCH — restoring the pin"; \
       pip install -q torch==2.5.1 torchvision==0.20.1 --index-url https://download.pytorch.org/whl/cu124 2>&1 | tail -2; }

# The FULL module-scope import set on the geometry pipeline chain, obtained by
# walking it with ast LOCALLY rather than discovering one dep per rented pod.
# The first attempt installed from a hand-read of the submodules and died on
# pytorch_lightning, which is imported at line 37 of the package __init__ — with
# bs4 queued behind it. Scan the chain, do not read the top of a file.
python3 -c "import diffusers,transformers,trimesh,rembg,pytorch_lightning,bs4,timm,skimage,pymeshlab,omegaconf,jaxtyping,typeguard,streaming,imageio,wandb;print('core deps ok')" || die CORE_DEPS

# ...AND `import pymeshlab` PROVES NOTHING. It imports cleanly with every one of
# its IO plugins dead, which is why the check above passed on the pod that then
# crashed in post-processing. Exercise the ACTUAL call the pipeline makes --
# trimesh -> temp .ply -> load_new_mesh -- so a missing plugin costs $0 instead
# of a full generation. Same class as the udf_ext/P3-SAM preflight lessons in
# CLAUDE.md, inverted: there the check was too strict, here it was too shallow.
python3 - <<'PY' || die PYMESHLAB_IO
import tempfile, os, trimesh, pymeshlab
m = trimesh.creation.icosphere(subdivisions=1)
p = os.path.join(tempfile.gettempdir(), "iotest.ply")
m.export(p)
ms = pymeshlab.MeshSet()
ms.load_new_mesh(p)                       # the exact call trimesh2pymeshlab makes
assert ms.current_mesh().vertex_number() == len(m.vertices)
print("pymeshlab PLY io ok (%d verts)" % ms.current_mesh().vertex_number())
PY

# diso: lazy, but it IS the surface extractor -> a geometry run needs it.
pip install -q diso 2>&1 | tail -3 || echo "diso pip failed"
python3 -c "import torch, diso; print('diso ok')" || die DISO
# torch_cluster: lazy (farthest-point sampling). Wheel index is per torch build.
pip install -q torch-cluster -f https://data.pyg.org/whl/torch-2.5.1+cu124.html 2>&1 | tail -3 \
  || echo "torch_cluster wheel unavailable — lazy import, continuing"
python3 -c "import torch, torch_cluster; print('torch_cluster ok')" || echo "torch_cluster ABSENT (lazy; may not be on the image path)"

# ASSERT THE GEOMETRY PIPELINE IMPORTS *BEFORE* SPENDING INFERENCE MINUTES, and
# import torch first — a torch extension only finds libc10 once torch is loaded
# (the udf_ext lesson that killed a $0.85 Direct3D-S2 run at minute 39).
cd /workspace/s1x
python3 - <<'PY' || die GEOM_IMPORT
import torch
from step1x3d_geometry.models.pipelines.pipeline import Step1X3DGeometryPipeline
print("geometry pipeline imports OK — no pytorch3d/nvdiffrast/kaolin needed")
PY

stage fetch_image
cd /workspace
curl -fsSL "$SB/public/$PRE/$IN_NAME" -o input.png || die FETCH_INPUT
python3 - <<'PY' || die INPUT_NOT_RGBA
import numpy as np
from PIL import Image
im = Image.open('/workspace/input.png')
print('input', im.size, im.mode)
assert im.mode == 'RGBA', f'need an RGBA cutout, got {im.mode}'
a = np.array(im)[:, :, 3]
assert not np.all(a == 255), 'alpha is all-255 — not a cutout'
print('alpha OK: %d levels, subject frac %.3f' % (len(np.unique(a)), float((a > 24).mean())))
PY

stage infer
cd /workspace/s1x
export HF_HOME=/workspace/hf
# OUR OWN DRIVER: the repo's inference.py imports the texture pipeline at module
# scope. Runs BOTH geometry models — the plain one and the LABEL one, which
# takes symmetry and edge_type. A van is bilaterally symmetric with hard panel
# edges, so symmetry='x' + edge_type='sharp' is the variant worth having; the
# plain model is the control that says whether the labels did anything.
python3 - <<'PY' 2>&1 | tail -40 || die INFER
import os, time, torch, trimesh
from step1x3d_geometry.models.pipelines.pipeline import Step1X3DGeometryPipeline

def run(sub, out, **kw):
    t0 = time.time()
    p = Step1X3DGeometryPipeline.from_pretrained(
        "stepfun-ai/Step1X-3D", subfolder=sub).to("cuda")
    g = torch.Generator(device=p.device); g.manual_seed(2025)
    r = p("/workspace/input.png", guidance_scale=7.5,
          num_inference_steps=50, generator=g, **kw)
    m = r.mesh[0]
    m.export(out)
    print(f"{sub}: {out} faces={len(m.faces)} verts={len(m.vertices)} "
          f"{time.time()-t0:.0f}s")
    del p; torch.cuda.empty_cache()

run("Step1X-3D-Geometry-1300m", "/workspace/step1x_base.glb")
run("Step1X-3D-Geometry-Label-1300m", "/workspace/step1x_label.glb",
    label={"symmetry": "x", "edge_type": "sharp"},
    octree_resolution=384, max_facenum=400000)
PY
[ -s /workspace/step1x_base.glb ] || die NO_BASE_OUTPUT

stage measure
ls -la /workspace/step1x_*.glb
for f in step1x_base step1x_label; do
  [ -s /workspace/$f.glb ] && sb_file $f.glb /workspace/$f.glb
done
python3 - <<'PY' 2>&1 | tail -20
import trimesh, numpy as np, os
for f in ("step1x_base","step1x_label"):
    p=f"/workspace/{f}.glb"
    if not os.path.exists(p): continue
    m=trimesh.load(p, force="mesh", process=False)
    a=m.face_adjacency_angles
    print(f"{f}: faces {len(m.faces)} verts {len(m.vertices)} "
          f"bbox {np.round(m.bounds[1]-m.bounds[0],3)} "
          f"sharp_share(>45deg) {float((a>np.pi/4).mean()):.4f} "
          f"watertight {m.is_watertight}")
PY

echo "=== STEP1X_OK ==="
report "log.txt"
sleep infinity
