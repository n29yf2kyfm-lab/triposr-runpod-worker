#!/usr/bin/env bash
# hy_pod_bootstrap.sh — Hunyuan3D-2 shape generation on a rented RunPod GPU.
#
# WHY A POD AND NOT THIS CONTAINER. The same model was run locally on 4 CPU
# cores and took 5 hours 14 minutes for one car. On a GPU it is minutes. It also
# needs ~4GB of weights on a box that has repeatedly hit 100% disk, and this
# container has rolled back six times in one session -- the last rollback threw
# away that 5-hour mesh because it existed only on local disk.
#
# EVERY TRAP BELOW IS ONE THIS PROJECT HAS ALREADY PAID FOR (CLAUDE.md):
#
#   * A POD WHOSE START COMMAND EXITS GETS RESTARTED. Ending with `sleep 120`
#     and exiting put a pod in a re-clone/re-download loop that never finished
#     and billed until noticed. This script never exits on its own; the caller
#     terminates the pod explicitly.
#   * SUPABASE SIGNED UPLOAD URLS ARE ONE-TIME. A restart loop burns the single
#     shot on whichever attempt finishes first, so this uses a service key and
#     uploads as many times as it likes.
#   * HUNYUAN'S requirements.txt BREAKS THE IMAGE'S TORCH. Dependencies are
#     installed one by one, and `import torch; torch.cuda.is_available()` is
#     ASSERTED afterwards -- a broken torch otherwise surfaces as an unrelated
#     error deep in the pipeline.
#   * pymeshlab MUST BE INSTALLED even though its postprocessor is not used.
#     hy3dgen imports it at MODULE LOAD, so leaving it out on the theory that
#     "we skip that step" failed the first rented pod 90 seconds in with
#     ModuleNotFoundError. It also needs libOpenGL.so.0, installed in the apt
#     phase, or it imports but cannot load its plugins.
#   * ASSERT ON ARTEFACTS. A run that exits 0 having written nothing must not
#     read as success, so a missing mesh writes FAIL_NO_MESH and that marker is
#     what the caller checks.
#   * LOGS UPLOAD ON EVERY PHASE, so a failure names its own cause instead of
#     needing another rented GPU to reproduce.
#
# TEXTURE IS DELIBERATELY NOT RUN. hunyuan3d-paint needs custom_rasterizer and a
# differentiable renderer compiled on the pod, which is a long build with its own
# failure modes. The shape is what was soft, and paint is applied afterwards by
# r10_polish, which is proven. Do not add texture generation here without
# budgeting for that build.
#
# Env expected: SB_KEY, RUN_ID, PLATE_URL, HY_STEPS, HY_OCT, HY_MODEL, HY_SUB
set -u
RUN_ID="${RUN_ID:-hy1}"
SB="https://tfkvthprsntexrcuqpyd.supabase.co"
BUCKET="car-meshes"
PREFIX="gen/v1/${RUN_ID}"
LOG=/workspace/boot.log
mkdir -p /workspace
exec > >(tee -a "$LOG") 2>&1

up() {  # up <localfile> <destname> <content-type>
  [ -f "$1" ] || return 0
  curl -s -X POST "$SB/storage/v1/object/$BUCKET/$PREFIX/$2" \
    -H "apikey: $SB_KEY" -H "Authorization: Bearer $SB_KEY" \
    -H "Content-Type: $3" -H "x-upsert: true" \
    --data-binary "@$1" -o /dev/null -w "upload $2 %{http_code}\n"
}
phase() { echo "=== PHASE $* $(date -u +%T)"; up "$LOG" boot.log text/plain; }

phase START
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader || echo "no nvidia-smi"

phase APT
apt-get update -qq && apt-get install -y -qq git libgl1 libopengl0 libglib2.0-0 >/dev/null 2>&1
echo "apt rc=$?"

phase PIP
python3 -m pip install -q --no-cache-dir \
  diffusers "transformers<4.50" "huggingface-hub<1.0,>=0.26.0" accelerate \
  omegaconf einops trimesh scikit-image opencv-python-headless rembg onnxruntime \
  pymeshlab
echo "pip rc=$?"

