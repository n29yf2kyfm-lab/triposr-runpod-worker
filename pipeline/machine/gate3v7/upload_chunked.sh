#!/usr/bin/env bash
# upload_chunked.sh -- split a GLB into <=22 MB parts, upload, then VERIFY BY
# LISTING the prefix.  Copies the pattern already in staging/gate5_surface/glb/
# and staging/gate4_rear/glb/, both of which survived rollback #6 intact while
# the 68 MB Gate 3 v6 deliverable -- uploaded as a single object, i.e. not at
# all -- did not.
#
# Supabase rejects objects over ~50 MB on BOTH the plain and the resumable
# endpoint (measured on Gate 6: a 63 MB file 413'd).  Storage needs BOTH an
# `apikey:` header AND `Authorization: Bearer`; with Authorization alone it
# returns 403 "Invalid Compact JWS", which reads exactly like an expired key.
#
# A 200 on the small files reads identically to a complete backup, so the
# listing check at the end is not optional -- it is the whole point.
#
# Usage: upload_chunked.sh <file.glb> <bucket-prefix>
set -euo pipefail
FILE="$1"; PREFIX="$2"
BASE="$(basename "$FILE")"
SB="https://tfkvthprsntexrcuqpyd.supabase.co"
CHUNK=22000000
: "${SB_KEY:?SB_KEY not set - source /root/.alam3d_env}"

SIZE=$(stat -c%s "$FILE")
SHA=$(sha256sum "$FILE" | cut -d' ' -f1)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
split -b "$CHUNK" -d -a 2 "$FILE" "$TMP/$BASE.part_"

PARTS=""
for p in "$TMP/$BASE".part_*; do PARTS="$PARTS $(basename "$p" | sed "s/^$BASE\.//")"; done
{
  echo "$BASE"
  echo "size: $SIZE bytes"
  echo "sha256: $SHA"
  echo "parts:$PARTS"
  echo "reassemble: cat $BASE.part_* > $BASE"
} > "$TMP/MANIFEST_$BASE.txt"

up () {  # $1 = local path, $2 = object name
  code=$(curl -s -o /tmp/_up.out -w '%{http_code}' -X POST \
    "$SB/storage/v1/object/car-meshes/$PREFIX/$2" \
    -H "apikey: $SB_KEY" -H "Authorization: Bearer $SB_KEY" \
    -H "Content-Type: application/octet-stream" \
    -H "x-upsert: true" --data-binary "@$1")
  echo "  $2 -> HTTP $code"
  [ "$code" = "200" ] || { cat /tmp/_up.out; return 1; }
}

echo "uploading $BASE ($SIZE bytes, sha ${SHA:0:16}...) to $PREFIX"
for p in "$TMP/$BASE".part_*; do up "$p" "$(basename "$p")"; done
up "$TMP/MANIFEST_$BASE.txt" "MANIFEST_$BASE.txt"

echo "VERIFY BY LISTING $PREFIX:"
# The listing JSON is written to a FILE and the checker reads it from there.
# Piping curl into `python3 - <<'PY'` does not work: the heredoc becomes stdin
# and the piped JSON is discarded, which failed with a JSONDecodeError that
# looked like a bad listing rather than a broken pipe.
curl -s -X POST "$SB/storage/v1/object/list/car-meshes" \
  -H "apikey: $SB_KEY" -H "Authorization: Bearer $SB_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"prefix\":\"$PREFIX\",\"limit\":200}" > "$TMP/listing.json"

cat > "$TMP/check.py" <<'PY'
import json, os, sys
listing = json.load(open(sys.argv[4]))
local_file, base, chunk = sys.argv[1], sys.argv[2], int(sys.argv[3])
size = os.path.getsize(local_file)
want = {}
n, off = 0, 0
while off < size:
    want[f"{base}.part_{n:02d}"] = min(chunk, size - off)
    off += chunk
    n += 1
got = {o["name"]: (o.get("metadata") or {}).get("size") for o in listing}
ok = True
for k, v in sorted(want.items()):
    g = got.get(k)
    mark = "OK " if g == v else "BAD"
    if g != v:
        ok = False
    print(f"  [{mark}] {k:44s} want {v:>10}  got {g}")
mf = f"MANIFEST_{base}.txt"
print(f"  [{'OK ' if mf in got else 'BAD'}] {mf}")
ok = ok and mf in got
print("TOTAL bytes in bucket:", sum(v for k, v in got.items() if k.startswith(base + ".part_")),
      "/ local", size)
print("UPLOAD_VERIFIED" if ok else "UPLOAD_INCOMPLETE")
sys.exit(0 if ok else 1)
PY
