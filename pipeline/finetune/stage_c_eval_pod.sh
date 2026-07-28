#!/bin/bash
# stage_c_eval_pod.sh — Alam-3D Stage C eval: base TRELLIS.2-4B vs our
# fine-tuned checkpoint, same seed, on the fixed eval set (Golf 4-view,
# Tesla Model 3 side single-view, unseen Ford Escape/Kuga 4-view).
# Produces 6 GLBs (3 cases x base/alam3d) and uploads them to the
# car-meshes bucket under eval/ for rendering + human review.
# Secrets (HF_TOKEN for gated DINOv3, SB_KEY for upload) arrive via pod env.
# Outputs live on CONTAINER-LOCAL disk, not the network volume. On 2026-07-26
# the volume hit its quota and three eval pods went dark: the logs were created
# with plausible sizes but read back as all-NUL, so there was no way to see what
# the run was doing. Only the checkpoints are read from /workspace; a handful of
# GLBs fit easily on the 60GB container disk and go straight to Supabase.
OUT=/root/alam3d_eval
# M5: this used to be hardcoded to /workspace/alam3d_stage_c (v0). Evaluating
# v1 silently graded v0's damaged weights instead. EVAL_RUN_DIR now drives
# every path below and defaults to v1; v0 must be asked for by name.
EVAL_RUN_DIR="${EVAL_RUN_DIR:-/workspace/alam3d_stage_c_v1}"
CKPT_DIR="$EVAL_RUN_DIR/ckpts"
echo "EVAL RUN DIR: $EVAL_RUN_DIR"
if [ ! -d "$CKPT_DIR" ]; then
  echo "FATAL: $CKPT_DIR does not exist - nothing to evaluate"
  mkdir -p "$OUT/logs"
  printf '{"step":"FATAL-no-run-dir"}' > "$OUT/logs/status.json"
  sleep infinity
fi
export EVAL_RUN_DIR
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

status arch-check
# ARCHITECTURE GUARD. The container's CUDA kernels are compiled for a fixed set
# of architectures. Land on a newer card and every kernel launch fails with
# "no kernel image is available for execution on the device" - but only once
# real work starts, which on 2026-07-28 meant 25 minutes and $0.45 spent before
# an H100 admitted it could not run this image.
#
# torch knows both halves of the answer at import time. Ask it, in seconds,
# before anything expensive happens. This sits INSIDE the pod deliberately: a
# launcher allowlist protects only against the mistakes we already know about.
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
# The arch list is context, NOT the gate. Measured 2026-07-28: this image
# reports sm_90 in torch.cuda.get_arch_list(), yet the H100 run died at the
# first F.conv2d with "no kernel image is available" - conv2d dispatches to
# cuDNN, which ships kernels torch's list says nothing about (the cuDNN in
# this image predating Hopper is the likely mechanism; the failure itself is
# the measured fact). So the gate is a real launch of the op that died, plus
# a matmul, on the actual device.
if built and have not in built:
    print(f"note: {have} absent from the compiled arch list - relying on the "
          f"live kernel test below, not the list")
try:
    x = torch.randn(1, 3, 32, 32, device="cuda")
    w = torch.randn(8, 3, 3, 3, device="cuda")
    y = torch.nn.functional.conv2d(x, w)          # the op the H100 died on
    z = torch.randn(64, 64, device="cuda") @ torch.randn(64, 64, device="cuda")
    torch.cuda.synchronize()
    s = float(y.sum()) + float(z.sum())
except Exception as e:
    print(f"FATAL: kernel smoke test failed on {name} ({have}).")
    print(f"       {type(e).__name__}: {str(e)[:160]}")
    print("       Real work would die exactly like the H100 did on 2026-07-28.")
    sys.exit(1)
print(f"arch OK: conv2d + matmul ran on {name} ({have})")
PYARCH


# Fail fast and loudly if the volume is out of quota again — a silent quota
# error is what truncated Stage D's step-4000 checkpoint mid-save.
python3 - <<'PY' || { status FATAL-volume-quota; sleep infinity; }
import os, sys
p = "/workspace/_eval_quota_probe"
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
mkdir -p /root/eval_inputs/{golf,escape,model3,gti,gti8,qashqai}
for i in 0 1 2 3; do
  curl -sf "$PUB/golf/$i.jpg"   -o /root/eval_inputs/golf/$i.jpg   || true
  curl -sf "$PUB/escape/$i.jpg" -o /root/eval_inputs/escape/$i.jpg || true
  curl -sf "$PUB/gti/$i.jpg"    -o /root/eval_inputs/gti/$i.jpg    || true
  curl -sf "$PUB/qashqai/$i.jpg" -o /root/eval_inputs/qashqai/$i.jpg || true
  for j in 4 5 6 7; do curl -sf "$PUB/gti8/$j.jpg" -o /root/eval_inputs/gti8/$j.jpg || true; done
  curl -sf "$PUB/gti8/$i.jpg"   -o /root/eval_inputs/gti8/$i.jpg   || true
