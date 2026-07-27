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
#   i_save 1000  -> 500                4 checkpoints so the sweep can pick one
#
# WHAT DELIBERATELY DOES NOT CHANGE: the asset set. v1 trains on the SAME 365
# shapes as v0 so exactly one thing varies against a known-bad baseline. A
# bigger pool is v2, once it has been culled; changing both at once would leave
# us unable to say which change helped.
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
pip install -q tensorboard pandas easydict || true
pip install -q "transformers==4.57.6" || true

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
a = [d for d in glob.glob(aug + "/*") if os.path.isdir(d)]
s = [d for d in glob.glob(src + "/*") if os.path.isdir(d)]
empty = [d for d in a if not glob.glob(d + "/*")]
print(f"augmented shape dirs: {len(a)}  (source has {len(s)})")
print(f"empty augmented dirs: {len(empty)}")
if len(a) < len(s) * 0.98 or empty:
    print("FATAL: augmentation incomplete"); sys.exit(1)
# writability, so a full volume cannot truncate this run's checkpoints
p = "/workspace/_v1_probe"
with open(p, "wb") as f:
    f.write(b"X" * 32_000_000); f.flush(); os.fsync(f.fileno())
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
if len(m) < 350:
    print("FATAL: metadata lost rows"); sys.exit(1)
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

status build-config
python3 - <<'PY'
import json
c = json.load(open("configs/gen/slat_flow_img2shape_dit_1_3B_512_bf16.json"))
t = c["trainer"]["args"]
t.update({"max_steps": 2000, "i_log": 10, "i_save": 500, "i_sample": 10**9,
          "batch_size_per_gpu": 4, "batch_split": 4, "learning_rate": 5e-6})
c["dataset"]["args"]["min_aesthetic_score"] = 0.0
c["dataset"]["args"]["max_tokens"] = 32768
json.dump(c, open("/workspace/alamcars/stage_c_v1_cfg.json", "w"), indent=1)
print("v1 config: 2000 steps, lr 5e-6, save every 500 (4 sweepable checkpoints)")
PY

status tryrun
python3 train.py --config /workspace/alamcars/stage_c_v1_cfg.json \
  --output_dir "$OUT" --data_dir "$DATA_JSON" --tryrun \
  || { echo "TRYRUN FAILED"; status FATAL-tryrun; sleep infinity; }

status train-2000
python3 train.py --config /workspace/alamcars/stage_c_v1_cfg.json \
  --output_dir "$OUT" --data_dir "$DATA_JSON" \
  || { echo "TRAIN FAILED (see log)"; status FATAL-train; sleep infinity; }

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
