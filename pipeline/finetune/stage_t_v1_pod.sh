#!/bin/bash
# stage_t_v1_pod.sh — Stage T: first-ever fine-tune of the TEXTURE flow model
# (slat_flow_imgshape2tex_dit_1_3B_512) on the audited car set.
#
# WHY TEXTURE: the owner's own audit rubric fails cars on "grille edges soft,
# honeycomb texture shallow, headlights lacking sharp internal LED elements,
# shut lines not defined" — every one a TEXTURE-stage property. The shape run
# (Stage C v1) cannot touch them; its eval showed shape gains peaking at step
# 500 while texture stayed stock, because the texture model has never seen a
# single training step. This run is the direct attack on the rubric.
#
# DATA: pbr latents exist only because texture_unblock_pod.sh merged the
# per-directory pbr_dumped flags (821 of 964 rows) and ran voxelize_pbr +
# encode_pbr_latent — steps that had silently matched ZERO rows since Stage A.
# This script hard-gates on those latents actually existing.
#
# Inherits every gate the shape runs paid for, adapted:
#   arch-check     - live conv2d+matmul (the arch LIST lies: it shows sm_90 and
#                    an H100 still died in cuDNN)
#   gated-check    - DINOv3 conditioner 401s exit ZERO having trained nothing
#   space/write    - the volume truncated a 5.2GB checkpoint at 236/250GB
#   build-meta     - pool = pbr-latent shapes ∩ human keep-verdict, banded.
#                    NOT the v1 mtime-anchor: that anchored on the v0 run dir,
#                    which was PURGED on 2026-07-28 — a blind copy would FATAL.
#   build-config   - the REAL lr lives at optimizer.args.lr; the banner gate
#                    proves it end-to-end (every earlier run trained at 1e-4
#                    while logging something else)
#   G2 (inverted)  - FRESH run: the init marker must be PRESENT and must name
#                    imgshape2tex. Marker absent = trained random weights;
#                    marker naming img2shape = initialised from the wrong
#                    released stage. If checkpoints already exist in OUT this
#                    flips to resume mode and the marker must be ABSENT.
#   G3             - trainer's "Total instances" must equal the private
#                    metadata rows, or the cull did not reach the trainer
#   no-ckpt guard  - exit 0 is not proof of training
#
# Secrets via pod env only. MAX_STEPS from env (balance decides, not a round
# number); i_save 250 so any abort leaves usable checkpoints.
ROOT=/workspace/alamcars
OUT=/workspace/alam3d_stage_t_v1
AUG="$ROOT/renders_cond_aug"
CFG_SRC="configs/gen/slat_flow_imgshape2tex_dit_1_3B_512_bf16.json"
CFG_OUT="$ROOT/stage_t_v1_cfg.json"
LR_WANT="5e-06"
mkdir -p "$OUT/logs"
( cd "$OUT/logs" && python3 -m http.server 8000 >/dev/null 2>&1 & )
RUN_LOG="stage_t_v1_$(hostname)_$(date -u +%Y%m%dT%H%M%SZ).log"
ln -sf "$RUN_LOG" "$OUT/logs/stage_b.log"
exec > >(tee -a "$OUT/logs/$RUN_LOG") 2>&1
status(){ printf '{"step":"%s","at":"%s"}\n' "$1" "$(date -u +%FT%TZ)" > "$OUT/logs/status.json"; echo "===== $1 ====="; }

status boot
[ -f /etc/rp_environment ] && source /etc/rp_environment
export HF_TOKEN HUGGING_FACE_HUB_TOKEN 2>/dev/null
[ -n "$HF_TOKEN" ] && echo "HF token: present (${#HF_TOKEN} chars)" || echo "HF token: MISSING from env"
nvidia-smi -L || true
cd /app/TRELLIS.2 || { status FATAL-no-trellis2; sleep infinity; }
export PYTHONPATH=/app/TRELLIS.2:$PYTHONPATH
# python block-buffers stdout through the tee pipe; a run that prints nothing
# for 80 minutes is indistinguishable from a hung one
export PYTHONUNBUFFERED=1
pip install -q tensorboard pandas easydict || true
pip install -q "transformers==4.57.6" || true

