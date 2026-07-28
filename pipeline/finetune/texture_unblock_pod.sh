#!/bin/bash
# texture_unblock_pod.sh — unblock the TEXTURE half of the dataset.
#
# Root cause (found 2026-07-26): Stage A's voxelize_pbr filters on
# metadata['pbr_dumped'] == True, but that flag is written to the PER-DIRECTORY
# pbr_dumps metadata, never to the root metadata.csv the step reads. The filter
# matched zero rows, so no PBR voxels were produced and encode_pbr_latent then
# failed with KeyError 'pbr_voxelized'. The 9.1GB of PBR dumps were always fine
# — nothing ever looked at them. (Same class of bug as Stage D seeing 365 of
# 543 shapes: per-directory flags not merged into root.)
#
# This merges the flags first, proves the count, then runs the two missing
# steps. Texture-stage training needs pbr voxels + pbr latents; geometry
# training is untouched by any of this.
ROOT=/workspace/alamcars
mkdir -p "$ROOT/logs"
( cd "$ROOT/logs" && python3 -m http.server 8000 >/dev/null 2>&1 & )
RUN_LOG="texfix_$(hostname)_$(date -u +%Y%m%dT%H%M%SZ).log"
ln -sf "$RUN_LOG" "$ROOT/logs/stage_b.log"
exec > >(tee -a "$ROOT/logs/$RUN_LOG") 2>&1
status(){ printf '{"step":"%s","at":"%s"}\n' "$1" "$(date -u +%FT%TZ)" > "$ROOT/logs/status.json"; echo "===== $1 ====="; }

status boot
[ -f /etc/rp_environment ] && source /etc/rp_environment
export HF_TOKEN HUGGING_FACE_HUB_TOKEN
nvidia-smi -L || true
cd /app/TRELLIS.2 || { status FATAL-no-trellis2; sleep infinity; }
export PYTHONPATH=/app/TRELLIS.2:$PYTHONPATH
pip install -q pandas easydict pillow || true
bash data_toolkit/setup.sh || echo "setup.sh failed (continuing)"
mkdir -p datasets && cp "$ROOT/AlamCars.py" datasets/AlamCars.py && touch datasets/__init__.py

status merge-flags
python3 - <<'PY'
import glob, pandas as pd
p="/workspace/alamcars/metadata.csv"
m=pd.read_csv(p).set_index("sha256")
before=[c for c in m.columns if "pbr" in c.lower()]
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
after=[c for c in m.columns if "pbr" in c.lower()]
dumped=int(m["pbr_dumped"].fillna(False).sum()) if "pbr_dumped" in m.columns else 0
print(f"merged {merged} files | pbr cols before={before} after={after}")
print(f"PBR-DUMPED ROWS: {dumped} of {len(m)}   <- voxelize_pbr saw 0 of these before the merge")
PY

status arch-check
# ARCHITECTURE GUARD. The container's CUDA kernels are compiled for sm_80 and
# below. Land on a newer card and every kernel launch fails with "no kernel
# image is available for execution on the device" — but only once real work
# starts, which on 2026-07-28 meant 25 minutes and $0.45 spent before an H100
# admitted it could not run this image. torch knows both halves of the answer at
# import time; ask it in seconds, before anything expensive happens.
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
    print(f"FATAL: this image has no kernels for {have} ({name}).")
    print(f"       Supported: {' '.join(built)}")
    sys.exit(1)
print(f"arch OK: {have} is supported by this image")
PYARCH

status space-check
# VOLUME SPACE GUARD. This volume filled to 236/250GB on 2026-07-27 and silently
# truncated a checkpoint mid-save — the file looked present, was 3264MB against a
# healthy 5169MB, and only failed when something tried to unzip it four
# checkpoints into a GPU sweep. voxelize_pbr at 512 AND 1024 writes a lot. Refuse
# to start a write-heavy job without room, rather than discover the ceiling by
# corrupting something.
python3 - <<'PYSPACE' || { status FATAL-no-space; sleep infinity; }
import os, shutil, sys
need_gb = float(os.environ.get("MIN_FREE_GB", "40"))
t, u, f = shutil.disk_usage("/workspace")
gb = 1024 ** 3
print(f"/workspace: {u/gb:.0f}GB used of {t/gb:.0f}GB, {f/gb:.0f}GB free "
      f"(need {need_gb:.0f}GB)")
if f / gb < need_gb:
    print("FATAL: not enough headroom. Reclaim space before running this.")
    sys.exit(1)
PYSPACE

status voxelize-pbr
# UPSTREAM BUG: --resolution is declared type=str with default=1024 (an int),
# and the parser then calls .split(",") on it — so omitting the flag always
# raises AttributeError. Stage A omitted it, which is why no PBR voxels exist.
python3 data_toolkit/voxelize_pbr.py AlamCars --root "$ROOT" --resolution 512,1024 \
  || echo "STEP-FAILED voxelize_pbr"
python3 data_toolkit/build_metadata.py AlamCars --root "$ROOT" >/dev/null 2>&1 || true

status encode-pbr-latent
python3 data_toolkit/encode_pbr_latent.py --root "$ROOT" || echo "STEP-FAILED encode_pbr_latent"
python3 data_toolkit/build_metadata.py AlamCars --root "$ROOT" >/dev/null 2>&1 || true

status audit
# THIS IS A GATE, NOT A REPORT.
# Both steps above end in `|| echo STEP-FAILED`, so a total no-op reaches this
# point looking exactly like a success — and the old version then printed some
# zeros and set status DONE. That is the same failure shape as the run that
# exited 0 having trained nothing because a gated HF repo 401'd: a green
# terminal state over work that never happened. The whole purpose of this pod is
# to produce PBR latents. No latents, no DONE.
python3 - <<'PY' || { echo "TEXTURE DATA NOT PRODUCED"; status FATAL-no-latents; sleep infinity; }
import glob, os, sys
root = "/workspace/alamcars"
vox = 0
for d in sorted(glob.glob(f"{root}/pbr_voxels*")):
    n = len(glob.glob(f"{d}/*.vxz")) or len(glob.glob(f"{d}/*"))
    vox += n
    print(f"  {os.path.basename(d)}: {n} voxel files")
lat = 0
for d in sorted(glob.glob(f"{root}/pbr_latents/*/")):
    n = len(glob.glob(d + "*.npz")) + len(glob.glob(d + "*.pt"))
    lat += n
    print(f"  pbr_latents/{os.path.basename(d.rstrip('/'))}: {n} latents")
try:
    import pandas as pd
    m = pd.read_csv(f"{root}/metadata.csv")
    for c in [c for c in m.columns if "pbr" in c.lower()]:
        try:
            print(f"  flag {c}: {int(m[c].fillna(False).astype(bool).sum())} of {len(m)}")
        except Exception:
            pass
except Exception as e:
    print("  metadata read failed:", str(e)[:80])
print(f"TOTALS: {vox} voxel files, {lat} latents")
if lat == 0:
    print("FATAL: zero PBR latents. Texture training is still blocked — the "
          "steps above reported failure or matched no rows. Do not record this "
          "as a success.")
    sys.exit(1)
if vox == 0:
    print("FATAL: latents exist but zero voxel files — inconsistent state, "
          "not treating this as done.")
    sys.exit(1)
print(f"texture data unblocked: {lat} latents across {vox} voxel files")
PY

status DONE
du -sh "$ROOT"/pbr_* 2>/dev/null
sleep infinity