done
curl -sf "$PUB/model3/0.jpg" -o /root/eval_inputs/model3/0.jpg || true

# DOMAIN TEST. Every training image is a Blender render of a GLB on a black
# background; every eval so far fed real dealer photographs. That gap is a live
# suspect for the Stage C regression — fine-tuning hard onto one renderer's look
# can push real photos further out of distribution than they were before.
#
# EVAL_HOLDOUT_SHA names a car whose latents were encoded AFTER Stage C started,
# so it is genuinely unseen. Feeding 4 of its own conditioning views makes the
# input perfectly in-distribution. Good on renders + bad on photos = domain gap,
# and the fix is render augmentation rather than less training.
if [ -n "$EVAL_HOLDOUT_SHA" ]; then
  SRC="/workspace/alamcars/renders_cond/$EVAL_HOLDOUT_SHA"
  mkdir -p /root/eval_inputs/holdout
  if [ -d "$SRC" ]; then
    # 4 views spread around the 16-view orbit, mirroring the 4-photo GTI setup
    n=0
    for i in 000 004 008 012; do
      f=$(ls "$SRC"/*"$i"* 2>/dev/null | head -1)
      [ -n "$f" ] && cp "$f" "/root/eval_inputs/holdout/$i.png" && n=$((n+1))
    done
    [ "$n" -eq 0 ] && ls "$SRC" | head -4 | while read -r f; do cp "$SRC/$f" /root/eval_inputs/holdout/; done
    echo "holdout case: $EVAL_HOLDOUT_SHA -> $(ls /root/eval_inputs/holdout | wc -l) views"
  else
    echo "holdout: NO RENDERS at $SRC — case will be skipped"
  fi
fi
ls -la /root/eval_inputs/*/

status generate
python3 - <<'PY'
import glob, io, json, os, re, sys, subprocess, types, zipfile, time, urllib.request
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

OUT = "/root/alam3d_eval/logs"
RUN_DIR = os.environ.get("EVAL_RUN_DIR", "/workspace/alam3d_stage_c_v1")
ck = sorted(glob.glob(f"{RUN_DIR}/ckpts/denoiser_ema0.9999_step*.pt"))
print("checkpoint source:", RUN_DIR)
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
    "golf":   sorted(glob.glob("/root/eval_inputs/golf/*.jpg")),
    "model3": sorted(glob.glob("/root/eval_inputs/model3/*.jpg")),
    "escape": sorted(glob.glob("/root/eval_inputs/escape/*.jpg")),
    "gti":    sorted(glob.glob("/root/eval_inputs/gti/*.jpg")),
    "gti8":   sorted(glob.glob("/root/eval_inputs/gti8/*.jpg")),
    # a car sourced fresh today and never seen by any checkpoint
    "qashqai": sorted(glob.glob("/root/eval_inputs/qashqai/*.jpg")),
    # renders, not photographs — the in-distribution control for the domain test
    "holdout": sorted(glob.glob("/root/eval_inputs/holdout/*.png"))
               + sorted(glob.glob("/root/eval_inputs/holdout/*.jpg")),
}
CASES = {k: v for k, v in CASES.items() if v}   # drop cases with no inputs
# EVAL_CASES=gti runs one case only — fast, cheap spot-checks of new vehicles
_only = [c for c in os.environ.get("EVAL_CASES", "").split(",") if c]
if _only:
    CASES = {k: v for k, v in CASES.items() if k in _only}
print("cases:", list(CASES))

RUNID = os.environ.get("EVAL_RUN_ID") or time.strftime("%Y%m%dT%H%M", time.gmtime())
_SB = os.environ.get("SB_KEY", "")
_pushed = []

def _push(local, name):
    """Ship one GLB immediately. Never raises - a failed upload must not kill a
    sweep that is otherwise producing good results, but it must be VISIBLE, so
    every outcome is printed and counted."""
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

for case, paths in CASES.items():
    gen(case, paths, "base")

# swap in the fine-tuned weights. Stage C tuned the 512 shape stage; Stage D
# tuned the 1024 refiner — with both loaded, the whole geometry cascade is ours.
def swap(stage_key, ckpt_glob, label):
    # A missing or truncated checkpoint must ABORT, never fall through to stock
    # weights: the run would still emit "alam3d" GLBs that are really Microsoft's
    # model, and the comparison sheet would be a lie. The full volume truncated
    # Stage D's step-4000 save on 2026-07-26, so verify the archive too — a
    # torch .pt is a zip, and reading its central directory proves it all landed.
    ck = sorted(glob.glob(ckpt_glob), reverse=True)
    good = []
    for p in ck:
        try:
            with zipfile.ZipFile(p):
                good.append(p)
        except Exception as e:
            print(f"{label}: SKIPPING truncated checkpoint {os.path.basename(p)} ({type(e).__name__})")
    if not good:
        raise SystemExit(f"{label}: no loadable checkpoint matching {ckpt_glob} — aborting "
                         f"rather than silently evaluating stock weights")
    ck = good
    sd = torch.load(ck[0], map_location="cuda", weights_only=True)
    m = pipeline.models[stage_key]
    missing, unexpected = m.load_state_dict(sd, strict=False)
    print(f"{label} swap [{os.path.basename(ck[0])}]: missing={len(missing)} unexpected={len(unexpected)}")
    if missing:
        raise SystemExit(
            f"{label}: {len(missing)} tensors did not load - those weights would "
            f"stay STOCK while the result is reported as a fine-tune. Aborting.")
    return ck[0]

