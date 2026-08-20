#!/usr/bin/env bash
# alam3d_boot.sh — run OUR OWN fine-tune (Alam-3D) on real images, and the
# STOCK TRELLIS.2 base on the same images in the same pod boot, so the only
# comparison that matters costs one rental instead of two.
#
# WHAT ALAM-3D IS, stated here so nobody has to reconstruct it:
# a Stage C fine-tune of TRELLIS.2's `shape_slat_flow_model_512` (1.29B params),
# initialised from microsoft/TRELLIS.2-4B. NOT TRELLIS-1. Everything else in the
# cascade — sparse structure, the 1024 refiner, BOTH texture stages — is stock.
# So the job is: build the normal production pipeline, then SUBSTITUTE one
# submodule's state dict. The checkpoints are archived (private) on HF at
# Alamj/alam-3d-v1 and Alamj/alam-3d-v0; which one is the valid post-fix set is
# decided OUTSIDE this script — repo and file are parameters, never hardcoded.
#
# BASE IMAGE IS OUR OWN trellis2-worker-4b (RunPod template i1mk2n9dap). It
# already carries the TRELLIS.2 CUDA extensions (o_voxel, cumesh, flex_gemm,
# nvdiffrast), /app/handler.py with the two patches the pipeline cannot run
# without (ungated BiRefNet, DINOv3 feature-extraction fix), and
# /app/alam3d_multiview.py. Reusing it turns an hour of source builds into a
# pip install — and it means the pipeline this script loads is BYTE-IDENTICAL
# to the production render path, which is the point of an eval.
#
# THE ONE FAILURE MODE THIS WHOLE FILE EXISTS TO PREVENT: loading zero tensors.
# `load_state_dict(..., strict=False)` returns quietly when nothing matches. The
# run would then emit stock TRELLIS.2 output labelled "alam3d", and we would
# draw conclusions about a fine-tune from the base model. The swap below counts
# matched / missing / unexpected / shape-mismatched tensors, refuses to continue
# below a match-rate floor, AND fingerprints the module's weights before and
# after to prove the numbers actually moved.
set -x
export DEBIAN_FRONTEND=noninteractive
export PYTHONUNBUFFERED=1
LOG=/workspace/boot.log
mkdir -p /workspace
exec > >(tee -a "$LOG") 2>&1

SB="https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object"
# MUST match launch_alam3d.py's PRE. It did not match on the 2026-08-19 Pixal
# run: the launcher uploaded to one prefix and the pod read another, so four
# healthy pods booted, failed FETCH_MANIFEST, and reported to a log nobody was
# watching — which read as four dead hosts. The launcher passes ALAM3D_PRE in
# the pod env for exactly this reason; the default here is only a fallback.
PRE="${ALAM3D_PRE:-car-meshes/alam3d}"

# Supabase storage needs BOTH headers. `Authorization: Bearer` alone returns
# 403 "Invalid Compact JWS" (SB_KEY is an sb_secret_… key, not a JWT), which
# looks exactly like an expired key and has cost this project time twice.
report() { ( set +x
  curl -s -X POST -H "apikey: ${SB_KEY}" -H "Authorization: Bearer ${SB_KEY}" \
       -H "x-upsert: true" -H "Content-Type: text/plain" \
       --data-binary @"$LOG" "$SB/$PRE/$1" >/dev/null 2>&1 ) || true; }
sb_file() { ( set +x
  curl -s -o /tmp/put.out -w "%{http_code}" -X POST \
       -H "apikey: ${SB_KEY}" -H "Authorization: Bearer ${SB_KEY}" \
       -H "x-upsert: true" -H "Content-Type: application/octet-stream" \
       --data-binary @"$2" "$SB/$PRE/$1" ) || true; echo " <- upload $1"; }
stage() { echo "=== STAGE:$1 ==="; report "log.txt"; }
# die() NEVER exits. A dockerStartCmd that exits gets the pod RESTARTED — which
# on the PartCrafter run meant re-cloning and re-downloading ~10GB of weights in
# an infinite loop, GPU at 0%, `desiredStatus` reading RUNNING the whole time.
# Park the container instead and let the launcher delete the pod.
die()   { echo "=== FAIL:$1 ==="; report "log.txt"; sleep infinity; }

