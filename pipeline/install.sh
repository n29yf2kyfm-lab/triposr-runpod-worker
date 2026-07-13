#!/usr/bin/env bash
# install.sh — install the free/open-source car-pipeline toolchain.
# Run from repo root. Safe to re-run (idempotent-ish). Nothing here is paid.
set -euo pipefail

echo "==> System packages (Debian/Ubuntu). On macOS use: brew install blender meshlab node"
if command -v apt-get >/dev/null 2>&1; then
  sudo apt-get update -y
  sudo apt-get install -y blender meshlab nodejs npm python3-pip \
       gimp krita inkscape || true         # GUI tools optional on a server
fi

echo "==> Python libs (PyMeshLab, Open3D, trimesh) — free, pip"
python3 -m pip install --user pymeshlab open3d trimesh numpy pillow scipy || true

echo "==> Node CLIs (glTF-Transform, validator, gltfpack, http-server, playwright, lighthouse)"
cd "$(dirname "$0")"
npm init -y >/dev/null 2>&1 || true
npm install @gltf-transform/cli @gltf-transform/core @gltf-transform/extensions \
            gltf-validator gltfpack http-server >/dev/null 2>&1 || true
npm install -D @playwright/test lighthouse >/dev/null 2>&1 || true
npx --yes playwright install chromium || true

echo "==> Instant Meshes (retopo, GPL) — download binary manually if needed:"
echo "    https://github.com/wjakob/instant-meshes/releases"
echo "==> Material Maker (procedural PBR, MIT) — https://github.com/RodZill4/material-maker/releases"
echo "==> KTX-Software / toktx (Basis+KTX2, Apache-2.0) — optional, enables GPU texture compression:"
echo "    https://github.com/KhronosGroup/KTX-Software/releases  (then re-run optimise.sh)"

echo "==> DONE. Verify:"
echo "    blender --version ; node -e \"require('gltf-validator')\" ; npx @gltf-transform/cli --version"
