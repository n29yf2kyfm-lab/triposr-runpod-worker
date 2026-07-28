#!/bin/bash
# stage_a_backfill_pod.sh — close the gap between the shapes the owner KEPT and
# the shapes the trainer SAW.
#
# The cull verdict kept 476 shapes; Stage C v1's trainer reported 296 instances.
# The ~180 missing keeps are worth more than any hyperparameter: they are the
# only new signal available without sourcing new data. But "re-run Stage A" is
# not the first step — DIAGNOSIS is. A keep can be absent from training for
# reasons re-running fixes (a failed dump/render/encode) and for reasons it
# never will (token count over the trainer's max_tokens cap). Spending GPU hours
# on shapes in the second bucket is paying to change nothing, so this pod:
#
#   1. merges the per-directory metadata flags into the root csv (the same
#      never-merged-flags disease that hid 821 PBR dumps from voxelize_pbr),
#   2. joins the cull verdict against the real files on the volume and writes a
#      per-shape WHY for every untrained keep, uploaded before any work starts,
#   3. re-runs the Stage A steps — each is incremental by metadata flag, so
#      only missing work runs,
#   4. re-diagnoses, uploads the after-report, and refuses to call itself DONE
#      unless the number of latent-bearing keeps actually went UP.
#
# Runs on the render tier: the original Stage A completed on a 24GB RTX 4090
# (pod r0uucvv8f3wkf3), so no A100 money is needed here.
# Secrets: HF_TOKEN / SB_KEY via pod env only. No secrets in this file.
ROOT=/workspace/alamcars
OUT_LOGS="$ROOT/logs"
mkdir -p "$OUT_LOGS"
( cd "$OUT_LOGS" && python3 -m http.server 8000 >/dev/null 2>&1 & )
RUN_LOG="backfill_$(hostname)_$(date -u +%Y%m%dT%H%M%SZ).log"
ln -sf "$RUN_LOG" "$OUT_LOGS/stage_b.log"   # launcher polls this name
exec > >(tee -a "$OUT_LOGS/$RUN_LOG") 2>&1
status(){ printf '{"step":"%s","at":"%s"}\n' "$1" "$(date -u +%FT%TZ)" > "$OUT_LOGS/status.json"; echo "===== $1 ====="; }

status boot
[ -f /etc/rp_environment ] && source /etc/rp_environment
export HF_TOKEN SB_KEY; export HUGGING_FACE_HUB_TOKEN="${HUGGING_FACE_HUB_TOKEN:-$HF_TOKEN}"
[ -n "$HF_TOKEN" ] && echo "HF token: present (${#HF_TOKEN} chars)" || echo "HF token: MISSING"
[ -n "$SB_KEY" ] && echo "SB key: present" || echo "SB key: MISSING (reports will not upload)"
nvidia-smi -L || true
cd /app/TRELLIS.2 || { status FATAL-no-trellis2; sleep infinity; }
export PYTHONPATH=/app/TRELLIS.2:$PYTHONPATH
pip install -q pandas easydict pillow || true
bash data_toolkit/setup.sh || echo "setup.sh failed (continuing)"
mkdir -p datasets && cp "$ROOT/AlamCars.py" datasets/AlamCars.py && touch datasets/__init__.py

status arch-check
# The arch list is context, NOT the gate — this image lists sm_90 yet died on an
# H100 at the first F.conv2d (cuDNN ships its own kernels). Launch the real op.
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
if built and have not in built:
    print(f"note: {have} absent from the compiled arch list - relying on the "
          f"live kernel test below, not the list")
try:
    x = torch.randn(1, 3, 32, 32, device="cuda")
    w = torch.randn(8, 3, 3, 3, device="cuda")
    y = torch.nn.functional.conv2d(x, w)          # the op the H100 died on
    z = torch.randn(64, 64, device="cuda") @ torch.randn(64, 64, device="cuda")
    torch.cuda.synchronize()
    s = float(y.sum()) + float(z.sum())
except Exception as e:
    print(f"FATAL: kernel smoke test failed on {name} ({have}).")
    print(f"       {type(e).__name__}: {str(e)[:160]}")
    sys.exit(1)
print(f"arch OK: conv2d + matmul ran on {name} ({have})")
PYARCH

status space-check
# The volume that truncated a checkpoint at 236/250GB. Refuse to start
# write-heavy work without headroom.
python3 - <<'PYSPACE' || { status FATAL-no-space; sleep infinity; }
import os, shutil, sys
need_gb = float(os.environ.get("MIN_FREE_GB", "30"))
t, u, f = shutil.disk_usage("/workspace")
gb = 1024 ** 3
print(f"/workspace: {u/gb:.0f}GB used of {t/gb:.0f}GB, {f/gb:.0f}GB free "
      f"(need {need_gb:.0f}GB)")
if f / gb < need_gb:
    print("FATAL: not enough headroom. Reclaim space before running this.")
    sys.exit(1)
PYSPACE

