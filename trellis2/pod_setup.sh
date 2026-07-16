#!/usr/bin/env bash
# Bootstrap a FRESH RunPod GPU pod into a working TRELLIS.2 worker and run a
# real end-to-end smoke test (text -> image -> 3D -> trim -> colour -> GLB).
#
# Pod requirements:
#   - GPU with >=24GB VRAM (A6000 / L40S / A100 / H100; 48GB recommended)
#   - a CUDA 12.4 *devel* image (nvcc needed to compile extensions), e.g.
#       runpod/pytorch:2.4.0-py3.10-cuda12.4.1-devel-ubuntu22.04
#   - ~60GB container/volume disk (weights are ~20GB, build artifacts a few GB)
#
# Usage on the pod (web terminal or SSH):
#   export GIT_TOKEN=github_pat_...     # only if the repo is private
#   export HF_TOKEN=hf_...              # required: gated repos (dinov3, RMBG-2.0)
#   bash <(curl -fsSL https://raw.githubusercontent.com/n29yf2kyfm-lab/triposr-runpod-worker/claude/custom-upgrade-path-2vszoo/trellis2/pod_setup.sh)
# ...or copy this file to the pod and: bash pod_setup.sh
#
# Everything is idempotent — safe to re-run after a failure.
set -euo pipefail

REPO="n29yf2kyfm-lab/triposr-runpod-worker"
BRANCH="${BRANCH:-claude/custom-upgrade-path-2vszoo}"
WORKDIR="${WORKDIR:-/workspace}"
# Prefer the mounted network volume for caches (matches the serverless
# convention, and gated models already cached there need no HF token).
if [ -d /runpod-volume ]; then
    export HF_HOME="${HF_HOME:-/runpod-volume/hf_cache}"
    export TORCH_HOME="${TORCH_HOME:-/runpod-volume/torch_cache}"
else
    export HF_HOME="${HF_HOME:-$WORKDIR/hf_cache}"
    export TORCH_HOME="${TORCH_HOME:-$WORKDIR/torch_cache}"
fi

# Progress beacon: when running unattended inside a RunPod pod (RUNPOD_POD_ID
# is auto-set) with RUNPOD_API_KEY in the env, publish each phase into the
# pod's own name so it's watchable from the outside via GET /v1/pods/<id>.
# NOTE: pass the account key as RUNPOD_ACCOUNT_KEY — RunPod injects its own
# pod-scoped RUNPOD_API_KEY into every pod, which shadows a same-named env
# and cannot rename pods (live-confirmed: the beacon stayed mute for 2h).
report() {
    [ -n "${RUNPOD_POD_ID:-}" ] && [ -n "${RUNPOD_ACCOUNT_KEY:-}" ] || return 0
    curl -s -X PATCH "https://rest.runpod.io/v1/pods/$RUNPOD_POD_ID" \
        -H "Authorization: Bearer $RUNPOD_ACCOUNT_KEY" \
        -H "Content-Type: application/json" \
        -d "{\"name\": \"t2-smoke-$1\"}" > /dev/null || true
}
trap 'report FAILED-see-log' ERR

report 1-sysdeps
echo "=== [1/7] System deps ==="
apt-get update -qq
apt-get install -y -qq --no-install-recommends git wget curl ninja-build \
    libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 ffmpeg libjpeg-dev

report 2-clone
echo "=== [2/7] Clone worker branch ==="
if [ ! -d "$WORKDIR/worker" ]; then
    CLONE_URL="https://github.com/$REPO.git"
    [ -n "${GIT_TOKEN:-}" ] && CLONE_URL="https://x-access-token:$GIT_TOKEN@github.com/$REPO.git"
    git clone -b "$BRANCH" "$CLONE_URL" "$WORKDIR/worker"
fi
cd "$WORKDIR/worker/trellis2"

report 3-pydeps
echo "=== [3/7] Python deps (torch 2.6.0 cu124 + TRELLIS.2 basics) ==="
pip install -q --upgrade pip "setuptools>=64" wheel ninja packaging
pip install -q torch==2.6.0 torchvision==0.21.0 --index-url https://download.pytorch.org/whl/cu124
pip install -q imageio imageio-ffmpeg tqdm easydict opencv-python-headless \
    trimesh transformers tensorboard pandas lpips zstandard kornia timm
pip install -q "git+https://github.com/EasternJournalist/utils3d.git@9a4eb15e4021b67b12c460c7057d642626897ec8"
pip install -q diffusers accelerate safetensors runpod requests

report 4-cudaext
echo "=== [4/7] CUDA extensions (GPU present -> nvcc auto-detects arch) ==="
export MAX_JOBS="${MAX_JOBS:-4}"
python -c "import flash_attn" 2>/dev/null || \
    pip install --no-build-isolation flash-attn==2.7.3
python -c "import nvdiffrast" 2>/dev/null || { \
    git clone -b v0.4.0 https://github.com/NVlabs/nvdiffrast.git /tmp/ext/nvdiffrast 2>/dev/null || true; \
    pip install --no-build-isolation /tmp/ext/nvdiffrast; }
python -c "import nvdiffrec" 2>/dev/null || { \
    git clone -b renderutils https://github.com/JeffreyXiang/nvdiffrec.git /tmp/ext/nvdiffrec 2>/dev/null || true; \
    pip install --no-build-isolation /tmp/ext/nvdiffrec; }
python -c "import cumesh" 2>/dev/null || { \
    git clone --recursive https://github.com/JeffreyXiang/CuMesh.git /tmp/ext/CuMesh 2>/dev/null || true; \
    pip install --no-build-isolation /tmp/ext/CuMesh; }
python -c "import flexgemm" 2>/dev/null || { \
    git clone --recursive https://github.com/JeffreyXiang/FlexGEMM.git /tmp/ext/FlexGEMM 2>/dev/null || true; \
    pip install --no-build-isolation /tmp/ext/FlexGEMM; }

report 5-ovoxel
echo "=== [5/7] o-voxel from OUR vendored source (eigen fetched pinned) ==="
EIGEN_DIR="TRELLIS.2/o-voxel/third_party/eigen"
if [ ! -f "$EIGEN_DIR/Eigen/Core" ]; then
    rm -rf "$EIGEN_DIR" && git init -q "$EIGEN_DIR"
    git -C "$EIGEN_DIR" remote add origin https://gitlab.com/libeigen/eigen.git
    git -C "$EIGEN_DIR" fetch -q --depth 1 origin 21e4582d1739107337a03460c81412981130373e
    git -C "$EIGEN_DIR" checkout -q FETCH_HEAD
fi
python -c "import o_voxel" 2>/dev/null || \
    pip install --no-build-isolation ./TRELLIS.2/o-voxel

report 6-preload
echo "=== [6/7] Preload all model weights (offline-readiness) ==="
python preload_models.py

report 7-smoketest
echo "=== [7/7] Smoke tests ==="
python test_handler.py   # mocked routing suite (29 checks)
# The real thing: one text->3D generation on the actual GPU. runpod's SDK
# runs the handler once with --test_input and exits.
export OFFLINE=1  # everything is preloaded; prove no network is needed
python handler.py --test_input '{"input": {"prompt": "a small toy car, high detail", "seed": 1, "decimation_target": 500000, "texture_size": 2048}}'

report OK
echo ""
echo "SUCCESS — worker runs end-to-end on this GPU with OFFLINE=1."
echo "GLB output: check the path printed above (OUTPUT_DIR)."
echo "Next: merge the PR so CI builds the serverless image, or keep serving"
echo "from this pod directly with: python handler.py --rp_serve_api"
