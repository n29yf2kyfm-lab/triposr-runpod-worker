#!/usr/bin/env bash
# Hunyuan3D-2.1 TRAINER SMOKE TEST — proves the fine-tune loop runs end to end
# on Tencent's own 8-case mini-trainset before a penny goes to our data.
#
# Design follows the deployment lessons already paid for (CLAUDE.md):
#  * NEVER exits -> a pod whose dockerStartCmd exits gets RESTARTED in a loop
#  * uploads its log at EVERY stage via a SERVICE KEY (signed URLs are one-time)
#  * asserts on ARTEFACTS: no checkpoint file => FAIL_NO_CKPT, so a silent
#    no-output run can never read as success
#  * does NOT reinstall torch (Hunyuan's requirements.txt breaks the image's)
#  * installs pytorch_lightning + deepspeed EXPLICITLY: main.py imports them and
#    they are absent/commented in requirements.txt
set -x
export DEBIAN_FRONTEND=noninteractive
LOG=/workspace/boot.log
mkdir -p /workspace
exec > >(tee -a "$LOG") 2>&1

SB="https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object"
PRE="car-meshes/hy21_train/smoke"

report() {
  # subshell with xtrace OFF: set -x tracing a curl with auth headers wrote the
  # service key into a PUBLIC bucket object on the first run. Never again.
  ( set +x
    curl -s -X POST -H "apikey: ${SB_KEY}" -H "Authorization: Bearer ${SB_KEY}" \
         -H "x-upsert: true" -H "Content-Type: text/plain" \
         --data-binary @"$LOG" "$SB/$PRE/$1" >/dev/null 2>&1 ) || true
}
sb_put() {  # sb_put <remote-name> <local-file-or-inline-string-flag>
  ( set +x
    curl -s -X POST -H "apikey: ${SB_KEY}" -H "Authorization: Bearer ${SB_KEY}" \
         -H "x-upsert: true" -H "Content-Type: text/plain" \
         --data-binary "$2" "$SB/$PRE/$1" >/dev/null 2>&1 ) || true
}
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
# pymeshlab (pulled in via mesh_log_callback) needs libOpenGL.so.0 — the
# DOCUMENTED trap from the hybrid deploy ("pymeshlab's postprocess needs
# libopengl0 or FloaterRemover dies"). Attempt 3 died on exactly this.
apt-get update -qq && apt-get install -y -qq --no-install-recommends libopengl0 libegl1 libgl1 2>&1 | tail -2
# torch is NOT reinstalled: the image's build is what the model is tested on and
# Hunyuan's requirements.txt has broken it before.
grep -viE '^(torch|torchvision)$' requirements.txt > /tmp/reqs_notorch.txt
pip install -q -r /tmp/reqs_notorch.txt 2>&1 | tail -5
# undocumented but REQUIRED by main.py
# The FULL static import scan of the package (run locally, 2026-08-14) — not
# pod-by-pod discovery. Hard requirements the repo never declares:
#   pythreejs+ipywidgets (mesh_log_callback chain), torchdiffeq (ODE sampler),
#   wandb (top-level in trainings/callback.py), timm (moe_layers),
#   peft (built-in LoRA — the pilot will use this).
pip install -q pytorch_lightning deepspeed tensorboard timm pythreejs ipywidgets torchdiffeq wandb peft 2>&1 | tail -5
# Everything the scan found that I ASSUMED the image ships. It does not ship
# matplotlib (attempt 4 died on it) — so stop assuming, install the lot.
pip install -q matplotlib scipy pandas scikit-image scikit-learn 2>&1 | tail -3
# torch_cluster: FUNCTION-LEVEL import inside the VAE's fps sampling — invisible
# to import preflights, hits on the first training forward pass. Prebuilt wheel
# only (a source build costs 30+ min — the flash-attn lesson).
pip install -q torch-cluster -f https://data.pyg.org/whl/torch-2.4.0+cu124.html 2>&1 | tail -3
# latest transformers dropped torch 2.4: "[transformers] Disabling PyTorch
# because PyTorch >= 2.5 is required". Pin to the last broadly-2.x line;
# DINOv2 support has been in transformers since 4.31 so nothing is lost.
pip install -q "transformers==4.46.3" 2>&1 | tail -3
# `import transformers` SUCCEEDS even when it has disabled torch (tokenizer-only
# mode) — that is how the first preflight passed a broken install. AutoModel is
# the access that actually raises, so it is the check, and it must be fatal.
python3 -c "import transformers, torch; from transformers import AutoModel; print('transformers', transformers.__version__, 'torch-visible', torch.__version__)" || die TRANSFORMERS_TORCHLESS
python3 -c "import torch;assert torch.cuda.is_available();print('torch survived deps:',torch.__version__)" || die TORCH_KILLED_BY_DEPS

