#!/usr/bin/env bash
# Upload one file to car-meshes/staging/integrity/verify/<name> and VERIFY BY LISTING.
# CLAUDE.md: Supabase storage needs BOTH apikey: and Authorization: Bearer.
# RULE ZERO: never trust a 200 -- confirm the object appears in a prefix listing.
set -u
set -a; . /root/.alam3d_env; set +a
SB=https://tfkvthprsntexrcuqpyd.supabase.co
PREFIX=staging/integrity/verify
f="$1"; n="$(basename "$f")"; sub="${2:-}"
key="$PREFIX${sub:+/$sub}/$n"
code=$(curl -s -o /tmp/up.out -w '%{http_code}' -X POST \
  "$SB/storage/v1/object/car-meshes/$key" \
  -H "apikey: $SB_KEY" -H "Authorization: Bearer $SB_KEY" \
  -H "x-upsert: true" --data-binary @"$f")
# verify by listing the prefix
listed=$(curl -s -X POST "$SB/storage/v1/object/list/car-meshes" \
  -H "apikey: $SB_KEY" -H "Authorization: Bearer $SB_KEY" \
  -H 'Content-Type: application/json' \
  -d "{\"prefix\":\"$PREFIX${sub:+/$sub}\",\"limit\":1000}" \
  | python3 -c "import sys,json;d=json.load(sys.stdin);print(next((str(o.get('metadata',{}).get('size')) for o in d if o['name']=='$n'),'ABSENT'))" 2>/dev/null)
local_sz=$(stat -c%s "$f")
if [ "$listed" = "$local_sz" ]; then echo "OK   $key  ($listed bytes, listed)";
else echo "FAIL $key  http=$code listed=$listed local=$local_sz"; cat /tmp/up.out 2>/dev/null | head -2; fi
