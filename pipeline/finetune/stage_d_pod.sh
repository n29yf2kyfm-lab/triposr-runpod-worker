#!/bin/bash
# stage_d_pod.sh — Alam-3D Stage D: fine-tune the 1024 SHAPE REFINER.
#
# Why this stage exists: after Stage C the coarse shape is good, but every
# remaining defect the owner can see — soft bumper/grille creases, mushy LED
# internals, flat rear-lens graphics, undefined shut lines, inconsistent trim —
# is high-frequency detail owned by the 1024 stage, which is still Microsoft's
# untouched model. Training it on cars is the only lever that reaches them.
#
# Architecturally this is Stage C at a finer grid: the released
# slat_flow_img2shape_dit_1_3B_1024_bf16 is the same 1.3B SLatFlowModel with
# resolution 64 instead of 32. Upstream ships no training config for it, so we
# author one from the 512 config and let --tryrun prove the data contract
# before spending real GPU hours.
ROOT=/workspace/alamcars
OUT=/workspace/alam3d_stage_d
mkdir -p "$OUT/logs"
( cd "$OUT/logs" && python3 -m http.server 8000 >/dev/null 2>&1 & )
RUN_LOG="stage_d_$(hostname)_$(date -u +%Y%m%dT%H%M%SZ).log"
ln -sf "$RUN_LOG" "$OUT/logs/stage_b.log"
exec > >(tee -a "$OUT/logs/$RUN_LOG") 2>&1
status(){ printf '{"step":"%s","at":"%s"}\n' "$1" "$(date -u +%FT%TZ)" > "$OUT/logs/status.json"; echo "===== $1 ====="; }

status boot
[ -f /etc/rp_environment ] && source /etc/rp_environment
export HF_TOKEN HUGGING_FACE_HUB_TOKEN
[ -n "$HF_TOKEN" ] && echo "HF token: present (${#HF_TOKEN} chars)" || echo "HF token: MISSING"
nvidia-smi -L || true
cd /app/TRELLIS.2 || { status FATAL-no-trellis2; sleep infinity; }
export PYTHONPATH=/app/TRELLIS.2:$PYTHONPATH
pip install -q tensorboard pandas easydict || true
pip install -q "transformers==4.57.6" || true

status inspect-latents
# Which latent sets exist, and at what grid? Stage D needs the 64^3 (1024)
# latents; Stage C used 32^3. Print the truth rather than assuming it.
python3 - <<'PY'
import glob, os
import numpy as np
root="/workspace/alamcars"
for d in sorted(glob.glob(f"{root}/shape_latents/*/")):
    fs=sorted(glob.glob(d+"*.npz"))[:1] or sorted(glob.glob(d+"*.pt"))[:1]
    n=len(glob.glob(d+"*.npz"))+len(glob.glob(d+"*.pt"))
    info=""
    if fs and fs[0].endswith(".npz"):
        try:
            z=np.load(fs[0])
            info=" ".join(f"{k}{tuple(z[k].shape)}" for k in list(z.keys())[:4])
        except Exception as e:
            info=f"read fail {str(e)[:40]}"
    print(f"  {os.path.basename(d.rstrip('/')):40s} files={n:5d}  {info}")
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
export ALAM3D_INIT_FROM="microsoft/TRELLIS.2-4B/ckpts/slat_flow_img2shape_dit_1_3B_1024_bf16"

status build-data-roots
DATA_JSON=$(python3 - <<'PYIN'
import glob, json
root="/workspace/alamcars"
def pick(pattern, prefer):
    g=sorted(glob.glob(pattern))
    if not g: return None
    for p in g:
        if prefer in p: return p.rstrip("/")
    return g[-1].rstrip("/")
roots={"meta": root, "render_cond": root+"/renders_cond",
       # the 1024 stage trains on the finer latent set when one exists
       "shape_latent": pick(root+"/shape_latents/*/", "1024"),
       "ss_latent": pick(root+"/ss_latents/*/", "")}
print(json.dumps({"AlamCars": {k:v for k,v in roots.items() if v}}))
PYIN
)
echo "data roots: $DATA_JSON"

status build-config
python3 - <<'PY'
import json
c=json.load(open("configs/gen/slat_flow_img2shape_dit_1_3B_512_bf16.json"))
# released 1024 refiner = same 1.3B SLatFlowModel at a 64^3 grid
c["models"]["denoiser"]["args"]["resolution"] = 64
t=c["trainer"]["args"]
t.update({"max_steps":4000,"i_log":10,"i_save":1000,"i_sample":10**9,
          "batch_size_per_gpu":1,"batch_split":1,"learning_rate":8e-6})
c["dataset"]["args"]["min_aesthetic_score"]=0.0
c["dataset"]["args"]["max_tokens"]=32768
json.dump(c,open("/workspace/alamcars/stage_d_cfg.json","w"),indent=1)
print("stage D config: 4000 steps, lr 8e-6, denoiser resolution 64")
PY

status tryrun
python3 train.py --config /workspace/alamcars/stage_d_cfg.json \
  --output_dir "$OUT" --data_dir "$DATA_JSON" --tryrun \
  || { echo "TRYRUN FAILED — the 1024 stage likely needs extra conditioning; see log"; status FATAL-tryrun; sleep infinity; }

status train-4000
python3 train.py --config /workspace/alamcars/stage_d_cfg.json \
  --output_dir "$OUT" --data_dir "$DATA_JSON" \
  || { echo "TRAIN FAILED (see log)"; status FATAL-train; sleep infinity; }

status export-loss
python3 - <<'PY'
import glob
try:
    from tensorboard.backend.event_processing.event_accumulator import EventAccumulator
    for ev in sorted(glob.glob("/workspace/alam3d_stage_d/**/events.out.tfevents.*", recursive=True)):
        ea=EventAccumulator(ev); ea.Reload()
        for tag in ea.Tags().get("scalars", []):
            if "loss" in tag.lower():
                pts=ea.Scalars(tag)
                if not pts: continue
                s=pts[::max(1,len(pts)//30)]
                print(f"STAGE_D_LOSS {tag} ({len(pts)} pts): "+", ".join(f"{p.step}:{p.value:.4f}" for p in s))
except Exception as e:
    print("loss export failed:", e)
PY

status DONE
ls -la "$OUT/ckpts" 2>/dev/null | tail -6
sleep infinity