stage boot
nvidia-smi || die NO_GPU
python3 -c "import torch;print('torch',torch.__version__,torch.version.cuda,torch.cuda.get_device_name(0))" || die TORCH_BROKEN
TORCH_BEFORE=$(python3 -c "import torch;print(torch.__version__)")
echo "TORCH_BEFORE=$TORCH_BEFORE"
df -h /workspace | tail -1
free -g | head -2

stage arch_check
# ARCHITECTURE GUARD, and it is not theoretical. On 2026-07-28 this image loaded
# the whole model on an H100 and then died at the first F.conv2d with "no kernel
# image is available for execution on the device" — 25 minutes and $0.45 in.
# torch's compiled arch list does NOT catch it (the image reports sm_90); conv2d
# dispatches to cuDNN, which ships kernels the list says nothing about. So the
# gate is a REAL launch of the op that died, on the actual card, in seconds.
# The launcher also keeps Hopper out of the GPU pool; this is the backstop.
python3 - <<'PY' || die GPU_ARCH
import sys, torch
if not torch.cuda.is_available():
    print("FATAL: no CUDA device visible"); sys.exit(1)
name = torch.cuda.get_device_name(0)
cap = torch.cuda.get_device_capability(0)
print(f"GPU: {name}  compute=sm_{cap[0]}{cap[1]}")
print("image built for:", " ".join(torch.cuda.get_arch_list()) or "(none reported)")
try:
    x = torch.randn(1, 3, 32, 32, device="cuda")
    w = torch.randn(8, 3, 3, 3, device="cuda")
    y = torch.nn.functional.conv2d(x, w)              # the op the H100 died on
    z = torch.randn(64, 64, device="cuda") @ torch.randn(64, 64, device="cuda")
    torch.cuda.synchronize()
    _ = float(y.sum()) + float(z.sum())
except Exception as e:
    print(f"FATAL: kernel smoke test failed on {name}: {type(e).__name__}: {str(e)[:160]}")
    print("       Real work would die exactly like the H100 did on 2026-07-28.")
    sys.exit(1)
print("arch OK: conv2d + matmul ran on the real device")
PY

stage native_check
# CHEAPEST POSSIBLE FAILURE: if this is the wrong image, the whole plan is void.
# Find out in 20 seconds, not 20 minutes. Everything listed here is on the
# DEFAULT code path of the production pipeline — /app/handler.py imports o_voxel
# and trellis2 at module scope, and alam3d_multiview is what a multi-view car
# goes through. A missing one is fatal; there are no soft entries because there
# is no alternative backend for any of them.
python3 - <<'PY' || die WRONG_IMAGE
import importlib, os, sys, traceback
sys.path.insert(0, "/app/TRELLIS.2"); sys.path.insert(0, "/app")
bad = []
for m in ["o_voxel", "cumesh", "flex_gemm", "nvdiffrast",
          "trellis2.pipelines", "alam3d_multiview"]:
    try:
        importlib.import_module(m); print("ok", m)
    except Exception:
        bad.append(m); traceback.print_exc()
for f in ["/app/handler.py", "/app/alam3d_multiview.py"]:
    print(("ok  " if os.path.exists(f) else "MISSING "), f)
    if not os.path.exists(f):
        bad.append(f)
if bad:
    raise SystemExit(f"this is not trellis2-worker-4b — missing: {bad}")
PY

stage deps
# TORCH GUARD, the documented trap: anything that moves torch silently breaks
# every CUDA extension compiled against the image's build — and those extensions
# are the entire reason this image was chosen. Install, ASSERT, repin if moved.
# transformers is pinned to the version the DINOv3 patch in handler.py was
# written against (the same pin every finetune pod script carries).
pip install -q "transformers==4.57.6" "huggingface_hub>=0.26" 2>&1 | tail -4 || true
TORCH_AFTER=$(python3 -c "import torch;print(torch.__version__)")
echo "TORCH_AFTER=$TORCH_AFTER (before=$TORCH_BEFORE)"
if [ "$TORCH_BEFORE" != "$TORCH_AFTER" ]; then
  echo "a dependency MOVED TORCH — reinstalling the image's pin"
  pip install -q --force-reinstall "torch==$TORCH_BEFORE" 2>&1 | tail -3