status config-exists
# The texture config name is inferred from the shape config's naming scheme.
# Inference is not knowledge: prove the file exists before anything costs money,
# and if it does not, print what IS there so the fix needs no second pod.
if [ ! -f "$CFG_SRC" ]; then
  echo "FATAL: $CFG_SRC not found. configs/gen holds:"
  ls -1 configs/gen/ | sed 's/^/    /'
  status FATAL-no-config; sleep infinity
fi
echo "config present: $CFG_SRC"

status arch-check
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
# The arch list is context, NOT the gate — it shows sm_90 and an H100 still
# died at the first F.conv2d (cuDNN ships kernels the list says nothing about).
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

status gated-check
# DINOv3 is gated; without a valid token the trainer retries 3x then EXITS ZERO
# having trained nothing. Fail here, before a GPU-hour is spent.
DINO="https://huggingface.co/facebook/dinov3-vitl16-pretrain-lvd1689m/resolve/main/config.json"
CODE=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer ${HF_TOKEN}" "$DINO")
echo "gated conditioner check: HTTP $CODE"
if [ "$CODE" != "200" ]; then
  echo "FATAL: cannot read the DINOv3 conditioner (HTTP $CODE)."
  echo "       HF_TOKEN is ${HF_TOKEN:+present but rejected}${HF_TOKEN:-MISSING from the pod env}."
  status FATAL-gated-conditioner; sleep infinity
fi

status preflight
python3 - <<'PY' || { status FATAL-preflight; sleep infinity; }
import glob, os, sys
aug = "/workspace/alamcars/renders_cond_aug"
if not os.path.isdir(aug):
    print("FATAL: renders_cond_aug missing — the texture conditioner needs the "
          "same photo-domain augmented views the shape run needed"); sys.exit(1)
if not os.path.exists(os.path.join(aug, "metadata.csv")):
    print("FATAL: renders_cond_aug/metadata.csv missing — loader cannot index"); sys.exit(1)
# free space + writability: this volume has truncated a checkpoint before
import shutil
t, u, f = shutil.disk_usage("/workspace")
gb = 1024 ** 3
need = float(os.environ.get("MIN_FREE_GB", "35"))
print(f"/workspace: {u/gb:.0f}GB used of {t/gb:.0f}GB, {f/gb:.0f}GB free (need {need:.0f}GB)")
if f / gb < need:
    print("FATAL: not enough headroom for checkpoints"); sys.exit(1)
p = "/workspace/_t1_probe"
with open(p, "wb") as fh:
    fh.write(b"X" * 32_000_000); fh.flush(); os.fsync(fh.fileno())
ok = os.path.getsize(p) == 32_000_000
os.remove(p)
print("volume writable:", ok)
sys.exit(0 if ok else 1)
PY

status patch-upstream
grep -rl "def snapshot" trellis2/trainers | while read f; do
  python3 - "$f" <<'PY'
import re, sys
p=sys.argv[1]; s=open(p).read()
if "ALAM3D_NO_SNAPSHOT" in s: sys.exit()
s2,n=re.subn(r"(\n(\s+)def snapshot\(self[^)]*\):\n)",
             r"\1\2    import os\n\2    if os.environ.get('ALAM3D_NO_SNAPSHOT'):\n\2        print('snapshot skipped')\n\2        return\n", s)
open(p,"w").write(s2)
print(f"patched snapshot x{n} in {p}")
PY
done
export ALAM3D_NO_SNAPSHOT=1
python3 - <<'PY'
s=open("train.py").read()
if "ALAM3D_INIT_FROM" not in s:
    anchor="    # Build trainer"
    inject=("    _init = os.environ.get('ALAM3D_INIT_FROM')\n"
            "    if _init and cfg.load_ckpt is None:\n"
            "        _src = models.from_pretrained(_init)\n"
            "        model_dict['denoiser'].load_state_dict(_src.state_dict())\n"
            "        del _src\n"
            "        print(f'[alam3d] denoiser initialised from {_init} (rank {rank})')\n\n")
    assert anchor in s
    open("train.py","w").write(s.replace(anchor, inject+anchor))
    print("patched train.py: HF weight init")
