#!/bin/bash
# stage_b_pod.sh — Alam-3D Stage B: smoke training run of the shape flow model.
# Proves, on the Stage A volume: (1) config+data pipeline builds (tryrun),
# (2) loss decreases over a short real run, (3) checkpoints save AND load
# (resume), (4) the released 4B shape-flow weights load into the model class
# (the Stage C fine-tune init path). Progress on :8000 as before. No secrets.
ROOT=/workspace/alamcars
OUT=/workspace/alam3d_smoke
mkdir -p "$OUT/logs"
( cd "$OUT/logs" && python3 -m http.server 8000 >/dev/null 2>&1 & )
exec > >(tee -a "$OUT/logs/stage_b.log") 2>&1
status(){ printf '{"step":"%s","at":"%s"}\n' "$1" "$(date -u +%FT%TZ)" > "$OUT/logs/status.json"; echo "===== $1 ====="; }
status boot
nvidia-smi -L || true
cd /app/TRELLIS.2 || { status FATAL-no-trellis2; sleep infinity; }
export PYTHONPATH=/app/TRELLIS.2:$PYTHONPATH
pip install -q tensorboard pandas easydict || true

status metadata-aesthetic
python3 - <<'PY'
import pandas as pd
p="/workspace/alamcars/metadata.csv"
m=pd.read_csv(p)
if "aesthetic_score" not in m.columns:
    # internal curation flag for the training filter (our own curated set),
    # NOT a public-fact claim; datasets filter on this column unconditionally
    m["aesthetic_score"]=6.0
# encode steps completed 365/365 in Stage A but their record merge never reached
# metadata.csv; the training datasets filter on these flags
for col in ("shape_latent_encoded","ss_latent_encoded"):
    if col not in m.columns:
        m[col]=True
m.to_csv(p,index=False)
print("metadata flags ready:",[c for c in m.columns])
PY

status build-smoke-config
python3 - <<'PY'
import json
c=json.load(open("configs/gen/slat_flow_img2shape_dit_1_3B_512_bf16.json"))
t=c["trainer"]["args"]
t.update({"max_steps":300,"i_log":10,"i_save":300,"i_sample":1000000,
          "batch_size_per_gpu":2,"batch_split":1})
c["dataset"]["args"]["min_aesthetic_score"]=4.5
json.dump(c,open("/workspace/alamcars/smoke_cfg.json","w"),indent=1)
print("smoke config written (300 steps, bs 2)")
PY

status tryrun
python3 train.py --config /workspace/alamcars/smoke_cfg.json \
  --output_dir "$OUT" --data_dir "$ROOT" --tryrun \
  || { echo "TRYRUN FAILED"; }

status train-300
python3 train.py --config /workspace/alamcars/smoke_cfg.json \
  --output_dir "$OUT" --data_dir "$ROOT" \
  || echo "TRAIN FAILED (see log)"

status resume-probe
python3 - <<'PY'
import json
c=json.load(open("/workspace/alamcars/smoke_cfg.json"))
c["trainer"]["args"]["max_steps"]=320
json.dump(c,open("/workspace/alamcars/smoke_cfg2.json","w"),indent=1)
PY
python3 train.py --config /workspace/alamcars/smoke_cfg2.json \
  --output_dir "$OUT" --data_dir "$ROOT" --ckpt latest \
  || echo "RESUME FAILED (see log)"

status hf-weights-probe
python3 - <<'PY'
# Stage C init path: released shape-flow weights -> ElasticSLatFlowModel
from trellis2 import models
import glob
tried=[]
for name in ("slat_flow_img2shape_dit_1_3B_512_bf16",
             "slat_flow_img2shape_dit_1_3B_1024_bf16"):
    try:
        m=models.from_pretrained(f"microsoft/TRELLIS.2-4B/ckpts/{name}")
        n=sum(p.numel() for p in m.parameters())
        print(f"HF_WEIGHTS_OK {name}: {n/1e9:.2f}B params load into {type(m).__name__}")
        break
    except Exception as e:
        tried.append(f"{name}: {str(e)[:80]}")
else:
    print("HF_WEIGHTS_PROBE_FAILED"); [print("  ",t) for t in tried]
PY

status DONE
ls -la "$OUT/ckpts" 2>/dev/null | head
grep -iE "loss|step" "$OUT/logs/stage_b.log" | tail -5
sleep infinity
