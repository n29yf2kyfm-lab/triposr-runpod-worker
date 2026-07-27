#!/bin/bash
# stage_c_v1_pod.sh — Stage C, second attempt. Fixes what the evidence showed.
#
# WHY v0 FAILED (measured 2026-07-27, not guessed):
#   * four-way isolation: the tuned 512 stage carries the damage; the tuned
#     1024 refiner is clean.
#   * training-set audit: Stage C's 365 shapes are almost all real cars, so
#     "bad assets" is NOT the cause — that theory was disproved by measurement.
#   * checkpoint sweep on photos: quality degrades monotonically with steps.
#     1000 is closest to stock; the roof artefact appears at 2000 and grows.
#   * the SAME checkpoints fed a Blender render of an unseen car produce a
#     clean vehicle at every step count.
#   => v0 narrowed onto the render domain over 6000 steps and real photos fell
#      outside it. The fix is the input distribution and the dose, not the assets.
#
# WHAT CHANGES:
#   renders_cond -> renders_cond_aug   tone/sensor/alpha-edge augmented views
#   6000 steps   -> 2000               damage starts ~2000; stop at the edge
#   lr 1e-5      -> 5e-6               half the drift per step
#   i_save 1000  -> 250                8 checkpoints: the balance may force an
#                                      early stop, and every stop must leave a
#                                      usable checkpoint behind
#   365 shapes   -> the audited subset  culls applied (see below)
#
# RESUME RUN (2026-07-27 evening). This continues from the step-500
# checkpoint of the first correctly-configured run rather than restarting.
# Target comes from MAX_STEPS, set by the remaining balance, not by a round
# number: checkpoints land every 250 steps so stopping early always leaves
# something usable, and the run can be killed at any point without loss.
#
# Three gates now sit in front of the GPU spend, each reading what the
# PROGRAM reports rather than what this script printed:
#   resume-check  - every checkpoint zip-verified, highest intact step chosen
#   G2            - aborts if the trainer re-initialised from stock weights
#   G3            - aborts if instance count != the audited metadata rows
#
# ON THE ASSET SET — this changed after the file was first written, and the
# reason is worth keeping. The plan was to hold the 365 fixed so exactly one
# variable moved against a known-bad baseline. Then every shape was audited
# individually and the 365 turned out to contain unmarked police cars, a
# race-team car, a photogrammetry scan and several vans. Holding those in for
# experimental purity means paying ten hours to teach the model things we will
# then have to untrain. The pool is now filtered by
# car-meshes/audit/train/CULL_VERDICT.json at build-meta time.
#
# The comparison against v0 is therefore no longer single-variable. That is a
# real cost and it is accepted deliberately: the previous statement that the
# 365 were "almost all real cars" came from a coarser check than the per-shape
# audit that replaced it.
ROOT=/workspace/alamcars
OUT=/workspace/alam3d_stage_c_v1
AUG="$ROOT/renders_cond_aug"
mkdir -p "$OUT/logs"
( cd "$OUT/logs" && python3 -m http.server 8000 >/dev/null 2>&1 & )
RUN_LOG="stage_c_v1_$(hostname)_$(date -u +%Y%m%dT%H%M%SZ).log"
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
# Run 3 spent 80 minutes at 100% GPU printing NOTHING: python block-buffers
# stdout through the tee pipe, and i_log lines are ~100 bytes, so the first
# flush was hundreds of steps away. Unbuffered output is the difference
# between a measurable run and a blind one.
export PYTHONUNBUFFERED=1
pip install -q tensorboard pandas easydict || true
pip install -q "transformers==4.57.6" || true

status gated-check
# DINOv3 is the image conditioner and it is a GATED repo. Without a valid
# HF_TOKEN the trainer 401s, prints "Retrying (1/3)", burns three attempts and
# then EXITS ZERO having trained nothing — the pod looks busy, the GPU shows
# activity, and the log says "Starting training..." forever. Run 4 lost 20
# minutes to exactly this because the launcher had no HF_TOKEN in its env.
# Fail here, loudly, before a single GPU-hour is spent.
DINO="https://huggingface.co/facebook/dinov3-vitl16-pretrain-lvd1689m/resolve/main/config.json"
CODE=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer ${HF_TOKEN}" "$DINO")
echo "gated conditioner check: HTTP $CODE"
if [ "$CODE" != "200" ]; then
  echo "FATAL: cannot read the DINOv3 conditioner (HTTP $CODE)."
  echo "       HF_TOKEN is ${HF_TOKEN:+present but rejected}${HF_TOKEN:-MISSING from the pod env}."
  echo "       Training would retry three times and then exit 0 having done nothing."
  status FATAL-gated-conditioner; sleep infinity