phase ASSERT_TORCH
python3 - <<'PY' || { echo "FAIL_TORCH"; up "$LOG" boot.log text/plain; sleep infinity; }
import torch
print("torch", torch.__version__, "cuda", torch.cuda.is_available())
assert torch.cuda.is_available(), "no CUDA after dependency install"
print("gpu", torch.cuda.get_device_name(0))
PY

phase CLONE
cd /workspace
[ -d hy3d ] || git clone -q --depth 1 https://github.com/Tencent-Hunyuan/Hunyuan3D-2.git hy3d
ls hy3d/hy3dgen >/dev/null || { echo "FAIL_CLONE"; up "$LOG" boot.log text/plain; sleep infinity; }

phase WEIGHTS
python3 - <<PY
from huggingface_hub import snapshot_download
# model.fp16.safetensors BY NAME, not *.safetensors. hunyuan3d-dit-v2-0 holds
# SIX copies of the same weights -- model.ckpt, model.fp16.ckpt, model_fp16.ckpt,
# model.safetensors and model.fp16.safetensors -- so a *.safetensors pattern
# pulls 9.8GB for a 4.9GB need, and from_pretrained with no pattern at all pulls
# nearly 25GB. That is the mistake that filled a 6.8GB disk locally.
p = snapshot_download("${HY_MODEL:-tencent/Hunyuan3D-2}",
    allow_patterns=["${HY_SUB:-hunyuan3d-dit-v2-0}/model.fp16.safetensors",
                    "${HY_SUB:-hunyuan3d-dit-v2-0}/config.yaml",
                    "hunyuan3d-vae-v2-0/model.fp16.safetensors",
                    "hunyuan3d-vae-v2-0/config.yaml"],
    local_dir="/workspace/hyw")
print("weights at", p)
PY
du -sh /workspace/hyw 2>/dev/null; df -h /workspace | tail -1

phase PLATE
curl -sL -o /workspace/plate.png "${PLATE_URL}"
python3 -c "from PIL import Image; im=Image.open('/workspace/plate.png'); print('plate', im.size, im.mode)" \
  || { echo "FAIL_PLATE"; up "$LOG" boot.log text/plain; sleep infinity; }

phase GENERATE
cd /workspace
python3 - <<PY
import sys, time, torch
sys.path.insert(0, '/workspace/hy3d')
from hy3dgen.shapegen import Hunyuan3DDiTFlowMatchingPipeline
from hy3dgen.rembg import BackgroundRemover
from PIL import Image

pipe = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(
    "/workspace/hyw", subfolder="${HY_SUB:-hunyuan3d-dit-v2-0}",
    use_safetensors=True, device="cuda")
img = Image.open("/workspace/plate.png").convert("RGB")
# BACKGROUND REMOVAL ONLY. The pipeline runs its own centring processor on
# whatever it is handed; pre-centring makes it process an already-processed
# image and it dies in cv2.resize.
img = BackgroundRemover()(img)
print("plate after rembg", img.mode, img.size, flush=True)
t = time.time()
mesh = pipe(image=img, num_inference_steps=int("${HY_STEPS:-50}"),
            octree_resolution=int("${HY_OCT:-384}"),
            mc_algo="mc", generator=torch.manual_seed(1234))[0]
print(f"GEN_SECONDS {time.time()-t:.0f}", flush=True)
mesh.export("/workspace/mesh.glb")
print("MESH verts", len(mesh.vertices), "faces", len(mesh.faces), flush=True)
PY

phase UPLOAD
if [ -s /workspace/mesh.glb ]; then
  up /workspace/mesh.glb mesh.glb model/gltf-binary
  up /workspace/plate.png plate.png image/png
  echo "DONE $(date -u +%FT%TZ)" > /workspace/DONE
  up /workspace/DONE DONE text/plain
  echo "BOOTSTRAP_OK"
else
  echo "FAIL_NO_MESH"
  echo "FAIL_NO_MESH $(date -u +%FT%TZ)" > /workspace/DONE
  up /workspace/DONE DONE text/plain
fi
up "$LOG" boot.log text/plain

# NEVER EXIT. An exiting start command is restarted by RunPod, which re-clones,
# re-downloads and re-runs forever. The caller terminates this pod.
phase IDLE
sleep infinity
