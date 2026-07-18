#!/usr/bin/env bash
#
# clone_models.sh — fetch the licence-clear open-source models behind BuildScan AI.
#
# These are the building blocks identified in the tooling/model-sourcing research.
# Everything here is free and open source. The Apple capture layer (RoomPlan/ARKit)
# is NOT here because it is a proprietary Apple SDK — it cannot be cloned or forked;
# you consume it inside a native iOS app with an Apple Developer account.
#
# Usage:
#   ./models/clone_models.sh            # shallow clone (fast, latest main) into ./models/vendor
#   ./models/clone_models.sh --full     # full history (needed if you intend to fork/PR upstream)
#   ./models/clone_models.sh --pinned   # checkout the pinned commits in versions.lock (reproducible)
#
# The clones land in models/vendor/ which is git-ignored — we track this script and the
# manifest, not hundreds of MB of upstream code. To "upgrade" a model: re-run the script,
# or `cd models/vendor/<name> && git pull`, then re-pin with `git rev-parse HEAD`.

set -euo pipefail
cd "$(dirname "$0")"
DEST="vendor"
DEPTH="--depth 1"
MODE="latest"

for arg in "$@"; do
  case "$arg" in
    --full)   DEPTH="" ;;
    --pinned) MODE="pinned" ;;
    *) echo "unknown flag: $arg"; exit 1 ;;
  esac
done

mkdir -p "$DEST"

# name|repo|license|purpose
REPOS=(
  "TRELLIS|https://github.com/microsoft/TRELLIS.git|MIT|Image/text -> 3D (GLB). Concept-design visualisation ONLY."
  "TripoSR|https://github.com/VAST-AI-Research/TripoSR.git|MIT|Fast single-image -> 3D. Basis of this repo's worker."
  "Mask3D|https://github.com/JonasSchult/Mask3D.git|MIT|3D instance segmentation (mesh/point cloud -> semantic elements)."
  "PointTransformerV3|https://github.com/Pointcept/PointTransformerV3.git|MIT|SOTA point-cloud semantic segmentation backbone."
  "IfcOpenShell|https://github.com/IfcOpenShell/IfcOpenShell.git|LGPL-3.0|IFC read/write, geometry engine, quantity take-off."
)

clone_one() {
  local name="$1" repo="$2"
  if [ -d "$DEST/$name/.git" ]; then
    echo ">> $name already present — pulling latest"
    ( cd "$DEST/$name" && git pull --ff-only || true )
  else
    echo ">> cloning $name"
    git clone $DEPTH "$repo" "$DEST/$name"
  fi
}

for entry in "${REPOS[@]}"; do
  IFS='|' read -r name repo license purpose <<< "$entry"
  clone_one "$name" "$repo"
done

if [ "$MODE" = "pinned" ] && [ -f versions.lock ]; then
  echo ">> pinning to versions.lock"
  while IFS='|' read -r name sha; do
    [ -z "${name:-}" ] && continue
    case "$name" in \#*) continue ;; esac
    if [ -d "$DEST/$name/.git" ]; then
      ( cd "$DEST/$name" && git fetch --depth 1 origin "$sha" 2>/dev/null && git checkout "$sha" ) \
        || echo "   (could not pin $name to $sha — need --full history)"
    fi
  done < versions.lock
fi

echo
echo "Done. Clones are in models/$DEST/ (git-ignored)."
echo "Open3D is intentionally not cloned — install it as a library:  pip install open3d"
