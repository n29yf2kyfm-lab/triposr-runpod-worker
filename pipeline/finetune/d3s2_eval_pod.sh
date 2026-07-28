#!/bin/bash
# d3s2_eval_pod.sh — audition Direct3D-S2 (DreamTechAI, MIT) as a GEOMETRY
# engine, on the exact photos the Alam-3D evals use, so its output lands on the
# same comparison sheet as stock TRELLIS.2 and the fine-tuned checkpoints.
#
# WHAT THIS IS AND IS NOT (verified against the repo on 2026-07-28, not the
# marketing): Direct3D-S2 generates SDF GEOMETRY ONLY. No texture stage, no
# PBR, no materials. The Neural4D product on top of it almost certainly adds
# proprietary texture stages that are NOT in the open release. So this
# audition judges one thing: whether its 1024^3 sparse geometry resolves car
# shape (shut lines, grille geometry, pillar sharpness) better than the
# TRELLIS.2 shape stage. It cannot judge texture, and it does not touch the
# Stage T texture training running in parallel.
#
# The meshes come out untextured; the render step will show them in the studio
# rig's neutral material. That is a fair geometry comparison and an unfair
# beauty comparison — the sheet must say so.
#
# Runs on a 24GB card (1024 res needs ~24GB per the repo). Outputs go to
# CONTAINER-LOCAL disk then straight to Supabase — the network volume is not
# needed and not written (Stage T owns it tonight).
#
# Secrets: SB_KEY via pod env only. Weights are public MIT (wushuang98/Direct3D-S2).
OUT=/root/d3s2_eval
RUNID=${D3S2_RUN_ID:-d3s2_$(date -u +%Y%m%dT%H%M)}
RES=${D3S2_RES:-1024}
mkdir -p "$OUT/logs"
( cd "$OUT/logs" && python3 -m http.server 8000 >/dev/null 2>&1 & )
# heredocs are quoted; python reads these from the environment
export RUNID D3S2_RES="$RES"
RUN_LOG="d3s2_$(hostname)_$(date -u +%Y%m%dT%H%M%SZ).log"
ln -sf "$RUN_LOG" "$OUT/logs/stage_b.log"   # launcher polls this name
exec > >(tee -a "$OUT/logs/$RUN_LOG") 2>&1
status(){ printf '{"step":"%s","at":"%s"}\n' "$1" "$(date -u +%FT%TZ)" > "$OUT/logs/status.json"; echo "===== $1 ====="; }

status boot
[ -f /etc/rp_environment ] && source /etc/rp_environment
export SB_KEY HF_TOKEN HUGGING_FACE_HUB_TOKEN 2>/dev/null
[ -n "$SB_KEY" ] && echo "SB key: present" || { echo "SB key MISSING - outputs could not be shipped"; status FATAL-no-sbkey; sleep infinity; }
nvidia-smi -L || true
export PYTHONUNBUFFERED=1

status arch-check
python3 - <<'PYARCH' || { status FATAL-gpu-arch; sleep infinity; }
import sys
import torch
if not torch.cuda.is_available():
    print("FATAL: no CUDA device visible"); sys.exit(1)
name = torch.cuda.get_device_name(0)
cap = torch.cuda.get_device_capability(0)
have = f"sm_{cap[0]}{cap[1]}"
print(f"GPU: {name}  compute={have}")
try:
    x = torch.randn(1, 3, 32, 32, device="cuda")
    w = torch.randn(8, 3, 3, 3, device="cuda")
    y = torch.nn.functional.conv2d(x, w)
    torch.cuda.synchronize()
    float(y.sum())
except Exception as e:
    print(f"FATAL: kernel smoke test failed: {type(e).__name__} {str(e)[:120]}"); sys.exit(1)
mem = torch.cuda.get_device_properties(0).total_memory / 1e9
print(f"arch OK; VRAM {mem:.0f}GB")
if mem < 20:
    print("FATAL: Direct3D-S2 at 1024 needs ~24GB; this card is too small"); sys.exit(1)
PYARCH

status install
# The repo builds custom sparse-attention CUDA ops. That needs nvcc; a runtime-
# only image would fail here in a confusing way, so check explicitly first.
which nvcc && nvcc --version | tail -1 || echo "note: nvcc not on PATH - trying anyway (prebuilt wheels may cover it)"
git clone --depth 1 https://github.com/DreamTechAI/Direct3D-S2.git /root/Direct3D-S2 \
  || { status FATAL-clone; sleep infinity; }
