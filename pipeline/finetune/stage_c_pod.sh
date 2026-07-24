#!/bin/bash
# stage_c_pod.sh — Alam-3D Stage C: the real shape fine-tune.
# Initialises the 1.3B shape flow model from Microsoft's released
# TRELLIS.2-4B weights and fine-tunes it on the full AlamCars dataset
# (short schedule, low LR — domain adaptation, not retraining).
# Gates honoured before this runs: Stage B smoke passed (loss falls,
# ckpt save/load, HF weights load) and the cond-render backfill completed.
# Progress on :8000; the launcher tears the pod down on DONE/FATAL.
ROOT=/workspace/alamcars
OUT=/workspace/alam3d_stage_c
mkdir -p "$OUT/logs"
( cd "$OUT/logs" && python3 -m http.server 8000 >/dev/null 2>&1 & )
RUN_LOG="stage_c_$(hostname)_$(date -u +%Y%m%dT%H%M%SZ).log"
ln -sf "$RUN_LOG" "$OUT/logs/stage_b.log"   # launcher polls this name
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
python3 -c "import transformers; print('transformers', transformers.__version__)"

status patch-upstream
# (1) never sample during training — snapshots cost ~20 GPU-min each and the
# trainer fires them unconditionally at run start plus at step % i_sample == 0
grep -rl "def snapshot" trellis2/trainers | while read f; do
  python3 - "$f" <<'PY'
import re, sys
p=sys.argv[1]; s=open(p).read()
if "ALAM3D_NO_SNAPSHOT" in s: sys.exit()
s2,n=re.subn(r"(\n(\s+)def snapshot\(self[^)]*\):\n)",
             r"\1\2    import os\n\2    if os.environ.get('ALAM3D_NO_SNAPSHOT'):\n\2        print('snapshot skipped (ALAM3D_NO_SNAPSHOT)')\n\2        return\n", s)
open(p,"w").write(s2)
print(f"patched snapshot x{n} in {p}")
PY
done
export ALAM3D_NO_SNAPSHOT=1
# (2) initialise the denoiser from the released weights (train.py builds
# models fresh from config args; no upstream pretrained hook exists)
python3 - <<'PY'
s=open("train.py").read()
if "ALAM3D_INIT_FROM" not in s:
    anchor = "    # Build trainer"
    inject = (
"    _init = os.environ.get('ALAM3D_INIT_FROM')\n"
"    if _init and cfg.load_ckpt is None:\n"
"        _src = models.from_pretrained(_init)\n"
"        model_dict['denoiser'].load_state_dict(_src.state_dict())\n"
"        del _src\n"
"        print(f'[alam3d] denoiser initialised from {_init} (rank {rank})')\n\n")
    assert anchor in s
    s = s.replace(anchor, inject + anchor)
    open("train.py","w").write(s)
    print("patched train.py: HF weight init")
PY
export ALAM3D_INIT_FROM="microsoft/TRELLIS.2-4B/ckpts/slat_flow_img2shape_dit_1_3B_512_bf16"

