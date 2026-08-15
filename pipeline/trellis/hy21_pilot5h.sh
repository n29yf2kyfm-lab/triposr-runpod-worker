#!/usr/bin/env bash
# Hunyuan3D-2.1 5-HOUR FINE-TUNE EXPERIMENT on our own cars (owner directive
# 2026-08-15: "Put all glb in pod and train for 5 hrs let's see as experiment").
#
# Inherits every paid-for fix from hy21_smoke.sh (which PASSED, 10.28GB ckpt).
# Differences from the smoke:
#  * preprocesses OUR staged GLBs with our hy21_render.py + their
#    watertight_and_sample.py, under a hard time budget
#  * trains from tencent/Hunyuan3D-2.1 released weights via THEIR finetuning
#    config (lr 1e-5, from_pretrained for VAE + DiT)
#  * wall-clock capped: total pod life ~5h, train gets what prep leaves
#  * checkpoint goes to a PRIVATE HF repo (10GB does not fit the bucket cap);
#    loss curve + log go to the bucket
set -x
export DEBIAN_FRONTEND=noninteractive
START=$(date +%s)
BUDGET=${BUDGET:-9000}       # absolute wall safety (2.5h)
TRAIN_CAP=${TRAIN_CAP:-3600}  # owner 2026-08-15: "Do 1 hr just to test"
RESERVE=900                  # keep 15 min for ckpt upload + verify
LOG=/workspace/boot.log
mkdir -p /workspace
exec > >(tee -a "$LOG") 2>&1

SB="https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object"
PRE="car-meshes/hy21_train/pilot5h"

report() { ( set +x
  curl -s -X POST -H "apikey: ${SB_KEY}" -H "Authorization: Bearer ${SB_KEY}" \
       -H "x-upsert: true" -H "Content-Type: text/plain" \
       --data-binary @"$LOG" "$SB/$PRE/$1" >/dev/null 2>&1 ) || true; }
sb_file() { ( set +x
  curl -s -X POST -H "apikey: ${SB_KEY}" -H "Authorization: Bearer ${SB_KEY}" \
       -H "x-upsert: true" -H "Content-Type: application/octet-stream" \
       --data-binary @"$2" "$SB/$PRE/$1" >/dev/null 2>&1 ) || true; }
sb_txt() { ( set +x
  curl -s -X POST -H "apikey: ${SB_KEY}" -H "Authorization: Bearer ${SB_KEY}" \
       -H "x-upsert: true" -H "Content-Type: text/plain" \
       --data-binary "$2" "$SB/$PRE/$1" >/dev/null 2>&1 ) || true; }
stage() { echo "=== STAGE:$1 ==="; report "log.txt"; }
die()   { echo "=== FAIL:$1 ==="; report "log.txt";
          echo "$1" > /workspace/FAILED; sleep infinity; }

stage boot
nvidia-smi || die NO_GPU
python3 -c "import torch;print('torch',torch.__version__,'cuda',torch.cuda.is_available(),torch.cuda.get_device_name(0))" || die TORCH_BROKEN
df -h /workspace

stage clone
cd /workspace
git clone --depth 1 https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1 repo || die CLONE
cd /workspace/repo/hy3dshape

stage deps
apt-get update -qq && apt-get install -y -qq --no-install-recommends \
  libopengl0 libegl1 libgl1 xvfb xauth libxi6 libxrender1 libxkbcommon0 \
  libxkbcommon-x11-0 libxrandr2 libxinerama1 libxcursor1 libsm6 \
  libice6 libxfixes3 libxxf86vm1 2>&1 | tail -2
grep -viE '^(torch|torchvision)$' requirements.txt > /tmp/reqs_notorch.txt
pip install -q -r /tmp/reqs_notorch.txt 2>&1 | tail -5
pip install -q pytorch_lightning deepspeed tensorboard timm pythreejs ipywidgets torchdiffeq wandb peft 2>&1 | tail -5
pip install -q matplotlib scipy pandas scikit-image scikit-learn libigl huggingface_hub 2>&1 | tail -3
pip install -q torch-cluster -f https://data.pyg.org/whl/torch-2.4.0+cu124.html 2>&1 | tail -3
pip install -q "transformers==4.46.3" 2>&1 | tail -3
python3 -c "import transformers, torch; from transformers import AutoModel; print('transformers', transformers.__version__, 'torch-visible', torch.__version__)" || die TRANSFORMERS_TORCHLESS
python3 -c "import torch;assert torch.cuda.is_available();print('torch survived deps:',torch.__version__)" || die TORCH_KILLED_BY_DEPS
python3 -c "import igl; print('igl ok')" || die IGL