fi

status preflight
# Verify the inputs exist BEFORE burning GPU hours. v0's sibling runs were lost
# to a full volume and to a metadata merge that silently trained on 365 of 543;
# both would have been caught by checks this cheap.
python3 - <<'PY' || { status FATAL-preflight; sleep infinity; }
import glob, os, sys
aug = "/workspace/alamcars/renders_cond_aug"
src = "/workspace/alamcars/renders_cond"
if not os.path.isdir(aug):
    print("FATAL: renders_cond_aug missing — run augment_cond_pod.sh first"); sys.exit(1)
# Compare PER DIRECTORY against the source. The first version of this check
# failed on "any empty output dir", which is the wrong rule: the augment run
# reported exactly one empty output, and an empty output is only a fault if the
# INPUT had views to copy. renders_cond is already known to hold a shape with
# no renders (the review pass found 966 of 967 entries had images), so a
# blanket ban would block the run over a harmless pre-existing gap.
lost, empty_src = [], 0
sdirs = sorted(os.path.basename(d.rstrip("/")) for d in glob.glob(src + "/*/"))
for name in sdirs:
    ns = len(glob.glob(f"{src}/{name}/*"))
    nd = len(glob.glob(f"{aug}/{name}/*"))
    if ns == 0:
        empty_src += 1
    elif nd < ns:
        lost.append((name, ns, nd))
print(f"source shape dirs: {len(sdirs)} | empty AT SOURCE (pre-existing): {empty_src}")
print(f"dirs where augmentation LOST views: {len(lost)}")
for name, ns, nd in lost[:10]:
    print(f"  {name[:12]}: src {ns} -> dst {nd}")
if lost:
    print("FATAL: augmentation dropped views"); sys.exit(1)
# writability, so a full volume cannot truncate this run's checkpoints
p = "/workspace/_v1_probe"
with open(p, "wb") as f:
    f.write(b"X" * 32_000_000); f.flush(); os.fsync(f.fileno())
ok = os.path.getsize(p) == 32_000_000
os.remove(p)
print("volume writable:", ok)

# The dataset loader reads a metadata.csv from INSIDE the render root, not just
# the per-shape image folders. The augment pass copied the folders and not that
# file, so run 1 died with "No such file: renders_cond_aug/metadata.csv" after
# burning a pod. Heal it here — copying root-level files is instant and makes
# the run self-sufficient rather than depending on the augment pass being
# re-run correctly.
import shutil
copied = []
for f in glob.glob(src + "/*"):
    if os.path.isdir(f):
        continue
    dst = os.path.join(aug, os.path.basename(f))
    if not os.path.exists(dst):
        shutil.copy2(f, dst); copied.append(os.path.basename(f))
print(f"root-level files copied into renders_cond_aug: {copied or 'none needed'}")
need = os.path.join(aug, "metadata.csv")
if not os.path.exists(need):
    print(f"FATAL: {need} still missing — loader cannot index the dataset")
    sys.exit(1)
print("renders_cond_aug/metadata.csv present")
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
PY
# init from Microsoft's released weights, NOT from the damaged v0 checkpoint
export ALAM3D_INIT_FROM="microsoft/TRELLIS.2-4B/ckpts/slat_flow_img2shape_dit_1_3B_512_bf16"

status build-meta
# Restrict to exactly the shapes v0 trained on, identified the same way the
# subset audit did: latents that existed when v0's run directory was created.
# That method returned 365 — matching the count in v0's own training log, which
# is what makes it trustworthy. Asserted here so a silent drift fails the run.
python3 - <<'PY' || { status FATAL-meta; sleep infinity; }
import glob, os, sys
import pandas as pd

anchor = os.path.getmtime("/workspace/alam3d_stage_c")
lat = {}
for d in glob.glob("/workspace/alamcars/shape_latents/*/"):
    for f in glob.glob(d + "*.npz") + glob.glob(d + "*.pt"):
        sha = os.path.splitext(os.path.basename(f))[0]
        m = os.path.getmtime(f)
        if sha not in lat or m < lat[sha]:
            lat[sha] = m
