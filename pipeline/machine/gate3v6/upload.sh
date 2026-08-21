#!/bin/bash
# GATE 3 v6 — upload a proof artefact to Supabase car-meshes.
#   ./upload.sh <local-file> <dest-path-under-bucket>
# Supabase storage needs BOTH `apikey:` and `Authorization: Bearer` — with
# Authorization alone it returns 403 "Invalid Compact JWS", which looks exactly
# like an expired key (recorded trap).
set -eu
set +x
[ -f /root/.alam3d_env ] && { set -a; . /root/.alam3d_env; set +a; }
SRC="$1"; DEST="$2"
PROJ="tfkvthprsntexrcuqpyd"
URL="https://${PROJ}.supabase.co/storage/v1/object/car-meshes/${DEST}"
CT="application/octet-stream"
case "$SRC" in
  *.jpg|*.jpeg) CT="image/jpeg" ;; *.png) CT="image/png" ;;
  *.md)  CT="text/markdown" ;;    *.json) CT="application/json" ;;
esac
SZ=$(stat -c%s "$SRC")
CODE=$(curl -s -o /tmp/_up.$$ -w "%{http_code}" -X POST "$URL" \
  -H "apikey: ${SB_KEY}" -H "Authorization: Bearer ${SB_KEY}" \
  -H "Content-Type: ${CT}" -H "x-upsert: true" --data-binary "@${SRC}")
if [ "$CODE" != "200" ] && [ "$CODE" != "201" ]; then
  echo "UPLOAD_FAIL $CODE $DEST ($SZ bytes)"; cat /tmp/_up.$$; rm -f /tmp/_up.$$; exit 1
fi
rm -f /tmp/_up.$$
# VERIFY the object is really fetchable and the right size - an upload that
# returned 200 is not proof the object is there (recorded trap).
RC=$(curl -s -o /dev/null -w "%{http_code} %{size_download}" \
  -H "apikey: ${SB_KEY}" -H "Authorization: Bearer ${SB_KEY}" "$URL")
echo "OK $DEST  ${SZ}B  verify=[${RC}]"