stage blender
cd /workspace
curl -fsSL -o blender.tar.xz https://download.blender.org/release/Blender4.0/blender-4.0.2-linux-x64.tar.xz || die BLENDER_DL
tar xf blender.tar.xz && rm blender.tar.xz
BL=/workspace/blender-4.0.2-linux-x64/blender
$BL --version | head -1 || die BLENDER_RUN

stage fetch_ours
cd /workspace
curl -fsSL "$SB/public/$PRE/hy21_render.py" -o hy21_render.py || die FETCH_RENDER
curl -fsSL "$SB/public/$PRE/cars.txt" -o cars.txt || die FETCH_LIST
curl -fsSL "$SB/public/$PRE/golf.png" -o golf.png || die FETCH_GOLF
wc -l cars.txt

stage preflight_imports
cd /workspace/repo/hy3dshape
python3 - <<'PY' || die IMPORTS
import sys, traceback
sys.path.insert(0, '.')
mods = ["pytorch_lightning", "deepspeed", "omegaconf", "einops", "trimesh",
        "diffusers", "transformers", "hy3dshape",
        "hy3dshape.models.diffusion.flow_matching_sit",
        "hy3dshape.models.autoencoders",
        "hy3dshape.models.conditioner", "timm",
        "hy3dshape.models.denoisers.hunyuandit",
        "hy3dshape.data.dit_asl",
        "hy3dshape.utils.trainings.mesh_log_callback",
        "torchdiffeq", "torch_cluster", "pythreejs", "wandb", "peft"]
bad = []
for m in mods:
    try:
        __import__(m); print("ok", m)
    except Exception:
        bad.append(m); traceback.print_exc()
if bad:
    print("MISSING:", bad); sys.exit(1)
PY

stage patch_main
sed -i "s/ddp_strategy = None/ddp_strategy = 'auto'/" main.py
grep -n "ddp_strategy = 'auto'" main.py || die PATCH_MAIN
sed -i "s/def training_step(self, batch, batch_idx, optimizer_idx=0)/def training_step(self, batch, batch_idx)/" hy3dshape/models/diffusion/flow_matching_sit.py
sed -i "s/def validation_step(self, batch, batch_idx, optimizer_idx=0)/def validation_step(self, batch, batch_idx)/" hy3dshape/models/diffusion/flow_matching_sit.py
grep -c "optimizer_idx" hy3dshape/models/diffusion/flow_matching_sit.py | grep -q "^0$" || die PATCH_STEPS

stage patch_tools
# pip's current libigl drifted from the API their tool was written against.
# FOUR drifts, each found by running the tool (first on the pod's sanity car,
# then locally to exit 0 on a real mesh.ply, 2026-08-15):
#   1. signed_distance returns 4 values, tool unpacks 3 -> starred unpacks
#   2. marching_cubes also grew extra returns -> starred unpack
#   3. return_normals kwarg dropped; float64/int64 dtypes now strict
#   4. write_obj renamed writeOBJ
python3 - <<'PY' || die PATCH_TOOLS
import ast, re
p = "/workspace/repo/hy3dshape/tools/watertight/watertight_and_sample.py"
s = open(p).read()
s = re.sub(r"^(\s*)([\w]+), (I, C|_, _) = igl\.signed_distance\(",
           r"\1\2, \3, *_extra = igl.signed_distance(", s, flags=re.M)
n = len(re.findall(r"\*_extra = igl\.signed_distance\(", s))
assert n == 7, f"expected 7 patched unpacks, got {n}"
s = s.replace("mc_verts, mc_faces = igl.marching_cubes(",
              "mc_verts, mc_faces, *_extra = igl.marching_cubes(")
