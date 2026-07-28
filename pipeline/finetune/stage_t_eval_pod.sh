#!/bin/bash
# stage_t_eval_pod.sh — Alam-3D Stage T texture eval: stock TRELLIS.2 texture
# stage vs every intact Stage T checkpoint (sweep), same seed, same shape
# cascade, on the fixed eval photos. One GLB per (case x variant), uploaded
# incrementally to car-meshes/eval/<runid>/ for studio rendering + the owner's
# morning contact sheet.
#
# Isolation rule: ONLY tex_slat_flow_model_512 is swapped. Shape stages and the
# 1024 texture refiner stay stock in every variant, so any visual difference
# between tags is attributable to the Stage T checkpoint alone.
# Secrets (HF_TOKEN for gated DINOv3, SB_KEY for upload) arrive via pod env.
OUT=/root/alam3d_eval
EVAL_RUN_DIR="${EVAL_RUN_DIR:-/workspace/alam3d_stage_t_v1}"
CKPT_DIR="$EVAL_RUN_DIR/ckpts"
echo "EVAL RUN DIR: $EVAL_RUN_DIR"
mkdir -p "$OUT/logs"
if [ ! -d "$CKPT_DIR" ]; then
  echo "FATAL: $CKPT_DIR does not exist - nothing to evaluate"
  printf '{"step":"FATAL-no-run-dir"}' > "$OUT/logs/status.json"
  sleep infinity
fi
export EVAL_RUN_DIR
( cd "$OUT/logs" && python3 -m http.server 8000 >/dev/null 2>&1 & )
RUN_LOG="teval_$(hostname)_$(date -u +%Y%m%dT%H%M%SZ).log"
ln -sf "$RUN_LOG" "$OUT/logs/stage_b.log"   # launcher polls this name
exec > >(tee -a "$OUT/logs/$RUN_LOG") 2>&1
status(){ printf '{"step":"%s","at":"%s"}\n' "$1" "$(date -u +%FT%TZ)" > "$OUT/logs/status.json"; echo "===== $1 ====="; }

status boot
[ -f /etc/rp_environment ] && source /etc/rp_environment
export HF_TOKEN SB_KEY; export HUGGING_FACE_HUB_TOKEN="${HUGGING_FACE_HUB_TOKEN:-$HF_TOKEN}"
[ -n "$HF_TOKEN" ] && echo "HF token: present (${#HF_TOKEN} chars)" || echo "HF token: MISSING"
[ -n "$SB_KEY" ] && echo "SB key: present (${#SB_KEY} chars)" || echo "SB key: MISSING (uploads will be skipped)"
nvidia-smi -L || true
cd /app/TRELLIS.2 || { status FATAL-no-trellis2; sleep infinity; }
export PYTHONPATH=/app/TRELLIS.2:/app:$PYTHONPATH
pip install -q "transformers==4.57.6" || true

status arch-check
# The arch list is context, NOT the gate — this image lists sm_90 yet died on an
# H100 at the first F.conv2d (cuDNN ships its own kernels). Launch the real op.
python3 - <<'PYARCH' || { status FATAL-gpu-arch; sleep infinity; }
import sys
import torch
if not torch.cuda.is_available():
    print("FATAL: no CUDA device visible"); sys.exit(1)
name = torch.cuda.get_device_name(0)
cap = torch.cuda.get_device_capability(0)
have = f"sm_{cap[0]}{cap[1]}"
built = list(torch.cuda.get_arch_list())
print(f"GPU: {name}  compute={have}")
print(f"image built for: {' '.join(built) or '(none reported)'}")
if built and have not in built:
    print(f"note: {have} absent from the compiled arch list - relying on the "
          f"live kernel test below, not the list")
try:
    x = torch.randn(1, 3, 32, 32, device="cuda")
    w = torch.randn(8, 3, 3, 3, device="cuda")
    y = torch.nn.functional.conv2d(x, w)
    z = torch.randn(64, 64, device="cuda") @ torch.randn(64, 64, device="cuda")
    torch.cuda.synchronize()
    s = float(y.sum()) + float(z.sum())
