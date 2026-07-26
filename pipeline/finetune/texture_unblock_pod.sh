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
python3 - <<'PY'
import glob, os
root="/workspace/alamcars"
for d in ("pbr_voxels_256","pbr_voxels_512","pbr_voxels_1024"):
    n=len(glob.glob(f"{root}/{d}/*.vxz"))
    if n: print(f"  {d}: {n} voxel files")
for d in sorted(glob.glob(f"{root}/pbr_latents/*/")):
    n=len(glob.glob(d+"*.npz"))+len(glob.glob(d+"*.pt"))
    print(f"  {os.path.basename(d.rstrip('/'))}: {n} latents")
import pandas as pd
m=pd.read_csv(f"{root}/metadata.csv")
for c in [c for c in m.columns if "pbr" in c.lower()]:
    try: print(f"  flag {c}: {int(m[c].fillna(False).astype(bool).sum())}")
    except Exception: pass
PY

status DONE
du -sh "$ROOT"/pbr_* 2>/dev/null
sleep infinity