fi
python3 - <<'PY' || die NATIVE_BROKEN_BY_DEPS
import torch, o_voxel, cumesh, flex_gemm
assert torch.cuda.is_available()
print("post-deps OK: torch", torch.__version__, "+ native extensions intact")
PY

export HF_HOME="${HF_HOME:-/workspace/hf}"
export HUGGING_FACE_HUB_TOKEN="${HUGGING_FACE_HUB_TOKEN:-$HF_TOKEN}"
export PYTHONPATH=/app/TRELLIS.2:/app:$PYTHONPATH
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

# REPO AND FILE ARE PARAMETERS. Which checkpoint is the valid post-fix one is
# not this script's call — v1 holds steps 250/500/750/1000, v0 holds step 4000,
# and the answer may be either repo. The launcher resolves and verifies the
# exact path against the HF API and passes it in; these defaults only make the
# script runnable on its own. The _R copies are what the python heredocs read:
# the heredocs are quoted, so nothing is ever spliced into their source.
CKPT_REPO="${ALAM3D_CKPT_REPO:-Alamj/alam-3d-v1}"
CKPT_PATH="${ALAM3D_CKPT_PATH:-ckpts/denoiser_ema0.9999_step0000500.pt}"
export ALAM3D_CKPT_REPO_R="$CKPT_REPO" ALAM3D_CKPT_PATH_R="$CKPT_PATH"
echo "checkpoint: $CKPT_REPO :: $CKPT_PATH"

stage ckpt_fetch
# THE FINE-TUNE CHECKPOINT GETS ITS OWN RETRIED STAGE, and this is a paid
# lesson from 2026-08-20: a ~4GB lazy safetensors pull died mid-transfer
#   ChunkedEncodingError: IncompleteRead(439687615 read, 3584602277 expected)
# INSIDE the first inference, so a healthy model lost a whole car to a TCP drop.
# hf_hub_download resumes from its cache, so a broken connection costs seconds
# here instead of a car later. The file is ~5.2GB.
#
# And it is VERIFIED, not merely downloaded: a torch .pt is a zip, and a full
# volume once truncated a 5169MB checkpoint to 3264MB during Stage C. That
# truncation is invisible until something tries to load it.
python3 - <<'PY' || die CKPT_FETCH
import os, sys, time, zipfile
from huggingface_hub import hf_hub_download
repo = os.environ["ALAM3D_CKPT_REPO_R"]
path = os.environ["ALAM3D_CKPT_PATH_R"]
tok = os.environ.get("HF_TOKEN") or None
last = None
for attempt in range(1, 6):
    try:
        p = hf_hub_download(repo, path, token=tok)
        break
    except Exception as e:
        last = e
        print(f"attempt {attempt} failed: {type(e).__name__}: {str(e)[:200]}")
        if attempt == 5:
            print("FATAL: checkpoint unreachable after 5 attempts"); sys.exit(1)
        time.sleep(5 * attempt)
sz = os.path.getsize(p)
print(f"checkpoint on disk: {p} ({sz/1e9:.2f} GB)")
if sz < 1_000_000_000:
    print("FATAL: implausibly small for a 1.3B denoiser EMA — truncated?"); sys.exit(1)
try:
    with zipfile.ZipFile(p) as z:
        print(f"zip integrity OK, {len(z.namelist())} entries")
except Exception as e:
    print(f"FATAL: checkpoint is not a readable torch archive ({type(e).__name__}) "
          f"— truncated download or a corrupt upload"); sys.exit(1)
open("/workspace/ckpt_path.txt", "w").write(p)
PY
CKPT_LOCAL=$(cat /workspace/ckpt_path.txt) || die CKPT_PATH_MISSING
echo "CKPT_LOCAL=$CKPT_LOCAL"