C_GLOB = os.environ.get("EVAL_RUN_DIR", "/workspace/alam3d_stage_c_v1") + "/ckpts/denoiser_ema*step*.pt"
D_GLOB = "/workspace/alam3d_stage_d/ckpts/denoiser_ema*step*.pt"
K512, K1024 = "shape_slat_flow_model_512", "shape_slat_flow_model_1024"

if os.environ.get("EVAL_SWEEP") == "1":
    # STEP SWEEP. The contamination theory for Stage C was falsified: its 365
    # shapes are almost all clean cars, while the junk sits in the 598 added
    # later that only Stage D ever saw — and Stage D came out fine. The
    # surviving explanation is dose, not diet: Stage C ran 6000 steps at
    # lr 1e-5 over 365 shapes, far more epochs than Stage D's 3000 at 8e-6
    # over 543, which is how a 1.3B model gets dragged off its pretrained prior.
    #
    # Testable without retraining anything, because every Stage C EMA
    # checkpoint survived the volume purge. If damage accumulates with steps,
    # quality falls monotonically from 1000 to 4000 — and an early checkpoint
    # may already be a Stage C worth keeping.
    stock1024 = {n: t.detach().cpu().clone()
                 for n, t in pipeline.models[K1024].state_dict().items()}
    cks = sorted(glob.glob(C_GLOB))
    # PRE-FLIGHT: zip-verify every checkpoint before generating anything.
    # step-1250 of the 2026-07-27 run was truncated by a full volume and took
    # the whole sweep down at the fourth load, throwing away three checkpoints'
    # worth of finished cars. A corrupt file is now a skipped file.
    good, bad = [], []
    for _p in cks:
        try:
            with zipfile.ZipFile(_p):
                pass
            good.append(_p)
        except Exception as _e:
            bad.append((os.path.basename(_p), type(_e).__name__,
                        os.path.getsize(_p) // (1024 * 1024)))
    for _n, _t, _mb in bad:
        print(f"  CORRUPT, skipping: {_n} ({_mb}MB, {_t})", flush=True)
    if not good:
        print("FATAL: every checkpoint is unreadable"); sys.exit(1)
    if bad:
        print(f"  {len(bad)} of {len(cks)} checkpoints are unusable - "
              f"sweeping the {len(good)} that are intact", flush=True)
    cks = good
    print(f"sweeping {len(cks)} Stage C checkpoints (1024 stage stays stock throughout)")
    for p in cks:
        m = re.search(r"step0*(\d+)", os.path.basename(p))
        tag = "c" + (m.group(1) if m else os.path.basename(p)[:4])
        sd = torch.load(p, map_location="cuda", weights_only=True)
        missing, unexpected = pipeline.models[K512].load_state_dict(sd, strict=False)
        print(f"{tag}: loaded {os.path.basename(p)} missing={len(missing)} unexpected={len(unexpected)}")
        del sd
        pipeline.models[K1024].load_state_dict(stock1024, strict=False)
        for case, paths in CASES.items():
            gen(case, paths, tag)
elif os.environ.get("EVAL_ISOLATE") == "1":
    # ISOLATION RUN. The C+D cascade came out visibly worse than stock on the
    # GTI, but "worse" does not say WHICH stage did it. Four variants from one
    # pipeline, one seed, one pod answers that: whichever variant carries the
    # defect owns it, and if both C-only and D-only look fine while C+D does
    # not, the fault is in how the two stack rather than in either checkpoint.
    stock = {k: {n: t.detach().cpu().clone() for n, t in pipeline.models[k].state_dict().items()}
             for k in (K512, K1024)}
    print(f"stashed stock weights for {list(stock)}")

    def restore(k, label):
        pipeline.models[k].load_state_dict(stock[k], strict=False)
        print(f"restored stock {label}")

    swap(K512, C_GLOB, "Stage C 512")
    for case, paths in CASES.items():
        gen(case, paths, "conly")          # tuned C  + stock D

    swap(K1024, D_GLOB, "Stage D 1024")
    for case, paths in CASES.items():
        gen(case, paths, "cd")             # tuned C  + tuned D

    restore(K512, "512")
    for case, paths in CASES.items():
        gen(case, paths, "donly")          # stock C  + tuned D
else:
    swap(K512, C_GLOB, "Stage C 512")
    if os.environ.get("EVAL_STAGE_D", "1") == "1":
        swap(K1024, D_GLOB, "Stage D 1024")
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
