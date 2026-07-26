#!/bin/bash
# stage_c_eval_pod.sh — Alam-3D Stage C eval: base TRELLIS.2-4B vs our
# fine-tuned checkpoint, same seed, on the fixed eval set (Golf 4-view,
# Tesla Model 3 side single-view, unseen Ford Escape/Kuga 4-view).
# Produces 6 GLBs (3 cases x base/alam3d) and uploads them to the
# car-meshes bucket under eval/ for rendering + human review.
# Secrets (HF_TOKEN for gated DINOv3, SB_KEY for upload) arrive via pod env.
OUT=/workspace/alam3d_eval
CKPT_DIR=/workspace/alam3d_stage_c/ckpts
mkdir -p "$OUT/logs"
( cd "$OUT/logs" && python3 -m http.server 8000 >/dev/null 2>&1 & )
RUN_LOG="eval_$(hostname)_$(date -u +%Y%m%dT%H%M%SZ).log"
ln -sf "$RUN_LOG" "$OUT/logs/stage_b.log"   # launcher polls this name
exec > >(tee -a "$OUT/logs/$RUN_LOG") 2>&1
status(){ printf '{"step":"%s","at":"%s"}\n' "$1" "$(date -u +%FT%TZ)" > "$OUT/logs/status.json"; echo "===== $1 ====="; }

status boot
[ -f /etc/rp_environment ] && source /etc/rp_environment
export HF_TOKEN HUGGING_FACE_HUB_TOKEN SB_KEY 2>/dev/null
[ -n "$HF_TOKEN" ] && echo "HF token: present (${#HF_TOKEN} chars)" || echo "HF token: MISSING"
[ -n "$SB_KEY" ] && echo "SB key: present (${#SB_KEY} chars)" || echo "SB key: MISSING (uploads will be skipped)"
nvidia-smi -L || true
cd /app/TRELLIS.2 || { status FATAL-no-trellis2; sleep infinity; }
export PYTHONPATH=/app/TRELLIS.2:/app:$PYTHONPATH
pip install -q "transformers==4.57.6" || true

status fetch-inputs
PUB=https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object/public/car-renders/finetune/eval_inputs
mkdir -p /workspace/eval_inputs/{golf,escape,model3,gti,gti8}
for i in 0 1 2 3; do
  curl -sf "$PUB/golf/$i.jpg"   -o /workspace/eval_inputs/golf/$i.jpg   || true
  curl -sf "$PUB/escape/$i.jpg" -o /workspace/eval_inputs/escape/$i.jpg || true
  curl -sf "$PUB/gti/$i.jpg"    -o /workspace/eval_inputs/gti/$i.jpg    || true
  for j in 4 5 6 7; do curl -sf "$PUB/gti8/$j.jpg" -o /workspace/eval_inputs/gti8/$j.jpg || true; done
  curl -sf "$PUB/gti8/$i.jpg"   -o /workspace/eval_inputs/gti8/$i.jpg   || true
done
curl -sf "$PUB/model3/0.jpg" -o /workspace/eval_inputs/model3/0.jpg || true
ls -la /workspace/eval_inputs/*/

status generate
python3 - <<'PY'
import glob, io, json, os, sys, subprocess, types
import importlib.util
import torch
from PIL import Image
sys.path.insert(0, "/app")

# Load the pipeline THROUGH the production handler so we inherit its patches:
# the ungated MIT BiRefNet (the config's briaai/RMBG-2.0 is restricted AND
# non-commercial — it 403'd eval run 1) and the DINOv3 feature-extraction fix.
# handler.py calls runpod.serverless.start at import, so stub runpod first.
_fake = types.ModuleType("runpod")
_fake.serverless = types.SimpleNamespace(start=lambda *a, **k: None)
sys.modules["runpod"] = _fake
spec = importlib.util.spec_from_file_location("handler", "/app/handler.py")
handler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(handler)

import o_voxel

OUT = "/workspace/alam3d_eval/logs"
ck = sorted(glob.glob("/workspace/alam3d_stage_c/ckpts/denoiser_ema0.9999_step*.pt"))
if not ck:
    print("NO EMA CHECKPOINT FOUND"); open(f"{OUT}/status.json","w").write('{"step":"FATAL-no-ckpt"}'); sys.exit(1)
CKPT = ck[-1]
print("evaluating checkpoint:", os.path.basename(CKPT))

pipeline = handler.get_image_pipeline()
# product-quality eval: full cascade (the 512-only pass undersold sharpness);
# our tuned 512 stage feeds the stock 1024 refiner, exactly as production would
PIPE = os.environ.get("EVAL_PIPE", "1024_cascade")
print("pipeline_type:", PIPE)

CASES = {
    "golf":   sorted(glob.glob("/workspace/eval_inputs/golf/*.jpg")),
    "model3": sorted(glob.glob("/workspace/eval_inputs/model3/*.jpg")),
    "escape": sorted(glob.glob("/workspace/eval_inputs/escape/*.jpg")),
    "gti":    sorted(glob.glob("/workspace/eval_inputs/gti/*.jpg")),
    "gti8":   sorted(glob.glob("/workspace/eval_inputs/gti8/*.jpg")),
}
# EVAL_CASES=gti runs one case only — fast, cheap spot-checks of new vehicles
_only = [c for c in os.environ.get("EVAL_CASES", "").split(",") if c]
if _only:
    CASES = {k: v for k, v in CASES.items() if k in _only}
print("cases:", list(CASES))

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
    print(f"GLB {case}/{tag}: {os.path.getsize(path)//1024}KB")

for case, paths in CASES.items():
    gen(case, paths, "base")

# swap in the fine-tuned weights (fp32 master params -> bf16 module, cast on copy)
sd = torch.load(CKPT, map_location="cuda", weights_only=True)
model = pipeline.models["shape_slat_flow_model_512"]
missing, unexpected = model.load_state_dict(sd, strict=False)
print(f"weight swap: missing={len(missing)} unexpected={len(unexpected)}")
if len(missing) > 20:
    print("TOO MANY MISSING KEYS — aborting tuned eval"); sys.exit(1)

for case, paths in CASES.items():
    gen(case, paths, "alam3d")
print("EVAL_GENERATION_COMPLETE")
PY
[ $? -ne 0 ] && { echo "GENERATE FAILED"; status FATAL-generate; sleep infinity; }

status upload
if [ -n "$SB_KEY" ]; then
  RUNID=$(date -u +%Y%m%dT%H%M)
  for f in "$OUT/logs/"*.glb; do
    n=$(basename "$f")
    curl -s -X POST "https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object/car-meshes/eval/$RUNID/$n" \
      -H "apikey: $SB_KEY" -H "Authorization: Bearer $SB_KEY" \
      -H "Content-Type: model/gltf-binary" -H "x-upsert: true" \
      --data-binary @"$f" -o /dev/null -w "$n: %{http_code}\n"
  done
  echo "EVAL_RUN_ID $RUNID"
fi

status DONE
ls -la "$OUT/logs/"*.glb 2>/dev/null
sleep infinity