else:
    print("train.py already carries the init patch")
PY
# init from Microsoft's released TEXTURE weights — the imgshape2tex stage, not
# the img2shape stage the shape runs used. G2 below proves the right name
# reached the trainer.
export ALAM3D_INIT_FROM="microsoft/TRELLIS.2-4B/ckpts/slat_flow_imgshape2tex_dit_1_3B_512_bf16"

status build-meta
# Pool = shapes that HAVE a pbr latent ∩ the human keep-verdict. No mtime
# anchor: v1's anchor was the v0 run directory, purged 2026-07-28.
python3 - <<'PY' || { status FATAL-meta; sleep infinity; }
import glob, json, os, sys, time, urllib.request
import pandas as pd

lat = set()
for d in glob.glob("/workspace/alamcars/pbr_latents/*/"):
    for f in glob.glob(d + "*.npz") + glob.glob(d + "*.pt"):
        lat.add(os.path.splitext(os.path.basename(f))[0])
print(f"pbr latents on volume: {len(lat)}")
if not lat:
    print("FATAL: zero pbr latents — texture_unblock_pod.sh has not succeeded "
          "on this volume; there is nothing to train on"); sys.exit(1)

VERDICT = ("https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object/public/"
           "car-meshes/audit/train/CULL_VERDICT.json")
try:
    rows = json.loads(urllib.request.urlopen(VERDICT + f"?cb={int(time.time())}",
                                             timeout=120).read())
except Exception as e:
    print(f"FATAL: cannot read the cull verdict ({type(e).__name__}: {str(e)[:60]}). "
          f"Refusing to train on an unaudited set."); sys.exit(1)
by_sha = {r["sha256"]: r["verdict"] for r in rows}
keep    = sorted(s for s in lat if by_sha.get(s) == "keep")
culled  = [s for s in lat if by_sha.get(s) == "cull"]
unknown = [s for s in lat if s not in by_sha]
print(f"of {len(lat)} latent shapes: {len(keep)} keep, {len(culled)} culled, "
      f"{len(unknown)} not in the verdict (EXCLUDED — texture pool is "
      f"keep-verdict only)")
floor = int(os.environ.get("TEX_MIN_POOL", "150"))
if len(keep) < floor:
    print(f"FATAL: only {len(keep)} audited-keep shapes have pbr latents "
          f"(floor {floor}). The texture data is thinner than expected — "
          f"check the unblock run before spending training money."); sys.exit(1)

# VERIFY THE IMAGES, NOT THE FLAGS. Run 1 died at the first batch with
# OpenCV's "!_src.empty()": the pool here is latents ∩ keep-verdict, which
# admits ~133 shapes Stage C never trained, and renders_cond_aug predates
# them — so metadata said "Cond rendered: 429" while the files for some
# shapes were absent or empty. Metadata is a claim; only opening the file is
# a fact. For each pool shape: verify the aug dir has readable images; if
# not, fall back to copying the PRISTINE renders_cond images in (augmentation
# is a robustness nicety, not a requirement); drop the shape only if neither
# location has a single readable image.
import shutil
from PIL import Image
AUG = "/workspace/alamcars/renders_cond_aug"
SRC = "/workspace/alamcars/renders_cond"
EXT = (".png", ".jpg", ".jpeg", ".webp")

def readable(d):
    n = 0
    for f in glob.glob(os.path.join(d, "*")):
        if not f.lower().endswith(EXT):
            continue
        try:
            if os.path.getsize(f) == 0:
                return 0          # one empty image can kill a batch; reject the dir
            with Image.open(f) as im:
                im.verify()
            n += 1
        except Exception:
            return 0
    return n