stage weights_base
# Same lesson, other model: Trellis2ImageTo3DPipeline.from_pretrained pulls the
# whole TRELLIS.2-4B cascade lazily. Warm it HERE, on CPU, with retries, so a
# mid-transfer drop costs seconds rather than killing the first car. Building
# without .cuda() downloads exactly what the pipeline needs (a blanket
# snapshot_download would drag files this cascade never loads) and the generate
# stage below then re-builds from a warm cache in about a minute.
python3 - <<'PY' || die WEIGHTS_BASE
import importlib.util, sys, time, types
sys.path.insert(0, "/app/TRELLIS.2"); sys.path.insert(0, "/app")
# handler.py calls runpod.serverless.start at import — stub it, as the eval pod
# does, so importing the production patches does not start a worker loop.
_fake = types.ModuleType("runpod")
_fake.serverless = types.SimpleNamespace(start=lambda *a, **k: None)
sys.modules["runpod"] = _fake
spec = importlib.util.spec_from_file_location("handler", "/app/handler.py")
handler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(handler)
from trellis2.pipelines import Trellis2ImageTo3DPipeline
handler._patch_rembg_to_free_model()
handler._patch_dinov3_extract_features()
for attempt in range(1, 4):
    try:
        p = Trellis2ImageTo3DPipeline.from_pretrained(handler.IMAGE_MODEL)
        print("base weights cached; pipeline submodules:", sorted(p.models))
        del p
        break
    except Exception as e:
        print(f"attempt {attempt} failed: {type(e).__name__}: {str(e)[:200]}")
        if attempt == 3:
            raise
        time.sleep(10 * attempt)
PY

stage fetch_manifest
cd /workspace
curl -fsSL "$SB/public/$PRE/batch.json" -o batch.json || die FETCH_MANIFEST
mkdir -p /workspace/inputs
python3 - <<'PY' || die BAD_MANIFEST
import json
d = json.load(open("/workspace/batch.json"))
assert d and isinstance(d, list), "empty or malformed batch manifest"
for car in d:
    assert car.get("tag") and car.get("views"), f"bad entry: {car}"
print("batch cars:", len(d),
      "views:", {c["tag"]: len(c["views"]) for c in d})
PY
for V in $(python3 -c "import json;print(' '.join(v for c in json.load(open('/workspace/batch.json')) for v in c['views']))"); do
  curl -fsSL "$SB/public/$PRE/$V" -o "/workspace/inputs/$V" || die FETCH_INPUT_"$V"
done
ls -la /workspace/inputs | head -20

# ---------------------------------------------------------------- GENERATE
# Written to disk rather than piped as a heredoc so the traceback line numbers
# in the log point at something readable, and so `python3 -m py_compile` can
# check it locally before this file is ever uploaded.
cat > /workspace/alam3d_gen.py <<'PYGEN'
"""Base-vs-tuned generation in ONE pipeline load.

Order matters and is deliberate: every car is generated with STOCK weights
first, then the fine-tuned denoiser is swapped in and every car is generated
again. Same pod, same card, same seed, same inputs, same postprocess — the only
variable between the two arms is 1.29B parameters of `shape_slat_flow_model_512`.
Two rentals would not have given that, and a base render from some other run on
some other day is not a control.
"""
import glob
import hashlib
import importlib.util
import json
import os
import sys
import time
import types
import urllib.request

sys.path.insert(0, "/app/TRELLIS.2")
sys.path.insert(0, "/app")

import torch                                                   # noqa: E402
from PIL import Image                                          # noqa: E402