except Exception as e:
    print(f"FATAL: kernel smoke test failed on {name} ({have}).")
    print(f"       {type(e).__name__}: {str(e)[:160]}")
    sys.exit(1)
print(f"arch OK: conv2d + matmul ran on {name} ({have})")
PYARCH

# Fail fast if the volume is out of quota — a silent quota error is what
# truncated Stage D's step-4000 checkpoint mid-save.
python3 - <<'PY' || { status FATAL-volume-quota; sleep infinity; }
import os, sys
p = "/workspace/_teval_quota_probe"
try:
    with open(p, "wb") as f:
        f.write(b"X" * 8_000_000); f.flush(); os.fsync(f.fileno())
    ok = open(p, "rb").read() == b"X" * 8_000_000
finally:
    try: os.remove(p)
    except Exception: pass
print("volume writable:", ok)
sys.exit(0 if ok else 1)
PY

status fetch-inputs
PUB=https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object/public/car-renders/finetune/eval_inputs
mkdir -p /root/eval_inputs/{gti,qashqai}
for i in 0 1 2 3; do
  curl -sf "$PUB/gti/$i.jpg"     -o /root/eval_inputs/gti/$i.jpg     || true
  curl -sf "$PUB/qashqai/$i.jpg" -o /root/eval_inputs/qashqai/$i.jpg || true