s = re.sub(r"\s*return_normals=False,\n", "\n", s)
s = s.replace("return_normals=False)", ")").replace(",\n            )", ")")
s = s.replace(".astype(np.float32)", ".astype(np.float64)")
s = s.replace("mesh.vertices, mesh.faces",
              "np.asarray(mesh.vertices, np.float64), np.asarray(mesh.faces, np.int64)")
s = s.replace("igl.write_obj(", "igl.writeOBJ(")
assert "return_normals" not in s
# 5. CHUNK the SDF queries: the single-call version feeds the whole grid to
#    libigl and dies with a C++ bad_alloc cascade ("terminate called
#    recursively") on larger meshes — killed ~half the cars on two pods,
#    host-RAM dependent. Chunked version proven locally, outputs
#    statistically identical (2026-08-15).
helper = (
    "\ndef _sd_chunked(P, V, F, chunk=1_000_000, **kw):\n"
    "    outs = []\n"
    "    for i in range(0, len(P), chunk):\n"
    "        outs.append(igl.signed_distance(P[i:i + chunk], V, F, **kw))\n"
    "    return tuple(np.concatenate([o[j] for o in outs])\n"
    "                 for j in range(len(outs[0])))\n\n"
)
anchor = "def random_sample_pointcloud"
s = s.replace(anchor, helper + anchor, 1)
s = s.replace("*_extra = igl.signed_distance(", "*_extra = _sd_chunked(")
ast.parse(s)
open(p, "w").write(s)
print("patched: 7 signed_distance (chunked) + marching_cubes + kwargs/dtypes"
      " + writeOBJ")
PY

prep_one() {  # prep_one <uid>  -> 0 on success; rc/wt logs left in /tmp
  local U=$1 G=/workspace/car.glb OUTD="$DATA/$1"
  rm -f "$G"
  curl -fsSL "$SB/public/$PRE/glb/${U}.glb" -o "$G" || { echo "dlfail" > /tmp/rc.log; return 1; }
  # Cycles in -b needs no display: run blender DIRECTLY. v1 wrapped this in
  # xvfb-run and every car died unseen (the image ships no xauth, so xvfb-run
  # itself fails before blender starts). xauth is installed now anyway.
  $BL -b --factory-startup -noaudio -P /workspace/hy21_render.py -- \
       --object "$G" --output_folder "$OUTD/render_cond" --views 24 \
       --resolution 512 --samples 12 > /tmp/rc.log 2>&1 \
   && python3 /workspace/repo/hy3dshape/tools/watertight/watertight_and_sample.py \
       --input_obj "$OUTD/render_cond/mesh.ply" \
       --output_prefix "$OUTD/geo_data/$U" > /tmp/wt.log 2>&1 \
   && [ -f "$OUTD/geo_data/${U}_surface.npz" ] \
   && [ -f "$OUTD/render_cond/023.png" ]
}

stage prep_sanity
# ONE car, decisive, BEFORE the loop: if the environment is broken, name the
# cause in the bucket and die for pennies — v1 burned 45 cars with the real
# error trapped in an unuploaded /tmp file.
DATA=/workspace/prep
mkdir -p "$DATA"
FIRST=$(head -1 /workspace/cars.txt)
if ! prep_one "$FIRST"; then
  sb_file rc_fail.log /tmp/rc.log
  [ -f /tmp/wt.log ] && sb_file wt_fail.log /tmp/wt.log
  tail -n 20 /tmp/rc.log; tail -n 20 /tmp/wt.log 2>/dev/null
  die PREP_BROKEN
fi
echo "CAROK $FIRST (sanity)"

stage prep_cars
# time-budgeted: render 24 geo views + surface sampling per car; a car that
# fails is logged and skipped, never fatal. Stop when the prep window closes.
PREP_DEADLINE=$((START + 2400))
N_OK=1; N_FAIL=0
while read -r UID_; do
  [ -z "$UID_" ] && continue
  [ "$UID_" = "$FIRST" ] && continue
  NOW=$(date +%s)
  if [ "$NOW" -ge "$PREP_DEADLINE" ]; then echo "PREP_WINDOW_CLOSED"; break; fi
  if prep_one "$UID_"; then
    N_OK=$((N_OK+1)); echo "CAROK $UID_ ($N_OK)"
  else
    N_FAIL=$((N_FAIL+1)); echo "CARFAIL $UID_"
    tail -n 4 /tmp/rc.log; tail -n 4 /tmp/wt.log 2>/dev/null
    rm -rf "$DATA/$UID_"
  fi
  if [ $((N_OK % 5)) -eq 0 ]; then report "log.txt"; fi
