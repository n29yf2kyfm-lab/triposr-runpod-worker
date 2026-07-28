#!/bin/bash
# purge_void_runs_pod.sh — remove the two training runs that are void, and
# nothing else.
#
# WHY THESE TWO AND ONLY THESE TWO
# The learning rate in every run before 2026-07-27 was written to a config key
# the optimizer does not read (`trainer.args.learning_rate` instead of
# `trainer.args.optimizer.args.lr`). Stage C v0 nominally ran 1e-5 and Stage D
# nominally 8e-6; both actually ran at the stock 1e-4. Their weights are not
# "worse checkpoints" — they are experiments whose stated conditions never held,
# so nothing can be concluded from them.
#
#   alam3d_stage_c   ~34 GB   v0. Its published step-4000 EMA is already backed
#                             up at Alamj/alam-3d-v0 on HuggingFace.
#   alam3d_stage_d   ~30 GB   Stage D. Its step-4000 was silently truncated by
#                             the 2026-07-26 full-volume event, so it is both
#                             void AND partly corrupt.
#
# NOT TOUCHED, deliberately:
#   alam3d_stage_c_v1  the only correctly-configured checkpoints this project
#                      has. Owner approved deleting "old broken data" — this is
#                      the new, good data.
#   alamcars           the dataset.
#   hf_cache           re-downloadable, but leaving it keeps later pods fast.
#
# The inventory is written and uploaded BEFORE any delete, so what was removed
# is recorded even though the bytes are gone. A deletion nobody can describe
# afterwards is not a cleanup, it is a loss.
LOCAL=/root/purge
mkdir -p "$LOCAL/logs"
( cd "$LOCAL/logs" && python3 -m http.server 8000 >/dev/null 2>&1 & )
RUN_LOG="purge_$(hostname)_$(date -u +%Y%m%dT%H%M%SZ).log"
ln -sf "$RUN_LOG" "$LOCAL/logs/stage_b.log"
exec > >(tee -a "$LOCAL/logs/$RUN_LOG") 2>&1
status(){ printf '{"step":"%s","at":"%s"}\n' "$1" "$(date -u +%FT%TZ)" > "$LOCAL/logs/status.json"; echo "===== $1 ====="; }

status boot
[ -d /workspace ] || { echo "FATAL: /workspace not mounted"; status FATAL-no-volume; sleep infinity; }
echo "--- free space BEFORE ---"
df -h /workspace | tail -1
BEFORE=$(df -m /workspace | tail -1 | awk '{print $4}')

status inventory
# Record everything before removing it. This file is the only thing that will
# survive the delete.
INV="$LOCAL/logs/purged_inventory.txt"
for d in /workspace/alam3d_stage_c /workspace/alam3d_stage_d; do
  echo "=== $d ===" >> "$INV"
  if [ -d "$d" ]; then
    du -sh "$d" >> "$INV" 2>/dev/null
    find "$d" -type f -printf '%10s  %p\n' 2>/dev/null | sort -rn | head -60 >> "$INV"
  else
    echo "  (absent)" >> "$INV"
  fi
done
wc -l "$INV"; echo "--- inventory head ---"; head -25 "$INV"

status guard
# Refuse to run if the directory we must NOT delete is missing — that would mean
# this pod is looking at a different volume than the one we think it is.
if [ ! -d /workspace/alam3d_stage_c_v1 ]; then
  echo "FATAL: /workspace/alam3d_stage_c_v1 is absent. This is not the volume"
  echo "       holding the good checkpoints — refusing to delete anything."
  status FATAL-wrong-volume; sleep infinity
fi
KEEP=$(du -sm /workspace/alam3d_stage_c_v1 2>/dev/null | cut -f1)
echo "good run present: alam3d_stage_c_v1 = ${KEEP}MB (will NOT be touched)"
if [ "${KEEP:-0}" -lt 10000 ]; then
  echo "FATAL: the good run is only ${KEEP}MB — expected tens of GB. Aborting"
  echo "       rather than deleting anything next to a directory that looks wrong."
  status FATAL-good-run-too-small; sleep infinity
fi

status purge
del(){
  [ -e "$1" ] || { echo "  absent, nothing to do: $1"; return 0; }
  S=$(du -sm "$1" 2>/dev/null | cut -f1)
  rm -rf "$1" && echo "  DELETED ${S}MB  $1"
}
del /workspace/alam3d_stage_c
del /workspace/alam3d_stage_d

status verify
echo "--- free space AFTER ---"
df -h /workspace | tail -1
AFTER=$(df -m /workspace | tail -1 | awk '{print $4}')
echo "freed: $(( (AFTER - BEFORE) / 1024 )) GB"
echo "--- what remains at top level ---"
du -sh /workspace/* 2>/dev/null | sort -rh | head -10
echo "--- the good run is still here ---"
du -sh /workspace/alam3d_stage_c_v1 2>/dev/null || echo "  MISSING - THIS IS BAD"
ls /workspace/alam3d_stage_c_v1/ckpts/ 2>/dev/null | head -20

status upload
if [ -n "$SB_KEY" ]; then
  curl -s -X POST -H "apikey: $SB_KEY" -H "Authorization: Bearer $SB_KEY" \
    -H "Content-Type: text/plain" -H "x-upsert: true" \
    --data-binary @"$INV" \
    "https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object/car-meshes/audit/purged_inventory.txt" \
    && echo "inventory uploaded"
fi

status DONE
sleep infinity
