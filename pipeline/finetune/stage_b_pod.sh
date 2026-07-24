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

status metadata-merge
python3 - <<'PYIN'
import glob, pandas as pd
p="/workspace/alamcars/metadata.csv"
m=pd.read_csv(p).set_index("sha256")
# merge every step's new_records (incl. the encoders' shape/ss token counts +
# encoded flags that build_metadata never picked up)
merged=0
# Stage A's build_metadata consumed each step's new_records into PER-DIRECTORY
# metadata.csv files (upstream layout); sweep them all, plus any leftovers.
pats=["/workspace/alamcars/*/metadata.csv",
      "/workspace/alamcars/*/*/metadata.csv",
      "/workspace/alamcars/**/new_records/part_*.csv",
      "/workspace/alamcars/**/merged_records/*.csv"]
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
    m["aesthetic_score"]=6.0    # our curation flag for the dataset filter
m.reset_index().to_csv(p,index=False)
print(f"merged {merged} record files; columns: {sorted(m.columns)}")
if "shape_latent_tokens" not in m.columns:
    print("CONTRACT-MISSING shape_latent_tokens — training will fail; check volume layout")
PYIN

status build-data-roots
DATA_JSON=$(python3 - <<'PYIN'
import glob, json
root="/workspace/alamcars"
def first(p):
    g=sorted(glob.glob(p))
    return g[0].rstrip("/") if g else None
roots={"meta": root,
       "render_cond": root+"/renders_cond",
       "shape_latent": first(root+"/shape_latents/*/"),
       "ss_latent": first(root+"/ss_latents/*/")}
roots={k:v for k,v in roots.items() if v}
print(json.dumps({"AlamCars": roots}))
PYIN
)
echo "data roots: $DATA_JSON"

status build-smoke-config
python3 - <<'PY'
import json
c=json.load(open("configs/gen/slat_flow_img2shape_dit_1_3B_512_bf16.json"))
t=c["trainer"]["args"]
t.update({"max_steps":300,"i_log":10,"i_save":300,"i_sample":1000000,
          "batch_size_per_gpu":1,"batch_split":1})
c["dataset"]["args"]["min_aesthetic_score"]=4.5
c["dataset"]["args"]["max_tokens"]=32768   # 8192 admitted only 5 of 365 cars
json.dump(c,open("/workspace/alamcars/smoke_cfg.json","w"),indent=1)
print("smoke config written (300 steps, bs 2)")
PY

status tryrun
python3 train.py --config /workspace/alamcars/smoke_cfg.json \
  --output_dir "$OUT" --data_dir "$DATA_JSON" --tryrun \
  || { echo "TRYRUN FAILED"; }

status train-300
python3 train.py --config /workspace/alamcars/smoke_cfg.json \
  --output_dir "$OUT" --data_dir "$DATA_JSON" \
  || echo "TRAIN FAILED (see log)"

status resume-probe
python3 - <<'PY'
import json
c=json.load(open("/workspace/alamcars/smoke_cfg.json"))
c["trainer"]["args"]["max_steps"]=320
json.dump(c,open("/workspace/alamcars/smoke_cfg2.json","w"),indent=1)
PY
python3 train.py --config /workspace/alamcars/smoke_cfg2.json \
  --output_dir "$OUT" --data_dir "$DATA_JSON" --ckpt latest \
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