cd /root/Direct3D-S2
# Attempt 2's discovery step proved: setup.py does NOT declare the runtime
# deps (pipeline import dies on missing omegaconf) - they live in
# requirements.txt - and direct3d_s2.utils needs udf_ext, a custom CUDA
# extension with its own setup.py. Install all three layers explicitly.
pip install -q rembg onnxruntime trimesh omegaconf einops ninja || true
# Attempt 3 failed on pip BUILD ISOLATION: several of their deps (and the
# third_party extensions) import torch in setup.py, and pip builds them in an
# isolated venv that has no torch - "No module named 'torch'" from inside a
# pip subprocess. --no-build-isolation lets builds see the image's torch.
# Their requirements may also pin torch itself; installing that would replace
# the image's CUDA-matched stack, so torch lines are filtered out first.
if [ -f requirements.txt ]; then
  echo "--- requirements.txt (verbatim) ---"; cat requirements.txt; echo "---"
  grep -viE "^torch([=<>~ ]|$)|^torchvision|^torchaudio" requirements.txt > /tmp/req_safe.txt
  pip install --no-build-isolation -r /tmp/req_safe.txt 2>&1 | tail -8
fi
pip install --no-build-isolation -e . 2>&1 | tail -5
# build every nested extension the repo carries (voxelize, udf_ext, ...)
find . -mindepth 2 -maxdepth 5 -name setup.py | while read -r s; do
  d=$(dirname "$s")
  echo "building extension: $d"
  ( cd "$d" && pip install --no-build-isolation -e . 2>&1 | tail -3 ) \
    || echo "  extension build FAILED: $d (continuing - may be optional)"
done
# import check from OUTSIDE the repo dir: attempt 2's check passed vacuously
# because cwd=/root/Direct3D-S2 shadows a failed pip install with the raw
# source tree, deps unchecked.
( cd /root && python3 -c "import direct3d_s2, omegaconf; print('import OK from clean cwd')" ) \
  || { echo "FATAL: package (or its deps) do not import from a clean cwd";
       status FATAL-install; sleep infinity; }

status fetch-inputs
PUB=https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object/public/car-renders/finetune/eval_inputs
mkdir -p /root/eval_inputs/{gti,qashqai}
for i in 0 1 2 3; do
  curl -sf "$PUB/gti/$i.jpg"     -o /root/eval_inputs/gti/$i.jpg     || true
  curl -sf "$PUB/qashqai/$i.jpg" -o /root/eval_inputs/qashqai/$i.jpg || true
done
ls -la /root/eval_inputs/gti /root/eval_inputs/qashqai
[ -s /root/eval_inputs/gti/0.jpg ] && [ -s /root/eval_inputs/qashqai/0.jpg ] \
  || { echo "FATAL: eval photos missing from bucket"; status FATAL-inputs; sleep infinity; }

status api-discovery
# The first attempt died 16 seconds in, at import time — before any of the
# defensive call-signature logic could help — because the import path was
# INFERRED from the README. Stop inferring: read the installed package and the
# repo's own example code, print what actually exists, and write the findings
# where the generate step can use them.
python3 - <<'PY' || { status FATAL-api-discovery; sleep infinity; }
import glob, importlib, inspect, json, pkgutil, sys

import direct3d_s2
print("package file:", direct3d_s2.__file__)
mods = [m.name for m in pkgutil.walk_packages(direct3d_s2.__path__, "direct3d_s2.")]
print("modules:", mods)
found = []
for name in mods:
    try:
        mod = importlib.import_module(name)
    except Exception as e:
        print(f"  {name}: import failed ({type(e).__name__}: {str(e)[:60]})")
        continue
    for cname, obj in inspect.getmembers(mod, inspect.isclass):
        if "Pipeline" in cname and obj.__module__ == name:
            has_fp = hasattr(obj, "from_pretrained")
            found.append({"module": name, "cls": cname, "from_pretrained": has_fp})
            print(f"  candidate: {name}.{cname} (from_pretrained={has_fp})")
print("repo example files:")
for f in glob.glob("/root/Direct3D-S2/*.py") + glob.glob("/root/Direct3D-S2/app*.py"):
    print(f"--- {f} (first 40 lines) ---")
    print("\n".join(open(f, errors="ignore").read().splitlines()[:40]))
if not found:
    print("FATAL: no Pipeline class found anywhere in the installed package")
    sys.exit(1)
json.dump(found, open("/root/d3s2_api.json", "w"))
PY

status generate
python3 - <<'PY' || { echo "GENERATE FAILED"; status FATAL-generate; sleep infinity; }
import importlib, json, os, sys, time, traceback, urllib.request

import torch
from PIL import Image