stage preflight_imports
# replicate any sys.path the real entrypoint uses; a preflight that does not is
# worth exactly as much as no preflight (P3-SAM lesson).
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
    except Exception as e:
        bad.append(m); traceback.print_exc()
if bad:
    print("MISSING:", bad); sys.exit(1)
PY

stage patch_main
# Their single-GPU branch sets `ddp_strategy = None  # 'auto'` and newer
# pytorch_lightning REJECTS strategy=None (attempt 5). The fix is literally
# their own comment.
sed -i "s/ddp_strategy = None/ddp_strategy = 'auto'/" main.py
grep -n "ddp_strategy = 'auto'" main.py || die PATCH_MAIN
# Their step signatures are PL 1.x era (`optimizer_idx` arg); PL 2.x refuses to
# run them (attempt 6). The drift is exactly these two lines — verified by a
# full grep, no epoch_end-style APIs anywhere else in the package.
sed -i "s/def training_step(self, batch, batch_idx, optimizer_idx=0)/def training_step(self, batch, batch_idx)/" hy3dshape/models/diffusion/flow_matching_sit.py
sed -i "s/def validation_step(self, batch, batch_idx, optimizer_idx=0)/def validation_step(self, batch, batch_idx)/" hy3dshape/models/diffusion/flow_matching_sit.py
grep -c "optimizer_idx" hy3dshape/models/diffusion/flow_matching_sit.py | grep -q "^0$" || die PATCH_STEPS

stage patch_config
CFG=configs/hunyuandit-mini-overfitting-flowmatching-dinol518-bf16-lr1e4-4096.yaml
python3 - "$CFG" <<'PY' || die PATCH
import sys, re
p = sys.argv[1]; s = open(p).read()
# Cap the run: the shipped config trains for 10^10 steps. We only need to prove
# the loop turns and writes a checkpoint. every_n_train_steps must be >
# val_check_interval (their own comment says so).
s = re.sub(r"steps:\s*[\d_]+",            "steps: 24", s, count=1)
s = re.sub(r"every_n_train_steps:\s*\d+", "every_n_train_steps: 20", s, count=1)
s = re.sub(r"val_check_interval:\s*\d+",  "val_check_interval: 10", s, count=1)
s = re.sub(r"limit_val_batches:\s*\d+",   "limit_val_batches: 1", s, count=1)
s = re.sub(r"batch_size:\s*\d+",          "batch_size: 1", s, count=1)
s = re.sub(r"num_workers:\s*\d+",         "num_workers: 2", s, count=1)
s = re.sub(r"val_num_workers:\s*\d+",     "val_num_workers: 1", s, count=1)
# Drop the custom logger callbacks ENTIRELY: their on_validation_batch_end has
# a PL 1.x signature and crashes the val loop (attempt 7) — and the hook fires
# regardless of step_frequency. main.py guards with `if "callbacks" in config`,
# and ModelCheckpoint (the artefact this smoke test exists to prove) is built
# unconditionally before that guard.
s = s.split("\ncallbacks:")[0]
open(p, "w").write(s)
print(s[:1200])
PY

stage train
export WANDB_MODE=disabled
export HF_HUB_OFFLINE=0
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
OUT=/workspace/out_smoke
mkdir -p "$OUT"
# SINGLE GPU: main.py only builds a DeepSpeed strategy when num_gpus>1, so we
# deliberately do NOT pass --deepspeed here.
timeout 5400 python3 main.py \
  --num_nodes 1 --num_gpus 1 \
  --config "$CFG" \
  --output_dir "$OUT" \
  --use_amp --amp_type bf16 2>&1 | tail -200
echo "TRAIN_EXIT=${PIPESTATUS[0]}"
report "log.txt"

stage verify
# ARTEFACT assertion. RC=0 with an empty output dir is the documented failure
# mode (P3-SAM's demo returned results and saved nothing).
find "$OUT" -maxdepth 3 -type f | head -40
CKPT=$(find "$OUT" -name "*.ckpt" -o -name "*.pt" -o -name "*mp_rank*" 2>/dev/null | head -1)
if [ -z "$CKPT" ]; then
  echo "no checkpoint under $OUT"
  find /workspace -name "*.ckpt" | head -5
  die NO_CKPT
fi
echo "CKPT_FOUND=$CKPT"
du -sh "$CKPT"
find "$OUT" -maxdepth 3 -type f -printf "%s\t%p\n" | sort -rn | head -20 > /workspace/artefacts.txt
sb_put artefacts.txt @/workspace/artefacts.txt

echo "=== SMOKE_OK ==="
report "log.txt"
touch /workspace/SMOKE_OK
sb_put DONE "SMOKE_OK" 

# Keep the container alive so it is never restart-looped; the launcher
# terminates it explicitly.
sleep infinity
