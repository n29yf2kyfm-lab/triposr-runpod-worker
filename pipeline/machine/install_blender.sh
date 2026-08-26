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
#   (measured on 4.5.12; 4.5.13 is a point release in the same LTS series)
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
# EEVEE NOW RUNS -- corrected 2026-08-25. This comment used to read "EEVEE STILL
# WILL NOT RUN. There is no EGL in this container", which was true of the
# container AS SHIPPED and was never re-tested after 4.5.12 landed. The missing
# piece was three apt packages, not a Blender limitation: libegl1 + libegl-mesa0
# + libgl1-mesa-dri give a software EGL that EEVEE Next initialises against.
# Verified BY PIXELS, which is the only way this project accepts a render claim:
# a 160px factory-startup frame came back with 132 unique colours and std 21,
# i.e. the default cube is actually there. EGL_BAD_MATCH warnings print during
# context selection and are non-fatal -- Blender retries and succeeds.
#
# CYCLES REMAINS THE VERDICT ENGINE. Every material ruling in CLAUDE.md -- the
# glazing tests, the white-tyre artefact, the red control -- was calibrated
# against Cycles output. EEVEE is now available for a fast preview; it is not a
# drop-in replacement for the eye, and swapping it in would invalidate the
# calibration those rulings rest on.
#
# Usage:  bash pipeline/machine/install_blender.sh [version]
#         export BLENDER_BIN=/opt/blender-4.5.13-linux-x64/blender
set -euo pipefail

# 4.5 LTS ONLY, and the default is the point release we are pinned to.
# Owner ruling 2026-08-26: bump 4.5.12 -> 4.5.13 LTS, do NOT install 5.x. The
# whole material-verdict calibration in CLAUDE.md was made on Cycles under the
# 4.5 LTS series, so a major-version jump would silently invalidate it; a point
# release inside the same LTS does not. Availability of this exact tarball was
# checked (HTTP 200) before the default was moved — the previous default is
# still reachable by passing it as $1 if a bisect is ever needed.
VER="${1:-4.5.13}"
SERIES="$(echo "$VER" | cut -d. -f1,2)"
DEST="/opt/blender-${VER}-linux-x64"
URL="https://download.blender.org/release/Blender${SERIES}/blender-${VER}-linux-x64.tar.xz"

# The shim lives in a function because BOTH paths through this script need it.
# The first version returned early on "already installed" and never reached the
# shim block at the bottom -- so a re-run on a container where /opt survived but
# /usr/local/bin did not would silently reinstall nothing. Caught by reading the
# script's own output after it printed "already installed" and did not mention
# the shim.
# Python deps the golfmk8 / integrity tools import. Omitting these cost a
# recovery cycle after rollback #11: the chain died one stage in on
# "ModuleNotFoundError: No module named 'PIL'" with everything else healthy.
PY_DEPS="Pillow scipy"

# EGL / software GL. Without these EEVEE cannot get a context and dies without
# raising a Python exception, which is how this container spent months believing
# EEVEE was impossible on 4.5. Cheap, idempotent, and a no-op once present, so it
# runs on BOTH paths through this script (fresh install and already-installed) --
# the same bug the shim function was factored out to avoid.
# Deliberately NOT pulling a driver: on a GPU host the vendor's libEGL is already
# there and takes precedence; mesa is the software fallback for a CPU container.
EGL_PKGS="libegl1 libegl-mesa0 libgl1-mesa-dri libgles2 libxi6 libxxf86vm1 libxfixes3 libxrender1"
install_egl() {
  if [ -e /usr/lib/x86_64-linux-gnu/libEGL.so.1 ]; then
    echo "EGL present: $(ls /usr/lib/x86_64-linux-gnu/libEGL*.so.* 2>/dev/null | head -1)"
    return 0
  fi
  command -v apt-get >/dev/null 2>&1 || { echo "EGL: no apt-get, skipping"; return 0; }
  echo "installing EGL/mesa for EEVEE"
  DEBIAN_FRONTEND=noninteractive apt-get install -y -q $EGL_PKGS >/dev/null 2>&1 \
    || echo "EGL: apt install failed -- CYCLES still works, EEVEE will not"
}

