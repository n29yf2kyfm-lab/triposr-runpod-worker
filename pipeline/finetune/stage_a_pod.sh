#!/bin/bash
# stage_a_pod.sh — Alam-3D Stage A: run the TRELLIS.2 data_toolkit over the
# AlamCars subset on a RunPod GPU pod. Fetched from the public bucket by the
# pod's start command; NO secrets in this file (HF token arrives via pod env).
# Progress: $ROOT/logs served on :8000 (status.json + stage_a.log).
ROOT=/workspace/alamcars
mkdir -p "$ROOT/logs"
( cd "$ROOT/logs" && python3 -m http.server 8000 >/dev/null 2>&1 & )
exec > >(tee -a "$ROOT/logs/stage_a.log") 2>&1
status(){ printf '{"step":"%s","at":"%s"}\n' "$1" "$(date -u +%FT%TZ)" > "$ROOT/logs/status.json"; echo "===== $1 ====="; }
status boot
nvidia-smi -L || true
cd /app/TRELLIS.2 || { status FATAL-no-trellis2; sleep infinity; }
export PYTHONPATH=/app/TRELLIS.2:$PYTHONPATH   # subset modules import as datasets.<NAME>; scripts run with data_toolkit/ as sys.path[0]
[ -n "$HF_TOKEN" ] && echo "HF token: present" || echo "HF token: MISSING"
status deps
bash data_toolkit/setup.sh || echo "setup.sh failed (continuing)"
status fetch-inputs
PUB=https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object/public/car-renders
curl -sSL "$PUB/finetune/prepare_dataset.py?cb=$(date +%s)" -o /tmp/prepare_dataset.py
curl -sSL "$PUB/catalogue.v2.json?cb=$(date +%s)" -o /tmp/catalogue.v2.json
status prepare-dataset
python3 /tmp/prepare_dataset.py --root "$ROOT" --catalogue /tmp/catalogue.v2.json
mkdir -p datasets && cp "$ROOT/AlamCars.py" datasets/AlamCars.py && touch datasets/__init__.py
run(){ s="$1"; shift; status "$s"; "$@" || echo "STEP-FAILED $s (continuing so later logs exist)"; \
       python3 data_toolkit/build_metadata.py AlamCars --root "$ROOT" >/dev/null 2>&1 || true; }
run dump_mesh    python3 data_toolkit/dump_mesh.py    AlamCars --root "$ROOT"
run dump_pbr     python3 data_toolkit/dump_pbr.py     AlamCars --root "$ROOT"
run dual_grid    python3 data_toolkit/dual_grid.py    AlamCars --root "$ROOT" --resolution 256,512,1024
run voxelize_pbr python3 data_toolkit/voxelize_pbr.py AlamCars --root "$ROOT"
run render_cond  python3 data_toolkit/render_cond.py  AlamCars --root "$ROOT" --num_views 16
run enc_shape    python3 data_toolkit/encode_shape_latent.py --root "$ROOT" --resolution 1024
run enc_pbr      python3 data_toolkit/encode_pbr_latent.py   --root "$ROOT"
LNAME=$(ls "$ROOT/shape_latents" 2>/dev/null | head -1)
if [ -n "$LNAME" ]; then run enc_ss python3 data_toolkit/encode_ss_latent.py --root "$ROOT" --shape_latent_name "$LNAME"
else echo "SKIP enc_ss: no shape_latents produced"; fi
status DONE
df -h /workspace; du -sh "$ROOT"/* 2>/dev/null
sleep infinity
