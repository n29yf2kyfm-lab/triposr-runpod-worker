#!/usr/bin/env bash
# upload_evidence.sh -- put the gate's evidence in the bucket alongside the GLB.
#
# Rollback #6 destroyed a 68 MB deliverable while every report ABOUT it survived,
# so the lesson is usually stated the other way round.  It cuts both ways: the
# reports are cheap and they are also the only thing that makes the GLB
# reviewable.  Both go up, and both are verified by LISTING the prefix.
#
# Usage: upload_evidence.sh <evidence-dir> <bucket-prefix>
set -euo pipefail
EV="$1"; PREFIX="$2"
SB="https://tfkvthprsntexrcuqpyd.supabase.co"
: "${SB_KEY:?SB_KEY not set - source /root/.alam3d_env}"

up () {
  code=$(curl -s -o /tmp/_ev.out -w '%{http_code}' -X POST \
    "$SB/storage/v1/object/car-meshes/$PREFIX/$2" \
    -H "apikey: $SB_KEY" -H "Authorization: Bearer $SB_KEY" \
    -H "Content-Type: application/octet-stream" -H "x-upsert: true" \
    --data-binary "@$1")
  printf '  %-46s HTTP %s  %s bytes\n' "$2" "$code" "$(stat -c%s "$1")"
  [ "$code" = "200" ] || { cat /tmp/_ev.out; return 1; }
}

for f in "$EV"/*.json "$EV"/*.md; do
  [ -e "$f" ] || continue
  up "$f" "$(basename "$f")"
done
for f in "$EV"/*/*.png "$EV"/*.png; do
  [ -e "$f" ] || continue
  case "$(basename "$f")" in _probe_*) continue ;; esac
  d=$(basename "$(dirname "$f")")
  n=$(basename "$f")
  [ "$d" = "$(basename "$EV")" ] && up "$f" "$n" || up "$f" "${d}__${n}"
done

echo "VERIFY BY LISTING $PREFIX:"
curl -s -X POST "$SB/storage/v1/object/list/car-meshes" \
  -H "apikey: $SB_KEY" -H "Authorization: Bearer $SB_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"prefix\":\"$PREFIX\",\"limit\":500}" \
| python3 -c "
import json,sys
rows=json.load(sys.stdin)
tot=sum((o.get('metadata') or {}).get('size',0) for o in rows)
print(f'  {len(rows)} objects, {tot} bytes total')
for o in sorted(rows,key=lambda r:r['name'])[:200]:
    print(f\"    {o['name']:52s} {(o.get('metadata') or {}).get('size','?')}\")
"