status merge-flags
# Same disease, same cure as texture_unblock_pod.sh: every data_toolkit step
# records its done-flags in per-directory metadata that the root csv (which the
# NEXT step filters on) never sees. Merge before trusting any flag.
python3 - <<'PY'
import glob, pandas as pd
p="/workspace/alamcars/metadata.csv"
m=pd.read_csv(p).set_index("sha256")
merged=0
pats=["/workspace/alamcars/*/metadata.csv","/workspace/alamcars/*/*/metadata.csv",
      "/workspace/alamcars/**/new_records/part_*.csv","/workspace/alamcars/**/merged_records/*.csv"]
seen=set()
for pat in pats:
    for f in glob.glob(pat, recursive=True):
        if f in seen or f==p: continue
        seen.add(f)
        try:
            df=pd.read_csv(f)
            if "sha256" in df.columns:
                m=df.set_index("sha256").combine_first(m); merged+=1
        except Exception as e:
            print("skip",f,str(e)[:60])
if "aesthetic_score" not in m.columns: m["aesthetic_score"]=6.0
m["aesthetic_score"]=pd.to_numeric(m["aesthetic_score"], errors="coerce").fillna(6.0)
m.reset_index().to_csv(p,index=False)
print(f"merged {merged} metadata fragments into root csv ({len(m)} rows)")
PY

status fetch-diag
PUB=https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object/public/car-renders/finetune
curl -sSL "$PUB/gap_diag.py?cb=$(date +%s)" -o /tmp/gap_diag.py
# sha-pinned: the fetched file must be the exact revision this script was
# committed against, or a stale bucket copy silently runs old diagnosis logic
# (council reviewer 1, #5). UPDATE THIS HASH whenever gap_diag.py changes.
GAP_SHA_WANT=8a19e2cc3afc4195c1cbf46b120f72a22f8ebd2ac7fb6e188d5b4f223033c736
GAP_SHA_GOT=$(sha256sum /tmp/gap_diag.py | awk '{print $1}')
[ "$GAP_SHA_GOT" = "$GAP_SHA_WANT" ] \
  || { echo "gap_diag.py sha mismatch: got $GAP_SHA_GOT want $GAP_SHA_WANT — re-upload it"; status FATAL-diag-sha; sleep infinity; }
python3 -c "import ast;ast.parse(open('/tmp/gap_diag.py').read())" \
  || { echo "gap_diag.py failed to parse"; status FATAL-no-diag; sleep infinity; }

status diagnose-before
python3 /tmp/gap_diag.py before || { status FATAL-diagnose; sleep infinity; }

status run-stage-a
# Each step is incremental: it filters on the flags of the step before it and
# skips rows already carrying its own flag, so only missing work runs. The
# metadata rebuild after every step folds the new flags back in for the next.
run(){ s="$1"; shift; status "$s"; "$@" || echo "STEP-FAILED $s (continuing so later steps still run)"; \
       python3 data_toolkit/build_metadata.py AlamCars --root "$ROOT" >/dev/null 2>&1 || true; }
run dump_mesh    python3 data_toolkit/dump_mesh.py    AlamCars --root "$ROOT"
run dump_pbr     python3 data_toolkit/dump_pbr.py     AlamCars --root "$ROOT"
run dual_grid    python3 data_toolkit/dual_grid.py    AlamCars --root "$ROOT" --resolution 256,512,1024
# --resolution is mandatory: upstream declares type=str default=1024 (an int)
# then calls .split(",") on it, so omitting the flag always raises.
run voxelize_pbr python3 data_toolkit/voxelize_pbr.py AlamCars --root "$ROOT" --resolution 512,1024
run render_cond  python3 data_toolkit/render_cond.py  AlamCars --root "$ROOT" --num_cond_views 16
run enc_shape    python3 data_toolkit/encode_shape_latent.py --root "$ROOT" --resolution 1024
run enc_pbr      python3 data_toolkit/encode_pbr_latent.py   --root "$ROOT"
LNAME=$(ls "$ROOT/shape_latents" 2>/dev/null | head -1)
if [ -n "$LNAME" ]; then run enc_ss python3 data_toolkit/encode_ss_latent.py --root "$ROOT" --shape_latent_name "$LNAME"
else echo "SKIP enc_ss: no shape_latents dir"; fi

status merge-flags-after
python3 - <<'PY'
import glob, pandas as pd
p="/workspace/alamcars/metadata.csv"
m=pd.read_csv(p).set_index("sha256")
merged=0
pats=["/workspace/alamcars/*/metadata.csv","/workspace/alamcars/*/*/metadata.csv",
      "/workspace/alamcars/**/new_records/part_*.csv","/workspace/alamcars/**/merged_records/*.csv"]
seen=set()
for pat in pats:
    for f in glob.glob(pat, recursive=True):
        if f in seen or f==p: continue
        seen.add(f)
        try:
            df=pd.read_csv(f)
            if "sha256" in df.columns:
                m=df.set_index("sha256").combine_first(m); merged+=1
        except Exception: pass
m.reset_index().to_csv(p,index=False)
print(f"re-merged {merged} fragments")
PY

status diagnose-after
# THE GATE. diagnose-after compares against the before-report and exits nonzero
# unless the latent-bearing keep count went UP (or was already complete). A
# backfill that backfilled nothing must not report DONE.
python3 /tmp/gap_diag.py after || { status FATAL-no-progress; sleep infinity; }

status DONE
df -h /workspace | tail -1
sleep infinity
