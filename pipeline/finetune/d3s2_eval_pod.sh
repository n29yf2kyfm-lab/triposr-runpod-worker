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
pip install -q rembg onnxruntime trimesh || true
# torchsparse-style deps + the package itself; surface the real error if it dies
pip install -e . 2>&1 | tail -15
python3 -c "import direct3d_s2" \
  || { echo "FATAL: package did not import after install - see pip output above";
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

status generate
python3 - <<'PY' || { echo "GENERATE FAILED"; status FATAL-generate; sleep infinity; }
import os, sys, time, urllib.request

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

from direct3d_s2.pipeline import Direct3DS2Pipeline
pipe = Direct3DS2Pipeline.from_pretrained("wushuang98/Direct3D-S2",
                                          subfolder=f"direct3d-s2-v-1-1")
pipe.to("cuda")
print("pipeline loaded", flush=True)

def push(local, name):
    url = ("https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object/"
           f"car-meshes/eval/{RUNID}/{name}")
    with open(local, "rb") as fh:
        data = fh.read()
    rq = urllib.request.Request(url, data=data, method="POST")
    for h, v in (("apikey", SB), ("Authorization", "Bearer " + SB),
                 ("Content-Type", "model/gltf-binary"), ("x-upsert", "true")):
        rq.add_header(h, v)
    urllib.request.urlopen(rq, timeout=300).read()
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

print("D3S2_GENERATE_OK", flush=True)
PY

status DONE
sleep infinity