verified, healed, dropped = [], [], []
for sha in keep:
    if readable(os.path.join(AUG, sha)) > 0:
        verified.append(sha)
        continue
    src_ok = readable(os.path.join(SRC, sha))
    if src_ok > 0:
        os.makedirs(os.path.join(AUG, sha), exist_ok=True)
        for f in glob.glob(os.path.join(SRC, sha, "*")):
            if f.lower().endswith(EXT):
                shutil.copy2(f, os.path.join(AUG, sha, os.path.basename(f)))
        healed.append(sha)
        verified.append(sha)
    else:
        dropped.append(sha)
print(f"image verification: {len(verified)} pool shapes have readable cond "
      f"images ({len(healed)} healed from pristine renders), {len(dropped)} "
      f"dropped with no readable images anywhere")
for s in dropped[:10]:
    print(f"  dropped: {s[:16]}")
keep = verified
if len(keep) < floor:
    print(f"FATAL: after image verification the pool is {len(keep)} "
          f"(floor {floor})"); sys.exit(1)

p = "/workspace/alamcars/metadata.csv"
m = pd.read_csv(p).set_index("sha256")
merged = 0
for pat in ("/workspace/alamcars/*/metadata.csv", "/workspace/alamcars/*/*/metadata.csv",
            "/workspace/alamcars/**/new_records/part_*.csv"):
    for f in glob.glob(pat, recursive=True):
        if f == p: continue
        try:
            df = pd.read_csv(f)
            if "sha256" in df.columns:
                m = df.set_index("sha256").combine_first(m); merged += 1
        except Exception:
            pass
if "aesthetic_score" not in m.columns:
    m["aesthetic_score"] = 6.0
m["aesthetic_score"] = pd.to_numeric(m["aesthetic_score"], errors="coerce").fillna(6.0)
m = m[m.index.isin(keep)]
priv = "/workspace/alam3d_stage_t_v1/meta"
os.makedirs(priv, exist_ok=True)
m.reset_index().to_csv(f"{priv}/metadata.csv", index=False)
print(f"merged {merged} record files; private metadata rows: {len(m)}")
if len(m) < len(keep) - 5:
    print(f"FATAL: metadata lost rows — {len(m)} for {len(keep)} shapes"); sys.exit(1)
PY

status build-data-roots
DATA_JSON=$(python3 - <<'PYIN'
import glob, json
root = "/workspace/alamcars"
def pick(pattern):
    g = sorted(glob.glob(pattern))
    return g[0].rstrip("/") if g else None
roots = {"meta": "/workspace/alam3d_stage_t_v1/meta",
         "render_cond": root + "/renders_cond_aug",
         "shape_latent": pick(root + "/shape_latents/*/"),
         "ss_latent": pick(root + "/ss_latents/*/"),
         "pbr_latent": pick(root + "/pbr_latents/*/")}
print(json.dumps({"AlamCars": {k: v for k, v in roots.items() if v}}))
PYIN
)
echo "data roots: $DATA_JSON"
case "$DATA_JSON" in
  *pbr_latents*) echo "confirmed: pbr latent root present";;
  *) echo "FATAL: no pbr latent root resolved"; status FATAL-roots; sleep infinity;;
esac
case "$DATA_JSON" in *renders_cond_aug*) echo "confirmed: augmented conditioning views";;
  *) echo "FATAL: data roots not pointing at renders_cond_aug"; status FATAL-roots; sleep infinity;; esac

status mode-check
# Fresh run or resume? Decided by what is on disk, and G2 below is inverted
# accordingly. A truncated checkpoint must be caught BEFORE the trainer eats it.
RESUME=0
if [ -n "$(ls -A "$OUT/ckpts" 2>/dev/null)" ]; then
  RESUME=1
  python3 - <<'PYRES' || { status FATAL-resume-ckpt; sleep infinity; }