# ASSERT BY PIXELS, NOT BY EXIT CODE. An EEVEE render that writes a uniform
# frame exits 0 and looks exactly like success in a log; this project has been
# burned by silent no-ops often enough that a render claim is only accepted when
# the image varies. Non-fatal: EEVEE is a bonus, Cycles is the contract.
#
# MASK TO RGB. `img.pixels` is interleaved RGBA and alpha is 1.0 on every opaque
# pixel, so min/max over the raw list is pinned at ..1.000 by ALPHA and a
# uniform grey frame would pass. Caught in review 2026-08-26 and confirmed by
# measurement: the first version reported "range=0.220..1.000" and the 1.000 was
# the alpha channel — RGB alone is 0.220..0.737. The verdict was right and the
# evidence for it was partly meaningless, which is exactly the failure this
# function exists to prevent.
assert_eevee() {
  local bin="$1"
  cat > /tmp/_eevee_assert.py <<'PY'
import bpy, sys
sc = bpy.context.scene
for eng in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
    try:
        sc.render.engine = eng
        break
    except Exception:
        continue
else:
    print("EEVEE_UNAVAILABLE"); sys.exit(0)
sc.render.resolution_x = sc.render.resolution_y = 160
sc.view_settings.view_transform = 'Standard'
sc.render.filepath = '/tmp/_eevee_assert.png'
try:
    bpy.ops.render.render(write_still=True)
except Exception as e:
    print("EEVEE_RENDER_FAILED", type(e).__name__, e); sys.exit(0)
try:
    img = bpy.data.images.load('/tmp/_eevee_assert.png')
    px = list(img.pixels)
    n = img.channels
    rgb = px if n < 4 else px[0::n] + px[1::n] + px[2::n]   # DROP ALPHA
    lo, hi = min(rgb), max(rgb)
    print(f"EEVEE_PIXELS rgb={lo:.3f}..{hi:.3f} (alpha excluded)")
    print("EEVEE_ASSERT_OK" if hi - lo > 0.05 else "EEVEE_BLANK_FRAME")
except Exception as e:
    print("EEVEE_PIXEL_READ_FAILED", e)
PY
  # LIBGL_ALWAYS_SOFTWARE only where there is no GPU. Forcing it unconditionally
  # made the comment above ("on a GPU host the vendor's libEGL takes
  # precedence") FALSE under this function's own environment: llvmpipe would be
  # forced everywhere and the real driver path would never be exercised, so a
  # GPU host could pass this assert and still fail EEVEE in production.
  local soft=1
  command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L >/dev/null 2>&1 && soft=0
  echo "EEVEE assert: software GL=${soft}"
  LIBGL_ALWAYS_SOFTWARE=$soft EGL_PLATFORM=surfaceless "$bin" -b --factory-startup \
      --python /tmp/_eevee_assert.py 2>&1 | grep -E "EEVEE_|EGL Error" | tail -4
}
install_py_deps() {
  local bpy
  # DISCOVER the bundled python rather than hardcoding a version. The 4.5.12
  # path was baked in here, so installing 5.2.0 left the deps uninstalled and
  # said nothing about it.
  bpy="$(ls -d /opt/blender-*/[0-9].[0-9]*/python/bin/python3* 2>/dev/null | sort -V | tail -1)"
  [ -n "$bpy" ] || { echo "install_py_deps: no bundled python found" >&2; return 1; }
  echo "py deps into: $bpy"
  "$bpy" -m pip install --quiet $PY_DEPS 2>&1 | tail -1
  "$bpy" -c "from PIL import Image; import scipy, numpy; print('py deps OK')"
}