SB = "https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object"
PRE = os.environ.get("ALAM3D_PRE", "car-meshes/alam3d")
SB_KEY = os.environ.get("SB_KEY", "")
RUN_ID = os.environ.get("ALAM3D_RUN_ID") or time.strftime("%Y%m%dT%H%M", time.gmtime())
SEED = int(os.environ.get("ALAM3D_SEED", "42"))
PIPE = os.environ.get("ALAM3D_PIPE", "1024_cascade")
# 49152 is upstream's default and OOMs a 24GB worker (measured 2026-08-09:
# single-image died in remesh_narrow_band_dc, multi-image in cumesh.simplify
# AFTER generation succeeded). 32768 is the proven-safe budget. Both arms use
# the SAME value or the comparison is worthless.
MAX_TOKENS = int(os.environ.get("ALAM3D_MAX_TOKENS", "32768"))
TEXTURE = int(os.environ.get("ALAM3D_TEXTURE", "2048"))
DECIMATE = int(os.environ.get("ALAM3D_DECIMATE", "120000"))
RUN_BASE = os.environ.get("ALAM3D_RUN_BASE", "1") == "1"
MIN_MATCH = float(os.environ.get("ALAM3D_MIN_MATCH", "0.99"))
K512 = "shape_slat_flow_model_512"


def mark(s):
    """Stage marker. The launcher watches the BUCKET LOG for these lines — it
    never asks RunPod for status, because `desiredStatus` reads RUNNING straight
    through an infinite restart loop and through a wedged process alike."""
    print(f"=== STAGE:{s} ===", flush=True)


def push(local, name):
    """Upload one artefact immediately. Never raises: a failed upload must not
    kill a run that is otherwise producing results — but it must be VISIBLE, so
    every outcome is printed."""
    if not SB_KEY:
        print(f"  upload skipped (no SB_KEY): {name}", flush=True)
        return
    try:
        with open(local, "rb") as fh:
            data = fh.read()
        rq = urllib.request.Request(f"{SB}/{PRE}/{RUN_ID}/{name}", data=data,
                                    method="POST")
        for h, v in (("apikey", SB_KEY), ("Authorization", "Bearer " + SB_KEY),
                     ("x-upsert", "true"),
                     ("Content-Type", "application/octet-stream")):
            rq.add_header(h, v)
        urllib.request.urlopen(rq, timeout=600).read()
        print(f"  uploaded {RUN_ID}/{name} ({len(data)/1e6:.1f}MB)", flush=True)
    except Exception as e:
        print(f"  UPLOAD FAILED {name}: {type(e).__name__} {str(e)[:120]}",
              flush=True)


# ------------------------------------------------------------------ pipeline
mark("load_pipeline")
_fake = types.ModuleType("runpod")
_fake.serverless = types.SimpleNamespace(start=lambda *a, **k: None)
sys.modules["runpod"] = _fake
spec = importlib.util.spec_from_file_location("handler", "/app/handler.py")
handler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(handler)
import o_voxel                                                 # noqa: E402

pipeline = handler.get_image_pipeline()
if K512 not in pipeline.models:
    raise SystemExit(f"FATAL: pipeline has no '{K512}' — submodules are "
                     f"{sorted(pipeline.models)}. This checkpoint tunes that "
                     f"exact module; there is nothing to substitute it into.")
print(f"pipeline loaded; type={PIPE} seed={SEED} max_num_tokens={MAX_TOKENS}",
      flush=True)

CARS = json.load(open("/workspace/batch.json"))
print("cars:", [c["tag"] for c in CARS], flush=True)


