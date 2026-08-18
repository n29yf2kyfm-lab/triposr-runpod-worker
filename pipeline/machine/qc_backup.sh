#!/bin/bash
# qc_backup.sh — push a QC working directory to the bucket, immediately.
#
# Written after the 2026-08-18 rollback ate an entire stage-2 evidence set
# (renders, sub-scene GLBs, the V42 build) while the COMMITTED scripts and
# the BUCKET-BACKED inputs both survived intact. The rule in CLAUDE.md
# already said "upload every work product the moment it validates"; this
# makes it one command so there is no excuse to defer it.
#
# Usage: bash qc_backup.sh <qc_dir> <bucket_prefix>
#   e.g. bash qc_backup.sh ./qc machine_v42
# Requires SB_KEY in the environment (set -a; . /root/.alam3d_env; set +a).
set -u
DIR="${1:?qc dir}"; PREFIX="${2:?bucket prefix}"
BASE="https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object/car-meshes/staging/$PREFIX"
: "${SB_KEY:?SB_KEY not in environment}"

ok=0; fail=0
while IFS= read -r f; do
    rel="${f#"$DIR"/}"
    flat="${rel//\//_}"
    case "$f" in
        *.png) ct="image/png";; *.jpg) ct="image/jpeg";;
        *.json) ct="application/json";; *.glb) ct="model/gltf-binary";;
        *) ct="application/octet-stream";;
    esac
    sz=$(stat -c%s "$f")
    if [ "$sz" -gt 52000000 ]; then
        echo "SKIP (>50MiB object cap, split it): $rel"; fail=$((fail+1)); continue
    fi
    code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/$flat" \
        -H "apikey: $SB_KEY" -H "Authorization: Bearer $SB_KEY" \
        -H "Content-Type: $ct" -H "x-upsert: true" --data-binary @"$f")
    if [ "$code" = "200" ]; then ok=$((ok+1)); else
        echo "FAIL $code: $rel"; fail=$((fail+1)); fi
done < <(find "$DIR" -type f)
echo "qc_backup: $ok uploaded, $fail failed -> staging/$PREFIX/"
[ "$fail" -eq 0 ]