# THE SHIM MUST DISCOVER, NOT HARDCODE. It used to name
# /opt/blender-4.5.12-linux-x64/blender literally, so running this script with a
# different version installed the binary, asserted a denoised render on it, and
# then left `blender` resolving to the container's stripped 4.0.2 -- reporting
# "shim installed: Blender 4.0.2" as if that were success. Every tool in the
# repo calls plain `blender`, so the upgrade silently did nothing.
# Highest version present wins; BLENDER_BIN still overrides for an A/B.
install_shim() {
  cat > /usr/local/bin/blender <<'SHIM'
#!/usr/bin/env bash
# LD_LIBRARY_PATH IS NOT OPTIONAL ON 5.x. The glTF importer's Draco bridge
# (io_scene_gltf2/libbf_intern_draco_bridge.so) dlopens libdraco.so.9, which
# ships in the install's own lib/ directory but is NOT on the loader path. The
# result is a Draco-compressed GLB failing to import with
# "OSError: libdraco.so.9: cannot open shared object file" -- and most of this
# catalogue is Draco-compressed, so that is most cars.
run() {
  local bin="$1"; shift
  local dir; dir="$(dirname "$bin")"
  [ -d "$dir/lib" ] && export LD_LIBRARY_PATH="$dir/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
  exec "$bin" "$@"
}
# THE SHIM MUST NEVER EXEC ITSELF. Setting BLENDER_BIN=/usr/local/bin/blender is
# a completely natural thing for a caller to do — it is the path `which blender`
# reports — and the branch below would then exec this script again, forever.
# Hit for real 2026-08-26: a chain runner exported BLENDER_BIN=$SHIM and
# `blender --version` sat spinning for 87s inside a command substitution with no
# output and no error, which reads exactly like a slow start rather than a hang.
# Compare resolved paths, not strings, so a symlink or a relative path cannot
# sneak past.
_self="$(readlink -f "$0" 2>/dev/null || echo "$0")"
if [ -n "${BLENDER_BIN:-}" ] && [ -x "${BLENDER_BIN}" ]; then
  _want="$(readlink -f "$BLENDER_BIN" 2>/dev/null || echo "$BLENDER_BIN")"
  if [ "$_want" != "$_self" ]; then run "$BLENDER_BIN" "$@"; fi
fi
newest="$(ls -d /opt/blender-*-linux-x64/blender 2>/dev/null | sort -V | tail -1)"
[ -n "$newest" ] && [ -x "$newest" ] && run "$newest" "$@"
[ -x /usr/bin/blender ] && exec /usr/bin/blender "$@"
echo "blender-shim: no blender binary found" >&2; exit 127
SHIM
  chmod +x /usr/local/bin/blender
  echo "shim installed: $(blender --version 2>/dev/null | head -1) via $(command -v blender)"
}

if [ -x "$DEST/blender" ]; then
  echo "already installed: $($DEST/blender --version 2>/dev/null | head -1)"
  echo "BLENDER_BIN=$DEST/blender"
  install_shim
  install_py_deps
  install_egl
  assert_eevee "$DEST/blender"
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

# --- PATH SHIM -------------------------------------------------------------
# 28 call sites in this repo say `blender` -- subprocess calls, shell scripts,
# and the "Run: blender -b --python ..." lines in docstrings that people paste.
# Editing all of them is churn with a long tail of misses. /usr/local/bin
# precedes /usr/bin on this container's PATH (verified: index 9 vs 11), so one
# shim routes every one of them at once, with no code change.
#
# It falls back to /usr/bin/blender when the modern install is absent -- which
# is exactly the state right after a container rollback, before this script has
# been re-run -- so nothing ever hard-fails on a missing path. BLENDER_BIN
# overrides, which is how you pin a specific build for an A/B.
install_shim

# Fresh-install path also needs the tool dependencies, not just the binary.
install_py_deps
install_egl
assert_eevee "$DEST/blender"