pre = sorted(s for s, m in lat.items() if m <= anchor)
print(f"v0 training shapes identified: {len(pre)}")
if len(pre) != 365:
    print(f"FATAL: expected 365, got {len(pre)} — the mtime split no longer holds")
    sys.exit(1)

# v1 change: drop the shapes the per-shape audit rejected. v0 trained on all
# 365 including three unmarked police cars, a race-team car, a photogrammetry
# scan and assorted vans — every one of them teaching the model something we
# do not want it to learn.
import json, urllib.request
VERDICT = ("https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object/public/"
           "car-meshes/audit/train/CULL_VERDICT.json")
try:
    rows = json.loads(urllib.request.urlopen(VERDICT + "?cb=" + str(int(os.times()[4])),
                                             timeout=120).read())
except Exception as e:
    print(f"FATAL: cannot read the cull verdict ({type(e).__name__}: {str(e)[:60]}). "
          f"Refusing to train on an unaudited set."); sys.exit(1)
by_sha = {r["sha256"]: r["verdict"] for r in rows}
culled   = [s for s in pre if by_sha.get(s) == "cull"]
ungraded = [s for s in pre if by_sha.get(s) == "ungraded"]
unknown  = [s for s in pre if s not in by_sha]
clean    = [s for s in pre if by_sha.get(s) == "keep" or s in unknown]
print(f"cull verdict: {len(rows)} rows | of v0's {len(pre)}: "
      f"{len(clean)} keep, {len(culled)} culled, {len(ungraded)} ungraded, "
      f"{len(unknown)} not in the verdict (kept — no evidence against them)")
# Bands, not a fixed number: the verdict file is expected to evolve, but a
# collapse to a tiny set or a no-op filter both mean something is wrong.
if not (250 <= len(clean) < len(pre)):
    print(f"FATAL: filtered pool is {len(clean)} of {len(pre)} — outside the sane "
          f"band [250, {len(pre)}). Either the verdict file did not apply or it "
          f"gutted the set; not spending a 10-hour run to find out which.")
    sys.exit(1)
if len(unknown) > 40:
    print(f"FATAL: {len(unknown)} of v0's shapes are absent from the verdict file — "
          f"the audit did not cover this training set"); sys.exit(1)
pre = clean

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
m = m[m.index.isin(pre)]
priv = "/workspace/alam3d_stage_c_v1/meta"
os.makedirs(priv, exist_ok=True)
m.reset_index().to_csv(f"{priv}/metadata.csv", index=False)
print(f"merged {merged} record files; private metadata rows: {len(m)}")
# The guard is relative to the filtered pool, not a hardcoded 350 — with the
# cull applied the pool is deliberately smaller, and a stale constant here
# would have failed the run for doing exactly what it was asked to do.
if len(m) < len(pre) - 5:
    print(f"FATAL: metadata lost rows — {len(m)} for {len(pre)} shapes"); sys.exit(1)
PY

status build-data-roots
DATA_JSON=$(python3 - <<'PYIN'
import glob, json
root = "/workspace/alamcars"
def pick(pattern, prefer=""):
    g = sorted(glob.glob(pattern))
    if not g: return None
    for p in g:
        if prefer and prefer in p: return p.rstrip("/")
    return g[0].rstrip("/")
roots = {"meta": "/workspace/alam3d_stage_c_v1/meta",
         # THE fix: augmented conditioning views, not the pristine render set
         "render_cond": root + "/renders_cond_aug",
         "shape_latent": pick(root + "/shape_latents/*/"),
         "ss_latent": pick(root + "/ss_latents/*/")}
print(json.dumps({"AlamCars": {k: v for k, v in roots.items() if v}}))
PYIN
)
echo "data roots: $DATA_JSON"
case "$DATA_JSON" in *renders_cond_aug*) echo "confirmed: training on AUGMENTED views";;
  *) echo "FATAL: data roots not pointing at renders_cond_aug"; status FATAL-roots; sleep infinity;; esac

status resume-check
# RESUMING. Upstream's find_ckpt populates cfg.load_ckpt from $OUT/ckpts, which
# is what makes a resume happen at all — but a truncated checkpoint loads as
# garbage or explodes hours in. Stage D lost a 5.2GB save to a full volume and
# nobody noticed until the eval. Prove the file before paying for the GPU.
python3 - <<'PYRES' || { status FATAL-resume-ckpt; sleep infinity; }
import glob, os, re, sys, zipfile
ck = sorted(glob.glob("/workspace/alam3d_stage_c_v1/ckpts/*.pt"))
if not ck:
    print("FATAL: nothing to resume from - no checkpoints in OUT/ckpts"); sys.exit(1)
