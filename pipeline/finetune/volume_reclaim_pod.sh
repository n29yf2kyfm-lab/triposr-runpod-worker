#!/bin/bash
# volume_reclaim_pod.sh — free space on alam3d-data and prove what survived.
#
# Diagnosis (2026-07-26, volume_diag_pod.sh): the 250GB network volume hit
# "Errno 122 Disk quota exceeded". Every write since then created the file and
# recorded its size but stored no blocks, so readers got all-NUL. That silently
# TRUNCATED Stage D's step-4000 checkpoint mid-save even though the trainer
# printed "Done."
#
# What gets deleted is deliberately narrow:
#   - alam3d_smoke/            the Stage B smoke run, disposable by design
#   - intermediate step ckpts  (non-EMA denoiser_step* and misc_step* for the
#                              steps we are not keeping) — optimizer/scheduler
#                              state only useful to RESUME a finished run
#   - any .pt that fails a zip integrity check (truncated by the full volume)
# Intact EMA weights are never deleted — they are what inference loads. A
# TRUNCATED EMA file is deleted, because it cannot be loaded by anything and
# leaving it in place would let the eval's newest-step-wins glob select it.
# Nothing under alamcars/ is touched — that is the dataset.
LOCAL=/root/reclaim
mkdir -p "$LOCAL"
( cd "$LOCAL" && python3 -m http.server 8000 >/dev/null 2>&1 & )
exec > >(tee -a "$LOCAL/stage_b.log") 2>&1
status(){ printf '{"step":"%s","at":"%s"}\n' "$1" "$(date -u +%FT%TZ)" > "$LOCAL/status.json"; echo "===== $1 ====="; }

status inventory
df -h /workspace | tail -1
for d in /workspace/alam3d_stage_c/ckpts /workspace/alam3d_stage_d/ckpts; do
  echo "--- $d"
  ls -la "$d" 2>/dev/null | awk 'NR>1{printf "  %12d  %s\n", $5, $NF}'
done

status integrity
# A torch .pt is a zip. Reading its central directory (at the END of the file)
# proves the whole file landed — cheap and definitive for truncation.
python3 - <<'PY' > "$LOCAL/integrity.txt" 2>&1
import glob, os, zipfile
bad = []
for p in sorted(glob.glob("/workspace/alam3d_stage_*/ckpts/*.pt")):
    sz = os.path.getsize(p)
    try:
        with zipfile.ZipFile(p) as z:
            n = len(z.namelist())
        print(f"OK      {sz:>13,}  {n:>4} entries  {p}")
    except Exception as e:
        print(f"CORRUPT {sz:>13,}  {type(e).__name__}: {str(e)[:50]}  {p}")
        bad.append(p)
# trailing newline matters: `while read -r` drops a final unterminated line,
# which silently spared one corrupt checkpoint on the first run
open("/root/reclaim/corrupt.txt", "w").write("".join(p + "\n" for p in bad))
print(f"\n{len(bad)} corrupt file(s)")
PY
cat "$LOCAL/integrity.txt"

status delete
FREED=0
del(){ [ -e "$1" ] || return 0; S=$(du -sm "$1" 2>/dev/null | cut -f1); rm -rf "$1" && echo "  deleted ${S}MB  $1"; }

# 1. the smoke run — a throwaway gate that already passed
del /workspace/alam3d_smoke

# 2. intermediate optimizer/scheduler state. Keep the LAST intact step of each
#    stage so a resume is still possible; EMA weights are untouched throughout.
for s in 0001000 0002000 0003000; do
  del "/workspace/alam3d_stage_c/ckpts/misc_step$s.pt"
  del "/workspace/alam3d_stage_c/ckpts/denoiser_step$s.pt"
done
for s in 0001000 0002000; do
  del "/workspace/alam3d_stage_d/ckpts/misc_step$s.pt"
  del "/workspace/alam3d_stage_d/ckpts/denoiser_step$s.pt"
done

# 3. anything the integrity pass proved truncated — it cannot be loaded, and
#    leaving it in place would let the eval's "newest step wins" glob pick it
while read -r f; do [ -n "$f" ] && del "$f"; done < "$LOCAL/corrupt.txt"

status verify
df -h /workspace | tail -1
echo "--- surviving checkpoints:"
ls -la /workspace/alam3d_stage_c/ckpts /workspace/alam3d_stage_d/ckpts 2>/dev/null
echo
echo "--- write test after reclaim:"
python3 - <<'PY'
import os
p = "/workspace/_reclaim_write_test"
try:
    with open(p, "wb") as f:
        f.write(b"X" * 100_000_000)      # 100MB, fsync'd
        f.flush(); os.fsync(f.fileno())
    d = open(p, "rb").read()
    print("VERDICT:", "WRITES-OK" if d.count(b"\0") == 0 and len(d) == 100_000_000 else "WRITES-BROKEN")
except Exception as e:
    print("VERDICT: WRITES-BROKEN", type(e).__name__, e)
finally:
    try: os.remove(p)
    except Exception: pass
PY

echo "--- which Stage D EMA checkpoint the eval will now pick:"
python3 - <<'PY'
import glob, os, zipfile
for pat, label in (("/workspace/alam3d_stage_c/ckpts/denoiser_ema*step*.pt", "Stage C 512"),
                   ("/workspace/alam3d_stage_d/ckpts/denoiser_ema*step*.pt", "Stage D 1024")):
    ck = sorted(glob.glob(pat), reverse=True)
    if not ck:
        print(f"{label}: NONE FOUND"); continue
    p = ck[0]
    try:
        with zipfile.ZipFile(p) as z: ok = f"{len(z.namelist())} entries"
    except Exception as e: ok = f"CORRUPT {type(e).__name__}"
    print(f"{label}: {os.path.basename(p)} ({os.path.getsize(p)//1024//1024}MB, {ok})")
PY

status DONE
sleep infinity
