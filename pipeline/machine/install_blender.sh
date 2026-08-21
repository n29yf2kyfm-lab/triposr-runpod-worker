#!/usr/bin/env bash
# install_blender.sh — put a MODERN Blender on this container, and keep it.
#
# WHY THIS EXISTS. The container ships Blender 4.0.2 as a STRIPPED system
# binary: no OpenImageDenoise on disk at all, and `cycles.compute_device_type`
# enumerates empty. CLAUDE.md has carried the note "this build has no OIDN, so
# use_denoising=True raises RuntimeError and the render dies AFTER 'Blender
# quit' prints" for weeks, and every render this project has ever produced was
# made WITHOUT a denoiser — which is why sample counts of 40-52 were needed and
# the results were still grainy.
#
# Measured on 2026-08-21 with the merged Golf through eyeball_views.py:
#   4.0.2,  52 samples, no denoiser  -> visible grain across the paint
#   4.5.12, 16 samples, DENOISED     -> visibly cleaner at 3.25x fewer samples
#
# The second reason is bigger than render quality. The free GPL Class-A add-ons
# this project would need to hand-build car bodies -- Surface Mesh (curve-network
# panel surfacing), Surface Diagnostics (zebra / isoangle / draft / sections),
# Surface Psycho (NURBS with continuity control and STEP I/O), Hardflow, PolyQuilt,
# PDT -- are distributed through the EXTENSIONS PLATFORM, which starts at 4.2 LTS.
# None of them can install on 4.0.2. The free tier was blocked by our own
# two-year-old binary, not by the ecosystem.
#
# INSTALLS ALONGSIDE, NOT OVER. /usr/bin/blender is left exactly as it was, so
# anything mid-flight keeps working. Point tooling at $BLENDER_BIN.
#
# ROLLBACK-PROOF BY DESIGN. This container has rolled back six times in one
# session, each time discarding /opt. Re-run this script after a rollback; it is
# idempotent and takes about a minute. That is the whole point of it being a
# script in the repo rather than a thing someone did once by hand.
#
# EEVEE STILL WILL NOT RUN. There is no EGL in this container, so EEVEE/EEVEE
# Next cannot initialise on 4.5 either -- it dies without even raising a Python
# exception. CYCLES ON CPU IS STILL THE ONLY WORKING ENGINE. What changes is
# that Cycles now has its denoiser.
#
# Usage:  bash pipeline/machine/install_blender.sh [version]
#         export BLENDER_BIN=/opt/blender-4.5.12-linux-x64/blender
set -euo pipefail

VER="${1:-4.5.12}"
SERIES="$(echo "$VER" | cut -d. -f1,2)"
DEST="/opt/blender-${VER}-linux-x64"
URL="https://download.blender.org/release/Blender${SERIES}/blender-${VER}-linux-x64.tar.xz"

if [ -x "$DEST/blender" ]; then
  echo "already installed: $($DEST/blender --version 2>/dev/null | head -1)"
  echo "BLENDER_BIN=$DEST/blender"
  exit 0
fi

echo "fetching $URL"
curl -sSL --max-time 900 -o /tmp/blender.tar.xz "$URL"
# A truncated download extracts to a binary that segfaults with no useful
# message, which is a miserable thing to debug. Check the size first.
SZ=$(stat -c%s /tmp/blender.tar.xz)
[ "$SZ" -gt 200000000 ] || { echo "FAIL: download only ${SZ}B, expected >200MB"; exit 1; }
tar -xf /tmp/blender.tar.xz -C /opt
rm -f /tmp/blender.tar.xz
[ -x "$DEST/blender" ] || { echo "FAIL: no binary at $DEST/blender"; exit 1; }

# ASSERT THE THING WE CAME FOR. A Blender that installs but cannot denoise is
# the same as the one we already had, and this project's standing rule is that
# a gate nobody tested does not exist -- so test it, on an actual render.
ls "$DEST/lib/" | grep -q libOpenImageDenoise || { echo "FAIL: no OIDN in $DEST/lib"; exit 1; }
cat > /tmp/_bl_assert.py <<'PY'
import bpy
sc = bpy.context.scene
sc.render.engine = 'CYCLES'
sc.cycles.device = 'CPU'
sc.cycles.use_denoising = True
sc.cycles.denoiser = 'OPENIMAGEDENOISE'
sc.cycles.samples = 8
sc.render.resolution_x = sc.render.resolution_y = 160
sc.view_settings.view_transform = 'Standard'   # never AgX; it has produced
sc.render.filepath = '/tmp/_bl_assert.png'     # false verdicts three times here
bpy.ops.render.render(write_still=True)
print("BLENDER_DENOISE_ASSERT_OK")
PY
"$DEST/blender" -b --python /tmp/_bl_assert.py 2>&1 | grep -q BLENDER_DENOISE_ASSERT_OK \
  || { echo "FAIL: installed, but a denoised CYCLES render did not complete"; exit 1; }

echo "installed: $($DEST/blender --version 2>/dev/null | head -1)"
echo "denoised CYCLES render: OK"
echo
echo "  export BLENDER_BIN=$DEST/blender"
echo
echo "system /usr/bin/blender left untouched at $(/usr/bin/blender --version 2>/dev/null | head -1)"