good = []
for path in ck:
    sz = os.path.getsize(path)
    try:
        with zipfile.ZipFile(path):
            pass
        m = re.search(r"step0*(\d+)", os.path.basename(path))
        good.append((int(m.group(1)) if m else -1, os.path.basename(path), sz))
        print("  ok      %s (%.0fMB)" % (os.path.basename(path), sz / 1e6))
    except Exception as e:
        print("  CORRUPT %s (%.0fMB) %s" % (os.path.basename(path), sz / 1e6, type(e).__name__))
if not good:
    print("FATAL: every checkpoint is unreadable"); sys.exit(1)
top = max(good)
print("RESUME FROM step %d (%s, %.0fMB)" % (top[0], top[1], top[2] / 1e6))
if top[0] < 250:
    print("FATAL: highest intact checkpoint is below step 250"); sys.exit(1)
open("/workspace/alam3d_stage_c_v1/.resume_step", "w").write(str(top[0]))
PYRES
RESUME_STEP=$(cat "$OUT/.resume_step")
echo "resume step recorded: $RESUME_STEP"

status build-config
python3 - <<'PY'
import json, os, sys
LR = 5e-6
c = json.load(open("configs/gen/slat_flow_img2shape_dit_1_3B_512_bf16.json"))
t = c["trainer"]["args"]
t.update({"max_steps": int(os.environ.get("MAX_STEPS", "2000")), "i_log": 10, "i_save": 250, "i_sample": 10**9,
          "batch_size_per_gpu": 4, "batch_split": 4, "learning_rate": LR})

# THE LEARNING RATE LIVES IN TWO PLACES AND ONLY ONE OF THEM IS REAL.
# trainer.args.learning_rate is decorative — the optimizer reads
# trainer.args.optimizer.args.lr. Every run this project has done set only the
# decorative one, so v0 (nominally 1e-5) and Stage D (nominally 8e-6) both
# actually trained at the stock 1e-4. Caught 2026-07-27 by reading the trainer's
# own "Learning rate:" banner, which printed 0.0001 while our config said 5e-6.
opt = t.setdefault("optimizer", {}).setdefault("args", {})
was = opt.get("lr")
opt["lr"] = LR
print(f"optimizer lr: {was} -> {opt['lr']}")
if float(opt["lr"]) != LR:
    print("FATAL: optimizer lr did not take"); sys.exit(1)
c["dataset"]["args"]["min_aesthetic_score"] = 0.0
c["dataset"]["args"]["max_tokens"] = 32768
json.dump(c, open("/workspace/alamcars/stage_c_v1_cfg.json", "w"), indent=1)
# read the file back: what we wrote is not proof of what landed on disk
rb = json.load(open("/workspace/alamcars/stage_c_v1_cfg.json"))
eff = float(rb["trainer"]["args"]["optimizer"]["args"]["lr"])
if eff != LR:
    print(f"FATAL: config on disk has lr {eff}, expected {LR}"); sys.exit(1)
# Print the values actually in the config, never a hardcoded copy of them.
# stage_c_pod.sh:142 prints "bs 1/gpu" on the line after setting
# batch_size_per_gpu 4 - a log that lies about its own run. Do not add another.
_ms = rb["trainer"]["args"]["max_steps"]; _is = rb["trainer"]["args"]["i_save"]
print(f"v1 config: {_ms} steps, OPTIMIZER lr {eff}, save every {_is} "
      f"({_ms // _is} sweepable checkpoints)")
PY

status tryrun
python3 -u train.py --config /workspace/alamcars/stage_c_v1_cfg.json \
  --output_dir "$OUT" --data_dir "$DATA_JSON" --tryrun \
  || { echo "TRYRUN FAILED"; status FATAL-tryrun; sleep infinity; }

# End-to-end proof, not config-file proof: the trainer prints the learning rate
# it will actually optimise with. The tryrun above has just printed it. If that
# banner disagrees with what we asked for, the config did not reach the
# optimizer and a 10-hour run at the wrong step size is about to start.
BANNER_LR=$(grep -a "^  - Learning rate:" "$OUT/logs/$RUN_LOG" | tail -1 | awk '{print $NF}')
echo "trainer reports effective learning rate: ${BANNER_LR:-<none found>}"
case "$BANNER_LR" in
  5e-06|5.0e-06|0.000005) echo "learning rate confirmed at the optimizer" ;;
  "") echo "FATAL: no learning-rate banner in the log — cannot confirm the rate"
      status FATAL-lr-unverified; sleep infinity ;;
  *)  echo "FATAL: trainer will optimise at $BANNER_LR, not 5e-06."
      status FATAL-lr-mismatch; sleep infinity ;;