status export-smoke-loss
python3 - <<'PY'
# print the Stage B smoke run's loss curve (the last unverified smoke verdict)
import glob
try:
    from tensorboard.backend.event_processing.event_accumulator import EventAccumulator
    evs=sorted(glob.glob("/workspace/alam3d_smoke/**/events.out.tfevents.*", recursive=True))
    for ev in evs:
        ea=EventAccumulator(ev); ea.Reload()
        for tag in ea.Tags().get("scalars", []):
            if "loss" in tag.lower():
                pts=ea.Scalars(tag)
                if not pts: continue
                sampled=pts[::max(1,len(pts)//30)]
                print(f"SMOKE_LOSS {tag} ({len(pts)} pts): "+", ".join(f"{p.step}:{p.value:.4f}" for p in sampled))
except Exception as e:
    print("smoke loss export failed:", e)
PY

status metadata-merge
python3 - <<'PYIN'
import glob, pandas as pd
p="/workspace/alamcars/metadata.csv"
m=pd.read_csv(p).set_index("sha256")
merged=0
pats=["/workspace/alamcars/*/metadata.csv","/workspace/alamcars/*/*/metadata.csv",
      "/workspace/alamcars/**/new_records/part_*.csv","/workspace/alamcars/**/merged_records/*.csv"]
seen=set()
for pat in pats:
    for f in glob.glob(pat, recursive=True):
        if f in seen or f=="/workspace/alamcars/metadata.csv": continue
        seen.add(f)
        try:
            df=pd.read_csv(f)
            if "sha256" in df.columns:
                m=df.set_index("sha256").combine_first(m); merged+=1
        except Exception as e:
            print("skip",f,str(e)[:60])
if "aesthetic_score" not in m.columns:
    m["aesthetic_score"]=6.0
m.reset_index().to_csv(p,index=False)
cr=m.get("cond_rendered")
print(f"merged {merged} record files; cond_rendered true: {int(cr.fillna(False).sum()) if cr is not None else '?'} of {len(m)}")
PYIN

status build-data-roots
DATA_JSON=$(python3 - <<'PYIN'
import glob, json
root="/workspace/alamcars"
def first(p):
    g=sorted(glob.glob(p))
    return g[0].rstrip("/") if g else None
roots={"meta": root, "render_cond": root+"/renders_cond",
       "shape_latent": first(root+"/shape_latents/*/"),
       "ss_latent": first(root+"/ss_latents/*/")}
print(json.dumps({"AlamCars": {k:v for k,v in roots.items() if v}}))
PYIN
)
echo "data roots: $DATA_JSON"

status build-finetune-config
python3 - <<'PY'
import json
c=json.load(open("configs/gen/slat_flow_img2shape_dit_1_3B_512_bf16.json"))
t=c["trainer"]["args"]
# short low-LR domain fine-tune: 6000 steps, LR 1e-5 (10x below scratch),
# checkpoint hourly-ish; sampling disabled via ALAM3D_NO_SNAPSHOT.
# Single-A100 economy mode: effective batch 4 via gradient accumulation
# (batch_split micro-batches of 1) — fits 80GB and the account balance.
t.update({"max_steps":6000,"i_log":10,"i_save":1000,"i_sample":10**9,
          "batch_size_per_gpu":4,"batch_split":4,"learning_rate":1e-5})
c["dataset"]["args"]["min_aesthetic_score"]=0.0
c["dataset"]["args"]["max_tokens"]=32768
json.dump(c,open("/workspace/alamcars/stage_c_cfg.json","w"),indent=1)
print("stage C config: 6000 steps, lr 1e-5, bs 1/gpu, save every 1000")
PY

status tryrun
python3 train.py --config /workspace/alamcars/stage_c_cfg.json \
  --output_dir "$OUT" --data_dir "$DATA_JSON" --tryrun \
  || { echo "TRYRUN FAILED"; status FATAL-tryrun; sleep infinity; }

status train-6000
python3 train.py --config /workspace/alamcars/stage_c_cfg.json \
  --output_dir "$OUT" --data_dir "$DATA_JSON" \
  || { echo "TRAIN FAILED (see log)"; status FATAL-train; sleep infinity; }

status export-loss-curve
python3 - <<'PY'
# distil the tensorboard events into a plain-text loss curve for the log
import glob
try:
    from tensorboard.backend.event_processing.event_accumulator import EventAccumulator
    for d in sorted(glob.glob("/workspace/alam3d_stage_c/tb_logs*")+["/workspace/alam3d_stage_c"]):
        for ev in sorted(glob.glob(d+"/**/events.out.tfevents.*", recursive=True)):
            ea=EventAccumulator(ev); ea.Reload()
            for tag in ea.Tags().get("scalars", []):
                if "loss" in tag.lower():
                    pts=ea.Scalars(tag)
                    sampled=pts[::max(1,len(pts)//40)]
                    print(f"LOSS {tag}: "+", ".join(f"{p.step}:{p.value:.4f}" for p in sampled))
except Exception as e:
    print("loss export failed:", e)
PY

status DONE
ls -la "$OUT/ckpts" 2>/dev/null | tail -8
sleep infinity