done
ls -la /root/eval_inputs/*/

status generate
python3 - <<'PY'
import glob, os, re, sys, time, types, zipfile, urllib.request
import importlib.util
import torch
from PIL import Image
sys.path.insert(0, "/app")

# Load the pipeline THROUGH the production handler to inherit its patches
# (ungated BiRefNet, DINOv3 feature fix). Stub runpod first.
_fake = types.ModuleType("runpod")
_fake.serverless = types.SimpleNamespace(start=lambda *a, **k: None)
sys.modules["runpod"] = _fake
spec = importlib.util.spec_from_file_location("handler", "/app/handler.py")
handler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(handler)

import o_voxel

OUT = "/root/alam3d_eval/logs"
RUN_DIR = os.environ.get("EVAL_RUN_DIR", "/workspace/alam3d_stage_t_v1")
pipeline = handler.get_image_pipeline()
PIPE = os.environ.get("EVAL_PIPE", "1024_cascade")
print("pipeline_type:", PIPE)

CASES = {
    "gti":     sorted(glob.glob("/root/eval_inputs/gti/*.jpg")),
    "qashqai": sorted(glob.glob("/root/eval_inputs/qashqai/*.jpg")),
}
CASES = {k: v for k, v in CASES.items() if v}
_only = [c for c in os.environ.get("EVAL_CASES", "").split(",") if c]
if _only:
    CASES = {k: v for k, v in CASES.items() if k in _only}
if not CASES:
    print("FATAL: no eval inputs downloaded"); sys.exit(1)
print("cases:", list(CASES))

RUNID = os.environ.get("EVAL_RUN_ID") or ("stage_t_" + time.strftime("%Y%m%dT%H%M", time.gmtime()))
_SB = os.environ.get("SB_KEY", "")
_pushed = []

def _push(local, name):
    if not _SB:
        print(f"  upload skipped (no SB_KEY): {name}", flush=True); return
    url = ("https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object/"
           f"car-meshes/eval/{RUNID}/{name}")
    try:
        with open(local, "rb") as fh:
            data = fh.read()
        rq = urllib.request.Request(url, data=data, method="POST")
        for h, v in (("apikey", _SB), ("Authorization", "Bearer " + _SB),
                     ("Content-Type", "model/gltf-binary"), ("x-upsert", "true")):
            rq.add_header(h, v)
        urllib.request.urlopen(rq, timeout=300).read()
        _pushed.append(name)
        print(f"  uploaded {name} -> car-meshes/eval/{RUNID}/ ({len(_pushed)} so far)", flush=True)
    except Exception as e:
        print(f"  UPLOAD FAILED {name}: {type(e).__name__} {str(e)[:80]}", flush=True)

def gen(case, paths, tag):
    imgs = [Image.open(p) for p in paths]
    torch.manual_seed(42)
    if len(imgs) > 1:
        from alam3d_multiview import run_multi_image
        meshes = run_multi_image(pipeline, imgs, seed=42, preprocess_image=True,
                                 pipeline_type=PIPE, num_samples=1)
    else:
        meshes = pipeline.run(imgs[0], seed=42, preprocess_image=True,
                              pipeline_type=PIPE, num_samples=1)
    mesh = max(meshes, key=lambda m: len(m.faces)) if len(meshes) > 1 else meshes[0]
    glb = o_voxel.postprocess.to_glb(
        vertices=mesh.vertices, faces=mesh.faces, attr_volume=mesh.attrs,
        coords=mesh.coords, attr_layout=mesh.layout, voxel_size=mesh.voxel_size,
        aabb=[[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]],
        decimation_target=120000, texture_size=2048,
        remesh=True, remesh_band=1, remesh_project=0, verbose=False)
    path = f"{OUT}/{case}_{tag}.glb"
    glb.export(path, extension_webp=False)
    kb = os.path.getsize(path) // 1024
    print(f"GLB {case}/{tag}: {kb}KB", flush=True)
    _push(path, f"{case}_{tag}.glb")

KTEX = "tex_slat_flow_model_512"
if KTEX not in pipeline.models:
    print(f"FATAL: pipeline has no model '{KTEX}' — keys: {list(pipeline.models)}")
    sys.exit(1)

# stock baseline first: every stage exactly as released
for case, paths in CASES.items():
    gen(case, paths, "stock")

# TEXTURE SWEEP. Load each intact Stage T checkpoint into the 512 texture
# stage only; zip-verify first (a truncated ckpt took down the 2026-07-27
# shape sweep at the fourth load). Missing tensors ABORT rather than silently
# evaluating a chimera of tuned+stock weights under a tuned tag.
stock_tex = {n: t.detach().cpu().clone()
             for n, t in pipeline.models[KTEX].state_dict().items()}
cks = sorted(glob.glob(f"{RUN_DIR}/ckpts/denoiser_ema*step*.pt"))
good, bad = [], []
for p in cks:
    try:
        with zipfile.ZipFile(p):
            pass
        good.append(p)
    except Exception as e:
        bad.append((os.path.basename(p), type(e).__name__))
for n, t in bad:
    print(f"  CORRUPT, skipping: {n} ({t})", flush=True)
if not good:
    print("FATAL: no loadable Stage T checkpoint"); sys.exit(1)
print(f"sweeping {len(good)} Stage T checkpoints (shape + tex-1024 stay stock)")
for p in good:
    m = re.search(r"step0*(\d+)", os.path.basename(p))
    tag = "t" + (m.group(1) if m else os.path.basename(p)[:4])
    sd = torch.load(p, map_location="cuda", weights_only=True)
    missing, unexpected = pipeline.models[KTEX].load_state_dict(sd, strict=False)
    print(f"{tag}: loaded {os.path.basename(p)} missing={len(missing)} unexpected={len(unexpected)}")
    if missing:
        print(f"FATAL: {len(missing)} tensors did not load for {tag} — aborting "
              f"rather than reporting stock weights as a fine-tune")
        sys.exit(1)
    del sd
    for case, paths in CASES.items():
        gen(case, paths, tag)
    pipeline.models[KTEX].load_state_dict(stock_tex, strict=False)
print("EVAL_GENERATION_COMPLETE")
PY
[ $? -ne 0 ] && { echo "GENERATE FAILED"; status FATAL-generate; sleep infinity; }

status DONE
ls -la "$OUT/logs/"*.glb 2>/dev/null
sleep infinity
