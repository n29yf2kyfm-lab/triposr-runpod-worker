#!/bin/bash
# chunk_upload.sh <file> <bucket_prefix> [part_mb]
# Splits a large artefact into <=22MB parts + MANIFEST.txt and uploads BOTH,
# then VERIFIES BY LISTING the prefix and comparing byte counts.
# Supabase rejects >~50MB on the plain AND the resumable endpoint, and a 200 on
# the small files reads identically to a complete backup -- so the listing, not
# the upload status, is the proof (CLAUDE.md, rollback #6).
set -eu
F="$1"; PREFIX="$2"; MB="${3:-22}"
: "${SB_KEY:?SB_KEY not set}"
B="https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object/car-meshes"
BASE=$(basename "$F"); WORK=$(mktemp -d)
split -b "${MB}000000" -d -a 3 "$F" "$WORK/${BASE}.part_"
SHA=$(sha256sum "$F" | cut -d' ' -f1); SZ=$(stat -c%s "$F")
{
  echo "file    = $BASE"
  echo "sha256  = $SHA"
  echo "bytes   = $SZ"
  echo "parts   = $(ls "$WORK" | grep -c part_)"
  echo "order   = lexical by part suffix (part_000, part_001, ...)"
  echo "reassemble: cat ${BASE}.part_* > $BASE"
  echo "verify    : sha256sum $BASE   ->  $SHA"
  ls -l "$WORK" | awk 'NR>1{print "  "$9"  "$5" bytes"}'
} > "$WORK/MANIFEST_${BASE}.txt"
for p in "$WORK"/*; do
  n=$(basename "$p")
  code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$B/$PREFIX/$n" \
    -H "apikey: $SB_KEY" -H "Authorization: Bearer $SB_KEY" \
    -H "Content-Type: application/octet-stream" -H "x-upsert: true" \
    --data-binary @"$p")
  echo "  PUT $n -> $code"
  [ "$code" = "200" ] || { echo "UPLOAD FAILED $n"; exit 1; }
done
echo "--- VERIFY BY LISTING $PREFIX ---"
curl -s -X POST "https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1/object/list/car-meshes" \
  -H "apikey: $SB_KEY" -H "Authorization: Bearer $SB_KEY" -H "Content-Type: application/json" \
  -d "{\"prefix\":\"$PREFIX/\",\"limit\":200}" |
  python3 -c "
import sys,json
d=json.load(sys.stdin); tot=0
for x in sorted(d,key=lambda a:a['name']):
    s=(x.get('metadata') or {}).get('size',0); tot+=s if 'part_' in x['name'] else 0
    print(f\"  {x['name']:44s} {s:>12,} bytes\")
print(f'  PART BYTES TOTAL = {tot:,}  (local file $SZ)')
print('  MATCH' if tot==$SZ else '  *** MISMATCH ***')"
rm -rf "$WORK"