done < /workspace/cars.txt
echo "PREP_DONE ok=$N_OK fail=$N_FAIL"
report "log.txt"
[ "$N_OK" -ge 8 ] || die PREP_TOO_FEW

stage patch_config
cd /workspace/repo/hy3dshape
CFG=configs/hunyuandit-finetuning-flowmatching-dinol518-bf16-lr1e5-4096.yaml
python3 - "$CFG" <<'PY' || die PATCH_CFG
import sys, re
p = sys.argv[1]; s = open(p).read()
s = s.replace("tools/mini_trainset/preprocessed", "/workspace/prep")
s = re.sub(r"steps:\s*[\d_]+",            "steps: 1000000", s, count=1)
# LR: the 2026-08-15 run at the shipped 1e-5 destroyed the model in
# 1900 steps on 20 cars (loss 1.85->1.05, output a melted blob). A
# small dataset needs a small step; 2e-6 is 5x gentler.
s = re.sub(r"base_lr:\s*\S+", "base_lr: 2e-6", s, count=1)
s = re.sub(r"every_n_train_steps:\s*\d+", "every_n_train_steps: 200", s, count=1)
s = re.sub(r"val_check_interval:\s*\d+",  "val_check_interval: 200", s, count=1)
s = re.sub(r"limit_val_batches:\s*\d+",   "limit_val_batches: 1", s, count=1)
s = re.sub(r"batch_size:\s*\d+",          "batch_size: 2", s, count=1)
s = re.sub(r"num_workers:\s*\d+",         "num_workers: 4", s, count=1)
s = re.sub(r"val_num_workers:\s*\d+",     "val_num_workers: 1", s, count=1)
s = s.split("\ncallbacks:")[0]
open(p, "w").write(s)
print(s[:800])
PY

stage train
export WANDB_MODE=disabled
export HF_HUB_OFFLINE=0
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
OUT=/workspace/out_pilot
mkdir -p "$OUT"
NOW=$(date +%s)
TRAIN_SECS=$((START + BUDGET - NOW - RESERVE))
if [ "$TRAIN_SECS" -gt "$TRAIN_CAP" ]; then TRAIN_SECS=$TRAIN_CAP; fi
[ "$TRAIN_SECS" -ge 900 ] || die NO_TIME_LEFT_FOR_TRAINING
echo "TRAIN_SECS=$TRAIN_SECS"
timeout "$TRAIN_SECS" python3 main.py \
  --num_nodes 1 --num_gpus 1 \
  --config "$CFG" \
  --output_dir "$OUT" \
  --use_amp --amp_type bf16 2>&1 | tail -400
echo "TRAIN_EXIT=${PIPESTATUS[0]}"
report "log.txt"

stage verify
find "$OUT" -maxdepth 3 -type f | head -40
CKPT=$(find "$OUT" -name "*.ckpt" 2>/dev/null | sort | tail -1)
[ -n "$CKPT" ] || die NO_CKPT
echo "CKPT_FOUND=$CKPT"; du -sh "$CKPT"

stage losscurve
python3 - "$OUT" <<'PY' || echo "losscurve failed (non-fatal)"
import sys, glob, csv
from tensorboard.backend.event_processing.event_accumulator import EventAccumulator
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
evs = sorted(glob.glob(sys.argv[1] + "/**/events.out.tfevents.*", recursive=True))
assert evs, "no tensorboard events"
ea = EventAccumulator(evs[-1]); ea.Reload()
tags = ea.Tags()["scalars"]
print("scalar tags:", tags)
tag = next((t for t in tags if "loss" in t.lower()), tags[0])
pts = ea.Scalars(tag)
xs = [p.step for p in pts]; ys = [p.value for p in pts]
with open("/workspace/loss.csv", "w") as f:
    w = csv.writer(f); w.writerow(["step", tag]); w.writerows(zip(xs, ys))
