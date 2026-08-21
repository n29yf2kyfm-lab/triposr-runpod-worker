#!/bin/bash
# chunk_upload.sh <file> <bucket-prefix>   — RULE ZERO: the artefact goes up
# BEFORE the report about it. <=22 MiB parts + MANIFEST.txt, then VERIFY BY
# LISTING the prefix and checking byte counts.
set -eu
F="$1"; PREFIX="$2"
set -a; . /root/.alam3d_env; set +a
SB=https://tfkvthprsntexrcuqpyd.supabase.co/storage/v1
B=$(basename "$F"); D=$(mktemp -d)
split -b 22020096 -d -a 3 "$F" "$D/$B.part"
SHA=$(sha256sum "$F" | cut -d' ' -f1); SZ=$(stat -c%s "$F")
{
echo "artefact   : $B"
echo "bytes      : $SZ"
echo "sha256     : $SHA"
echo "parts      : $(ls "$D" | grep -c "$B.part")  (part size 21 MiB)"
echo
echo "part order (concatenate in this order):"
for p in "$D/$B".part*; do
  echo "  $(basename "$p")  $(stat -c%s "$p") bytes  sha256 $(sha256sum "$p"|cut -d' ' -f1)"
done
echo
echo "reassemble:"
echo "  cat $(cd "$D" && ls "$B".part* | tr '\n' ' ') > $B"
echo "  sha256sum $B   # must print $SHA"
echo
echo "download each part (BOTH headers are required):"
echo '  curl -s -H "apikey: $SB_KEY" -H "Authorization: Bearer $SB_KEY" \'
echo "    -o PART \"$SB/object/$PREFIX/PART\""
} > "$D/MANIFEST.txt"
for p in "$D"/*; do
  n=$(basename "$p")
  code=$(curl -sS -X POST -H "apikey: $SB_KEY" -H "Authorization: Bearer $SB_KEY" \
    -H "Content-Type: application/octet-stream" -H "x-upsert: true" \
    --data-binary "@$p" "$SB/object/$PREFIX/$n" -o /dev/null -w "%{http_code}")
  echo "upload $n $(stat -c%s "$p") bytes -> HTTP $code"
done
rm -rf "$D"
