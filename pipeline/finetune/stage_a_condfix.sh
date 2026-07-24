#!/bin/bash
# stage_a_condfix.sh — forensic-audit fix F1: Stage A left only 142/365 assets
# with conditioning renders, which silently caps training at 142 cars. This
# audits WHY, then re-runs render_cond for the missing assets only (upstream
# skips anything with transforms.json, so the good 142 are never touched), and
# deliberately does NOT rewrite the root metadata.csv — a concurrently running
# Stage B resume-probe re-reads it, and the next stage boot's metadata-merge
# sweeps the per-directory records this produces. Progress on :8000. No secrets.
ROOT=/workspace/alamcars
OUT=/workspace/alam3d_condfix
mkdir -p "$OUT/logs"
( cd "$OUT/logs" && python3 -m http.server 8000 >/dev/null 2>&1 & )
RUN_LOG="condfix_$(hostname)_$(date -u +%Y%m%dT%H%M%SZ).log"
ln -sf "$RUN_LOG" "$OUT/logs/stage_b.log"   # poller compatibility
exec > >(tee -a "$OUT/logs/$RUN_LOG") 2>&1
status(){ printf '{"step":"%s","at":"%s"}\n' "$1" "$(date -u +%FT%TZ)" > "$OUT/logs/status.json"; echo "===== $1 ====="; }

status boot
nvidia-smi -L || true
cd /app/TRELLIS.2 || { status FATAL-no-trellis2; sleep infinity; }
export PYTHONPATH=/app/TRELLIS.2:$PYTHONPATH
cp "$ROOT/AlamCars.py" datasets/ || { status FATAL-no-shim; sleep infinity; }

status audit-before
python3 - <<'PY'
import os, glob, pandas as pd
root="/workspace/alamcars"
m=pd.read_csv(f"{root}/metadata.csv")
have={os.path.basename(os.path.dirname(p)) for p in glob.glob(f"{root}/renders_cond/*/transforms.json")}
partial={os.path.basename(p.rstrip('/')) for p in glob.glob(f"{root}/renders_cond/*/")}-have
print(f"metadata rows: {len(m)}; complete cond renders: {len(have)}; "
      f"partial (no transforms.json, will re-render): {len(partial)}; "
      f"missing entirely: {len(set(m['sha256'])-have-partial)}")
PY
# WHY were they missed? pull error lines from any Stage A logs on the volume.
for f in $(find /workspace -maxdepth 3 -name "*stage_a*.log" 2>/dev/null | head -5); do
  echo "--- errors in $f:"
  grep -aiE "foreach_instance error|Traceback|killed|CUDA|blender" "$f" | sort | uniq -c | sort -rn | head -10
done

status render-cond-backfill
python3 data_toolkit/render_cond.py AlamCars --root "$ROOT" \
  --num_cond_views 16 --max_workers 8 \
  || echo "RENDER_COND FAILED (see log)"

status audit-after
python3 - <<'PY'
import os, glob, pandas as pd
root="/workspace/alamcars"
m=pd.read_csv(f"{root}/metadata.csv")
have={os.path.basename(os.path.dirname(p)) for p in glob.glob(f"{root}/renders_cond/*/transforms.json")}
missing=sorted(set(m['sha256'])-have)
print(f"AFTER: complete cond renders {len(have)}/{len(m)}; still missing {len(missing)}")
for s in missing[:20]:
    row=m[m['sha256']==s].iloc[0]
    print("  still-missing:", s[:12], row.get('make'), row.get('model'))
PY

status DONE
sleep infinity