plt.figure(figsize=(8, 4.5)); plt.plot(xs, ys)
plt.xlabel("step"); plt.ylabel(tag); plt.title("Alam-3D v2 pilot 5h — " + tag)
plt.grid(alpha=0.3); plt.tight_layout(); plt.savefig("/workspace/loss.png", dpi=110)
print("loss points:", len(xs), "first", ys[:3], "last", ys[-3:])
PY
[ -f /workspace/loss.png ] && sb_file loss.png /workspace/loss.png
[ -f /workspace/loss.csv ] && sb_file loss.csv /workspace/loss.csv

stage ab_eval
# THE EXPERIMENT'S ACTUAL QUESTION (owner: "try with golf see if any changes"):
# same Golf capture through BASE 2.1 weights and the fresh checkpoint, same
# seed, both GLBs to the bucket. Runs in the SAME pod so the checkpoint never
# needs to survive a transfer (HF_TOKEN is read-only — measured).
cd /workspace/repo/hy3dshape
CKPTS=$(find "$OUT" -name "*.ckpt" | sort | tr '\n' ',')
echo "CKPT_SWEEP=$CKPTS"
python3 - "$CFG" "$CKPTS" <<'PY' || die AB_EVAL
import gc, sys, yaml, torch
from PIL import Image
sys.path.insert(0, '.')
from hy3dshape.pipelines import Hunyuan3DDiTFlowMatchingPipeline
from hy3dshape.utils import instantiate_from_config

img = Image.open('/workspace/golf.png').convert('RGBA')
pipe = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained('tencent/Hunyuan3D-2.1')
base_model = pipe.model
mesh = pipe(image=img, generator=torch.Generator().manual_seed(42))[0]
mesh.export('/workspace/golf_base.glb')
print('BASE_DONE', len(mesh.faces), flush=True)

# Sweep EVERY saved checkpoint. The previous run rendered only the LAST one,
# so "the fine-tune failed" could not be separated from "it passed through a
# good state and then collapsed". The trajectory answers that, and a mid-run
# checkpoint that beats base is the whole prize.
cfg = yaml.safe_load(open(sys.argv[1]))
for ck in [c for c in sys.argv[2].split(',') if c.strip()]:
    tag = ck.rstrip('/').split('=')[-1].split('.')[0]
    try:
        model = instantiate_from_config(cfg['model']['params']['denoiser_cfg'])
        sd = torch.load(ck, map_location='cpu')
        sd = sd.get('state_dict', sd)
        best, best_n = None, -1
        for pref in ('model.', '_forward_module.model.', ''):
            cand = {k[len(pref):]: v for k, v in sd.items() if k.startswith(pref)}
            hit = len(set(cand) & set(model.state_dict()))
            if hit > best_n:
                best, best_n = cand, hit
        assert best_n > 100, f'{tag}: checkpoint keys do not match denoiser'
        msg = model.load_state_dict(best, strict=False)
        assert len(msg.missing_keys) == 0, msg.missing_keys[:5]
        pipe.model = model.cuda().half()
        del sd, best
        gc.collect(); torch.cuda.empty_cache()
        mesh = pipe(image=img, generator=torch.Generator().manual_seed(42))[0]
        out = f'/workspace/golf_step{tag}.glb'
        mesh.export(out)
        print(f'STEP_DONE {tag} faces={len(mesh.faces)} -> {out}', flush=True)
    except Exception as e:
        print(f'STEP_FAIL {tag}: {type(e).__name__}: {e}', flush=True)
    finally:
        pipe.model = base_model
        gc.collect(); torch.cuda.empty_cache()
PY
for f in /workspace/golf_step*.glb; do
  [ -e "$f" ] && sb_file "$(basename $f)" "$f"
done
sb_file golf_base.glb /workspace/golf_base.glb
sb_file golf_tuned.glb /workspace/golf_tuned.glb
ls -la /workspace/golf_*.glb

echo "=== PILOT_OK ==="
report "log.txt"
sb_txt DONE "PILOT_OK"
sleep infinity