def generate(car, arm):
    tag = car["tag"]
    mark(f"gen_{tag}_{arm}")
    paths = [f"/workspace/inputs/{v}" for v in car["views"]]
    imgs = [Image.open(p) for p in paths]
    torch.manual_seed(SEED)
    t0 = time.time()
    if len(imgs) > 1:
        # multi-view goes through the same helper the production handler uses
        from alam3d_multiview import run_multi_image
        meshes = run_multi_image(pipeline, imgs, seed=SEED,
                                 preprocess_image=True, pipeline_type=PIPE,
                                 num_samples=1, max_num_tokens=MAX_TOKENS)
    else:
        try:
            meshes = pipeline.run(imgs[0], seed=SEED, preprocess_image=True,
                                  pipeline_type=PIPE, num_samples=1,
                                  max_num_tokens=MAX_TOKENS)
        except TypeError as e:
            # An older pipeline build may not surface max_num_tokens. Losing a
            # whole rental to a keyword argument is not acceptable; losing the
            # VRAM lever silently would be worse, so say which happened.
            print(f"  pipeline.run rejected a kwarg ({str(e)[:120]}) — retrying "
                  f"WITHOUT max_num_tokens (upstream default applies)")
            meshes = pipeline.run(imgs[0], seed=SEED, preprocess_image=True,
                                  pipeline_type=PIPE, num_samples=1)
    mesh = max(meshes, key=lambda m: len(m.faces)) if len(meshes) > 1 else meshes[0]
    # Free generation-stage VRAM before postprocess: the 2026-08-09 multi-view
    # OOM happened in cumesh.simplify AFTER generation had already succeeded,
    # with the sampler's allocations still resident.
    import gc
    gc.collect()
    torch.cuda.empty_cache()
    glb = o_voxel.postprocess.to_glb(
        vertices=mesh.vertices, faces=mesh.faces, attr_volume=mesh.attrs,
        coords=mesh.coords, attr_layout=mesh.layout, voxel_size=mesh.voxel_size,
        aabb=[[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]],
        decimation_target=DECIMATE, texture_size=TEXTURE,
        remesh=True, remesh_band=1, remesh_project=0, verbose=False)
    out = f"/workspace/{tag}_{arm}.glb"
    glb.export(out, extension_webp=False)
    # ARTEFACT ASSERTION. "It returned" is not "it produced a file": a run that
    # exits 0 with no output must fail loudly, never read as success.
    if not os.path.exists(out) or os.path.getsize(out) < 10_000:
        raise SystemExit(f"FATAL: {arm} arm produced no usable GLB for {tag}")
    print(f"GLB {tag}/{arm}: {os.path.getsize(out)//1024}KB in "
          f"{time.time()-t0:.0f}s", flush=True)
    push(out, f"{tag}_{arm}.glb")
    return out


# --------------------------------------------------------------- BASE ARM
produced = []
if RUN_BASE:
    for car in CARS:
        produced.append(generate(car, "base"))
else:
    print("base arm SKIPPED (ALAM3D_RUN_BASE=0) — there will be no control "
          "generated on this hardware with these inputs", flush=True)


# --------------------------------------------------------------- THE SWAP
mark("swap_weights")


def unwrap(obj, depth=0):
    """Return the flat {name: tensor} state dict inside a checkpoint.

    The Stage C trainer saves the EMA denoiser as a plain state dict (the eval
    pod loads it with a bare load_state_dict and that works). But 'plain' is an
    observation about four files, not a guarantee about the next one, and a
    wrapper key is the classic way to load ZERO tensors while raising nothing.
    Unwrap defensively, and say out loud what was unwrapped."""
    if not isinstance(obj, dict):
        raise SystemExit(f"FATAL: checkpoint is a {type(obj).__name__}, not a dict")
    if obj and all(torch.is_tensor(v) for v in obj.values()):
        return obj
    for key in ("ema", "ema_state_dict", "state_dict", "model", "module",
                "denoiser", "net", "params", "weights"):
        if key in obj and depth < 3:
            print(f"  unwrapping nested checkpoint key '{key}'")
            return unwrap(obj[key], depth + 1)
    tensors = {k: v for k, v in obj.items() if torch.is_tensor(v)}
    if tensors:
        print(f"  mixed dict: keeping {len(tensors)} of {len(obj)} entries "
              f"that are tensors")
        return tensors
    raise SystemExit(f"FATAL: no tensors found in checkpoint; top-level keys "
                     f"{list(obj)[:12]}")