import glob, os, re, sys, zipfile
good = []
for path in sorted(glob.glob("/workspace/alam3d_stage_t_v1/ckpts/*.pt")):
    sz = os.path.getsize(path)
    try:
        with zipfile.ZipFile(path):
            pass
        m = re.search(r"step0*(\d+)", os.path.basename(path))
        good.append((int(m.group(1)) if m else -1, os.path.basename(path)))
        print("  ok      %s (%.0fMB)" % (os.path.basename(path), sz / 1e6))
    except Exception as e:
        print("  CORRUPT %s (%.0fMB) %s" % (os.path.basename(path), sz / 1e6, type(e).__name__))
if not good:
    print("FATAL: checkpoints exist but none are readable"); sys.exit(1)
print("RESUME FROM step %d" % max(good)[0])
PYRES
fi
echo "mode: $([ "$RESUME" = 1 ] && echo resume || echo fresh-init from released texture weights)"

status build-config
python3 - <<'PY' || { status FATAL-config; sleep infinity; }
import json, os, sys
LR = 5e-6
c = json.load(open("configs/gen/slat_flow_imgshape2tex_dit_1_3B_512_bf16.json"))
t = c["trainer"]["args"]
t.update({"max_steps": int(os.environ.get("MAX_STEPS", "1000")), "i_log": 10,
          "i_save": 250, "i_sample": 10**9,
          "batch_size_per_gpu": 4, "batch_split": 4, "learning_rate": LR})
# the REAL lr lives at optimizer.args.lr; learning_rate is decorative
opt = t.setdefault("optimizer", {}).setdefault("args", {})
was = opt.get("lr")
opt["lr"] = LR
print(f"optimizer lr: {was} -> {opt['lr']}")
c["dataset"]["args"]["min_aesthetic_score"] = 0.0
c["dataset"]["args"]["max_tokens"] = 32768
json.dump(c, open("/workspace/alamcars/stage_t_v1_cfg.json", "w"), indent=1)
rb = json.load(open("/workspace/alamcars/stage_t_v1_cfg.json"))
eff = float(rb["trainer"]["args"]["optimizer"]["args"]["lr"])
if eff != LR:
    print(f"FATAL: config on disk has lr {eff}, expected {LR}"); sys.exit(1)
_ms = rb["trainer"]["args"]["max_steps"]; _is = rb["trainer"]["args"]["i_save"]
print(f"t1 config: {_ms} steps, OPTIMIZER lr {eff}, save every {_is} "
      f"({_ms // _is} sweepable checkpoints)  dataset={c['dataset'].get('name', c['dataset'])}")
PY

status tryrun
python3 -u train.py --config /workspace/alamcars/stage_t_v1_cfg.json \
  --output_dir "$OUT" --data_dir "$DATA_JSON" --tryrun \
  || { echo "TRYRUN FAILED — dumping the dataset class so the fix needs no second pod";
       python3 - <<'PYDBG'
import json, glob
cfg = json.load(open("/workspace/alamcars/stage_t_v1_cfg.json"))
print("dataset section:", json.dumps(cfg.get("dataset", {}), indent=1)[:800])
for f in glob.glob("trellis2/datasets/*.py") + glob.glob("datasets/*.py"):
    src = open(f).read()
    if "pbr" in src.lower() or "tex" in src.lower():
        print(f"--- {f} (first 80 lines) ---")
        print("\n".join(src.splitlines()[:80]))
PYDBG
       status FATAL-tryrun; sleep infinity; }

BANNER_LR=$(grep -a "^  - Learning rate:" "$OUT/logs/$RUN_LOG" | tail -1 | awk '{print $NF}')
echo "trainer reports effective learning rate: ${BANNER_LR:-<none found>}"
case "$BANNER_LR" in
  5e-06|5.0e-06|0.000005) echo "learning rate confirmed at the optimizer" ;;
  "") echo "FATAL: no learning-rate banner — cannot confirm the rate"
      status FATAL-lr-unverified; sleep infinity ;;
  *)  echo "FATAL: trainer will optimise at $BANNER_LR, not 5e-06."
      status FATAL-lr-mismatch; sleep infinity ;;