esac

# G2 - PROVE IT RESUMED, by absence of a signal we control.
# Our injected HF-init block only fires when cfg.load_ckpt is None, i.e. when
# the trainer is starting from Microsoft's weights. If it resumed from our
# checkpoint the marker is ABSENT. So the marker appearing means we are about to
# retrain from scratch and throw away step 500.
if grep -qa "\[alam3d\] denoiser initialised from" "$OUT/logs/$RUN_LOG"; then
  echo "FATAL: trainer re-initialised from stock weights instead of resuming."
  echo "       cfg.load_ckpt was None - the step-$RESUME_STEP checkpoint was NOT picked up."
  status FATAL-not-resumed; sleep infinity
fi
echo "confirmed: resumed from checkpoint (no stock re-init marker in the log)"

# G3 - PROVE THE CULL REACHED THE TRAINER.
# The cull survives only because culled rows carry NaN in aesthetic_score, and
# upstream unions metadata across every data root. Add that column anywhere and
# the 474 culled cars silently return. The trainer prints the truth; read it.
INSTANCES=$(grep -a "Total instances:" "$OUT/logs/$RUN_LOG" | tail -1 | awk '{print $NF}')
WANT=$(python3 -c "import csv;print(sum(1 for _ in csv.DictReader(open('$OUT/meta/metadata.csv'))))")
echo "trainer reports $INSTANCES instances; private metadata holds $WANT rows"
if [ "$INSTANCES" != "$WANT" ]; then
  echo "FATAL: the trainer is not training the set we selected."
  status FATAL-instance-count; sleep infinity
fi
echo "confirmed: training exactly $INSTANCES audited shapes"

status train-2000
python3 -u train.py --config /workspace/alamcars/stage_c_v1_cfg.json \
  --output_dir "$OUT" --data_dir "$DATA_JSON" \
  || { echo "TRAIN FAILED (see log)"; status FATAL-train; sleep infinity; }

# Exit code 0 is NOT proof of training. Run 1 hit a missing metadata.csv,
# printed "Retrying (3/3)", then exited ZERO — so this guard never fired and
# the pod reported DONE having trained nothing at all. A run that produced no
# checkpoint did not train, whatever it returned.
if [ -z "$(ls -A "$OUT/ckpts" 2>/dev/null)" ]; then
  echo "TRAIN PRODUCED NO CHECKPOINTS — exit code lied"
  status FATAL-no-ckpts
  sleep infinity
fi
echo "checkpoints written: $(ls "$OUT/ckpts" | wc -l) files"

status export-loss
python3 - <<'PY'
import glob
try:
    from tensorboard.backend.event_processing.event_accumulator import EventAccumulator
    for ev in sorted(glob.glob("/workspace/alam3d_stage_c_v1/**/events.out.tfevents.*", recursive=True)):
        ea = EventAccumulator(ev); ea.Reload()
        for tag in ea.Tags().get("scalars", []):
            if "loss" in tag.lower():
                pts = ea.Scalars(tag)
                if not pts: continue
                s = pts[::max(1, len(pts)//25)]
                print(f"V1_LOSS {tag} ({len(pts)} pts): " + ", ".join(f"{p.step}:{p.value:.4f}" for p in s))
except Exception as e:
    print("loss export failed:", e)
PY

status verify-ckpts
# a checkpoint that will not open is not a checkpoint — this is how v0's Stage D
# step-4000 save was found to be truncated
python3 - <<'PY'
import glob, os, zipfile
for p in sorted(glob.glob("/workspace/alam3d_stage_c_v1/ckpts/*.pt")):
    try:
        with zipfile.ZipFile(p) as z: n = len(z.namelist())
        print(f"OK      {os.path.getsize(p):>13,}  {n:>4} entries  {os.path.basename(p)}")
    except Exception as e:
        print(f"CORRUPT {os.path.getsize(p):>13,}  {type(e).__name__}  {os.path.basename(p)}")
PY

status DONE
sleep infinity
