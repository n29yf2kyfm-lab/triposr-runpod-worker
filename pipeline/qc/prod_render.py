"""prod_render.py — render a GLB through the REAL render/handler.py locally.

WHY THIS LIVES IN THE REPO: it has been rewritten from scratch FOUR times after
scratchpad rollbacks (CLAUDE.md: "assume local disk will be lost"). It is the
only way to judge a mesh under the shipping rig rather than under a preview
renderer, so it is worth keeping.

It does three things and nothing else:
  1. stubs `runpod` and `requests` so importing the handler starts no server
     and makes no network call;
  2. patches the ONE `use_denoising = True` line (local Blender builds have no
     OIDN) behind an assert that there was EXACTLY one — if the handler grows a
     second, this fails loudly rather than silently patching the wrong line;
  3. execs the real handler source and calls its real `_render`.

The handler reads its HDRI from $HDRI_PATH, defaulting to the container path
/app/assets/hdri.hdr which does not exist here. Point it at the repo copy:

  HDRI_PATH=render/assets/hdri.hdr \
  xvfb-run -a blender -b --factory-startup -noaudio -P pipeline/qc/prod_render.py -- \
      render/handler.py car.glb out.png 215 [samples] [colour]

POSE: the handler expects a glTF Y-up mesh sitting on the ground. It will NOT
stand up a mesh that is upside down — that is ingest's job (pipeline/ingest/
pose_fix.py). A wheels-up render here means the FILE is wrong; verify with
pipeline/qc/quad_views.py before blaming the rig (measured 2026-08-14: a
near-tie up-axis test produced exactly that false alarm).
"""
import os
import sys
import types

argv = sys.argv[sys.argv.index("--") + 1:]
if len(argv) < 4:
    raise SystemExit(__doc__)
HANDLER, GLB, OUT, AZ = argv[0], argv[1], argv[2], float(argv[3])
SAMPLES = int(argv[4]) if len(argv) > 4 else 48
COLOUR = argv[5] if len(argv) > 5 else None

runpod = types.ModuleType("runpod")
runpod.serverless = types.SimpleNamespace(start=lambda *a, **k: None)
sys.modules["runpod"] = runpod

requests = types.ModuleType("requests")


def _no_net(*a, **k):
    raise RuntimeError("network disabled in local harness")


requests.get = requests.post = _no_net
sys.modules["requests"] = requests

src = open(HANDLER).read()
n = src.count("use_denoising = True")
assert n == 1, f"expected exactly 1 denoising line, found {n} — re-read handler"
src = src.replace("use_denoising = True",
                  "use_denoising = False  # local harness: no OIDN in this build")

mod = types.ModuleType("handler_under_test")
mod.__file__ = HANDLER
exec(compile(src, HANDLER, "exec"), mod.__dict__)

bpy = mod._load_bpy()
device, recolour_info, plate_end_used, pose_info = mod._render(
    bpy, GLB, OUT,
    colour=COLOUR, plate_reg=None,
    az_deg=AZ, elev=0.15, zfrac=0.32,
    samples=SAMPLES, resx=900, resy=562,
    bright=False, studio=True, finish=None,
    recolour_mode="auto", plate_end="auto",
    plates_both=False, audit=False,
    glass_tint=None, fill_strength=None)
print(f"HARNESS_OK device={device} out={OUT} size={os.path.getsize(OUT)}")
print(f"RECOLOUR {recolour_info}")
print(f"POSE {pose_info}")