# Direct3D-S2 is single-image; photo 0 of each case is the same front-3/4 the
# TRELLIS evals lead with, which keeps the comparison same-photo.
CASES = [("gti", "/root/eval_inputs/gti/0.jpg"),
         ("qashqai", "/root/eval_inputs/qashqai/0.jpg")]
RES = int(os.environ.get("D3S2_RES", "1024"))
RUNID = os.environ["RUNID"]
SB = os.environ["SB_KEY"]
OUT = "/root/d3s2_eval"

def push_bytes(data, name, ctype):
    url = ("https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object/"
           f"car-meshes/eval/{RUNID}/{name}")
    rq = urllib.request.Request(url, data=data, method="POST")
    for h, v in (("apikey", SB), ("Authorization", "Bearer " + SB),
                 ("Content-Type", ctype), ("x-upsert", "true")):
        rq.add_header(h, v)
    urllib.request.urlopen(rq, timeout=300).read()

def die(stage, exc):
    """The watchdog deletes FATAL pods fast; the traceback must outlive the
    pod, so ship it to the bucket before exiting."""
    tb = f"stage: {stage}\n{traceback.format_exc()}"
    print(tb, flush=True)
    try:
        push_bytes(tb.encode(), "ERROR.txt", "text/plain")
        print("traceback archived to the eval bucket", flush=True)
    except Exception:
        print("traceback archive ALSO failed", flush=True)
    sys.exit(1)

try:
    cands = json.load(open("/root/d3s2_api.json"))
    pipe = None
    for c in [c for c in cands if c["from_pretrained"]] or cands:
        try:
            cls = getattr(importlib.import_module(c["module"]), c["cls"])
            for sub in ("direct3d-s2-v-1-1", "direct3d-s2-v-1-0", None):
                try:
                    pipe = (cls.from_pretrained("wushuang98/Direct3D-S2", subfolder=sub)
                            if sub else cls.from_pretrained("wushuang98/Direct3D-S2"))
                    print(f"loaded {c['module']}.{c['cls']} subfolder={sub}", flush=True)
                    break
                except Exception as e:
                    print(f"  load rejected ({c['cls']}, {sub}): {str(e)[:80]}", flush=True)
            if pipe is not None:
                break
        except Exception as e:
            print(f"  candidate failed ({c['module']}.{c['cls']}): {str(e)[:80]}", flush=True)
    if pipe is None:
        raise RuntimeError("no pipeline candidate could load the released weights")
    pipe.to("cuda")
    print("pipeline on GPU", flush=True)
except SystemExit:
    raise
except Exception as e:
    die("pipeline-load", e)

def push(local, name):
    with open(local, "rb") as fh:
        push_bytes(fh.read(), name, "model/gltf-binary")
    print(f"  uploaded {name}", flush=True)

def run_pipe(photo):
    """The call signature is inferred from the README, and inference is not
    knowledge: try the documented form first, then the obvious variants, and
    print which one actually worked so the log records the real API."""
    img = Image.open(photo).convert("RGB")
    attempts = [
        ("PIL + sdf_resolution + rembg", lambda: pipe(img, sdf_resolution=RES, remove_background=True)),
        ("PIL + sdf_resolution",         lambda: pipe(img, sdf_resolution=RES)),
        ("path + sdf_resolution",        lambda: pipe(photo, sdf_resolution=RES)),
        ("path only",                    lambda: pipe(photo)),
    ]
    last = None
    for name, fn in attempts:
        try:
            out = fn()
            print(f"  call signature that worked: {name}", flush=True)
            return out
        except TypeError as e:
            last = e
            print(f"  signature rejected ({name}): {str(e)[:80]}", flush=True)
    raise last

try:
  for case, photo in CASES:
    t0 = time.time()
    out = run_pipe(photo)
    mesh = out["mesh"] if isinstance(out, dict) else getattr(out, "mesh", out)
    # ship GLB so the render worker treats it exactly like every other eval mesh
    import trimesh
    if not isinstance(mesh, trimesh.Trimesh):
        mesh = trimesh.Trimesh(vertices=mesh.vertices, faces=mesh.faces)
    path = f"{OUT}/{case}_d3s2.glb"
    mesh.export(path)
    kb = os.path.getsize(path) // 1024
    print(f"GLB {case}: {kb}KB in {time.time()-t0:.0f}s "
          f"({len(mesh.vertices)} verts, {len(mesh.faces)} faces)", flush=True)
    push(path, f"{case}_d3s2.glb")   # ship immediately - the incremental lesson
except SystemExit:
  raise
except Exception as e:
  die("generate-loop", e)

print("D3S2_GENERATE_OK", flush=True)
PY

status DONE
sleep infinity