esac

# G2 — WHICH WEIGHTS DID THIS RUN START FROM? Inverted by mode.
MARK=$(grep -a "\[alam3d\] denoiser initialised from" "$OUT/logs/$RUN_LOG" | tail -1)
if [ "$RESUME" = 1 ]; then
  if [ -n "$MARK" ]; then
    echo "FATAL: trainer re-initialised from released weights instead of resuming."
    status FATAL-not-resumed; sleep infinity
  fi
  echo "confirmed: resumed from checkpoint (no init marker)"
else
  if [ -z "$MARK" ]; then
    echo "FATAL: fresh run but no init marker — the trainer started from RANDOM"
    echo "       weights, not the released texture model."
    status FATAL-no-init; sleep infinity
  fi
  case "$MARK" in
    *imgshape2tex*) echo "confirmed: initialised from released TEXTURE weights" ;;
    *) echo "FATAL: initialised from the WRONG stage: $MARK"
       status FATAL-wrong-init; sleep infinity ;;
  esac
fi

# G3 — the cull must reach the trainer
INSTANCES=$(grep -a "Total instances:" "$OUT/logs/$RUN_LOG" | tail -1 | awk '{print $NF}')
WANT=$(python3 -c "import csv;print(sum(1 for _ in csv.DictReader(open('$OUT/meta/metadata.csv'))))")
echo "trainer reports $INSTANCES instances; private metadata holds $WANT rows"
if [ "$INSTANCES" != "$WANT" ]; then
  echo "FATAL: the trainer is not training the set we selected."
  status FATAL-instance-count; sleep infinity
fi
echo "confirmed: training exactly $INSTANCES audited shapes"

status train
python3 -u train.py --config /workspace/alamcars/stage_t_v1_cfg.json \
  --output_dir "$OUT" --data_dir "$DATA_JSON" \
  || { echo "TRAIN FAILED (see log)"; status FATAL-train; sleep infinity; }

# exit 0 is not proof of training
if [ -z "$(ls -A "$OUT/ckpts" 2>/dev/null)" ]; then
  echo "TRAIN PRODUCED NO CHECKPOINTS — exit code lied"
  status FATAL-no-ckpts; sleep infinity
fi
echo "checkpoints written: $(ls "$OUT/ckpts" | wc -l) files"

status export-loss
python3 - <<'PY'
import glob
try:
    from tensorboard.backend.event_processing.event_accumulator import EventAccumulator
    for ev in sorted(glob.glob("/workspace/alam3d_stage_t_v1/**/events.out.tfevents.*", recursive=True)):
        ea = EventAccumulator(ev); ea.Reload()
        for tag in ea.Tags().get("scalars", []):
            if "loss" in tag.lower():
                pts = ea.Scalars(tag)
                if not pts: continue
                s = pts[::max(1, len(pts)//25)]
                print(f"T1_LOSS {tag} ({len(pts)} pts): " + ", ".join(f"{p.step}:{p.value:.4f}" for p in s))
except Exception as e:
    print("loss export failed:", e)
PY

status verify-ckpts
# a checkpoint that will not open is not a checkpoint
python3 - <<'PY' || { status FATAL-ckpt-verify; sleep infinity; }
import glob, os, sys, zipfile
bad = 0
for p in sorted(glob.glob("/workspace/alam3d_stage_t_v1/ckpts/*.pt")):
    sz = os.path.getsize(p) / 1e6
    try:
        with zipfile.ZipFile(p) as z:
            n = len(z.namelist())
        print(f"  ok      {os.path.basename(p)} ({sz:.0f}MB, {n} entries)")
    except Exception as e:
        bad += 1
        print(f"  CORRUPT {os.path.basename(p)} ({sz:.0f}MB) {type(e).__name__}")
if bad:
    print(f"{bad} corrupt checkpoint(s) — the volume is eating saves again")
    sys.exit(1)
PY

status DONE
df -h /workspace | tail -1
sleep infinity