def fingerprint(module, n=8):
    """A few cheap scalars over evenly spaced parameters. Loading a state dict
    that happens to be the STOCK weights would satisfy every count-based check
    below and still be a no-op; this is what catches that."""
    items = sorted(module.state_dict().items())
    step = max(1, len(items) // n)
    return [(k, round(float(v.detach().float().abs().mean()), 8))
            for k, v in items[::step][:n]]


ckpt_path = open("/workspace/ckpt_path.txt").read().strip()
print(f"loading {ckpt_path}", flush=True)
try:
    raw = torch.load(ckpt_path, map_location="cpu", weights_only=True)
except Exception as e:
    # weights_only=True is the safe default and is what the eval pod uses. A
    # failure here means the archive holds something other than plain tensors;
    # say so rather than silently widening the unpickler.
    print(f"  weights_only=True load failed ({type(e).__name__}: {str(e)[:120]})")
    print("  retrying with weights_only=False — this checkpoint is our own, "
          "written by our own trainer, so the pickle is not third-party")
    raw = torch.load(ckpt_path, map_location="cpu", weights_only=False)
sd = unwrap(raw)

module = pipeline.models[K512]
tgt = module.state_dict()
print(f"checkpoint tensors: {len(sd)}   module tensors: {len(tgt)}")

# Prefix reconciliation. DDP saves under 'module.', torch.compile under
# '_orig_mod.', and a trainer that saved the wrapper rather than the submodule
# saves under 'denoiser.'. Pick the prefix that matches BEST rather than
# assuming, and print the winner.
best, best_hits = "", -1
for pref in ("", "module.", "_orig_mod.", "denoiser.", "model.",
             "module._orig_mod."):
    hits = sum(1 for k in sd if k.startswith(pref) and k[len(pref):] in tgt)
    if hits > best_hits:
        best, best_hits = pref, hits
if best:
    print(f"  stripping checkpoint key prefix '{best}' ({best_hits} keys align)")
    sd = {k[len(best):]: v for k, v in sd.items() if k.startswith(best)}

matched = [k for k in sd if k in tgt and tuple(sd[k].shape) == tuple(tgt[k].shape)]
shape_bad = [k for k in sd if k in tgt and tuple(sd[k].shape) != tuple(tgt[k].shape)]
unexpected = [k for k in sd if k not in tgt]
missing = [k for k in tgt if k not in sd]
rate = len(matched) / max(1, len(tgt))
print(f"MATCHED {len(matched)}/{len(tgt)} ({rate:.4f})  "
      f"MISMATCHED: shape={len(shape_bad)} unexpected={len(unexpected)} "
      f"missing={len(missing)}")
for label, keys in (("shape-mismatch", shape_bad), ("unexpected", unexpected),
                    ("missing", missing)):
    if keys:
        print(f"  first {label}: {keys[:6]}")

# THE FLOOR. Silently loading zero tensors would produce base-model output that
# we would then present as the fine-tune — the single worst failure available
# here, and unfalsifiable after the fact because the GLB looks like a car
# either way. Refuse rather than guess.
if shape_bad:
    raise SystemExit("FATAL: shape mismatches — this checkpoint was not trained "
                     "against this module's architecture. Wrong stage, or a "
                     "TRELLIS-1 checkpoint against a TRELLIS.2 pipeline.")
if rate < MIN_MATCH or missing:
    raise SystemExit(
        f"FATAL: match rate {rate:.4f} < {MIN_MATCH} (or {len(missing)} tensors "
        f"absent from the checkpoint). Those weights would stay STOCK while the "
        f"output is labelled alam3d. Aborting instead of producing a comparison "
        f"that is a lie.")

before = fingerprint(module)
res = module.load_state_dict(sd, strict=False)
after = fingerprint(module)
print(f"load_state_dict: missing={len(res.missing_keys)} "
      f"unexpected={len(res.unexpected_keys)}")
changed = sum(1 for (ka, va), (kb, vb) in zip(before, after) if va != vb)
print("fingerprint before:", before)
print("fingerprint after: ", after)
if changed == 0:
    raise SystemExit(
        "FATAL: every sampled parameter is byte-identical after the load. The "
        "counts said the tensors matched, so the load was a NO-OP — either the "
        "checkpoint holds the stock weights, or it was loaded into a copy. "
        "This is exactly the case that would have shipped as 'the fine-tune'.")
print(f"swap confirmed: {changed}/{len(before)} sampled params moved", flush=True)
del sd, raw
import gc                                                      # noqa: E402
gc.collect()
torch.cuda.empty_cache()

# Provenance beside the artefacts. Six months from now "which checkpoint made
# this car?" must be answerable from the bucket, not from a chat log.
meta = {
    "run_id": RUN_ID,
    "ckpt_repo": os.environ.get("ALAM3D_CKPT_REPO_R"),
    "ckpt_path": os.environ.get("ALAM3D_CKPT_PATH_R"),
    "ckpt_bytes": os.path.getsize(ckpt_path),
    "ckpt_sha256_head": hashlib.sha256(
        open(ckpt_path, "rb").read(8 << 20)).hexdigest(),
    "matched": len(matched), "of": len(tgt), "match_rate": round(rate, 6),
    "unexpected": len(unexpected), "missing": len(missing),
    "sampled_params_moved": changed,
    "base_arm": RUN_BASE, "pipeline_type": PIPE, "seed": SEED,
    "max_num_tokens": MAX_TOKENS, "texture_size": TEXTURE,
    "decimation_target": DECIMATE,
    "gpu": torch.cuda.get_device_name(0),
    "cars": [c["tag"] for c in CARS],
}
json.dump(meta, open("/workspace/run_meta.json", "w"), indent=1)
push("/workspace/run_meta.json", "run_meta.json")

# --------------------------------------------------------------- TUNED ARM
for car in CARS:
    produced.append(generate(car, "alam3d"))

mark("verify")
want = len(CARS) * (2 if RUN_BASE else 1)
have = [p for p in produced if os.path.exists(p) and os.path.getsize(p) > 10_000]
print(f"artefacts: {len(have)}/{want}")
for p in sorted(glob.glob("/workspace/*.glb")):
    print(f"  {os.path.getsize(p)//1024:>8}KB  {os.path.basename(p)}")
if len(have) != want:
    raise SystemExit("FATAL: fewer GLBs than arms x cars")
print("ALAM3D_GENERATION_COMPLETE", flush=True)
PYGEN
python3 -m py_compile /workspace/alam3d_gen.py || die GEN_SYNTAX

stage generate
export ALAM3D_CKPT_REPO_R="$CKPT_REPO" ALAM3D_CKPT_PATH_R="$CKPT_PATH"
export ALAM3D_PRE="$PRE"
# LOG PUSHER. Generation is 20-40 minutes of one process; without this the
# launcher would see no marker move for that whole window and could not tell
# work from a wedge. The python above prints its own "=== STAGE:… ===" lines;
# this ships the log so the launcher can read them.
( while sleep 60; do report "log.txt"; done ) &
PUSH_PID=$!
# KILL BY PID, never by pattern. `pkill -f` on a broad pattern has killed this
# session's own shell (exit 144) more than once, and `pgrep -f` matches the
# harness wrapper whose command line CONTAINS the pattern — a guard that
# matches itself never exits.
python3 -u /workspace/alam3d_gen.py
RC=$?
kill "$PUSH_PID" 2>/dev/null || true
echo "GENERATE_EXIT=$RC"
[ "$RC" = "0" ] || die GENERATE

stage upload_log
# The GLBs uploaded themselves as they finished (a late failure can never lose
# an early car). This is the tail: logs and the provenance record.
sb_file "log.txt" "$LOG"
[ -f /workspace/run_meta.json ] && sb_file "run_meta.json" /workspace/run_meta.json

stage done
# LAST GATE, and it is not decoration. RC=0 with no artefact must fail loudly:
# on 2026-08-20 `python3 run.py … | tail` made $? the status of TAIL, a crashed
# inference read as success, and only the no-output check caught it. Here the
# exit code is read directly (no pipe), and the artefacts are counted anyway.
N=$(ls /workspace/*.glb 2>/dev/null | wc -l)
echo "GLBs produced: $N"
[ "$N" -gt 0 ] || die NO_OUTPUT
echo "=== ALAM3D_OK ==="
report "log.txt"
# Never exit. An exiting dockerStartCmd is restarted by RunPod, which re-clones,
# re-downloads the weights and starts over — forever, at 0% GPU, while the API
# happily reports desiredStatus RUNNING. The launcher deletes the pod.
sleep infinity
