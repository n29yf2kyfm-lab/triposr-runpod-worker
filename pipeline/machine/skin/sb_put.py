#!/usr/bin/env python3
"""sb_put.py -- chunk a file to <=22 MiB parts, upload, write a MANIFEST, then
VERIFY BY LISTING THE PREFIX.

Rollback #6 destroyed a finished 68 MB deliverable that existed only on local
disk while every report about it survived.  Supabase rejects objects above
~50 MB on BOTH the plain and the resumable endpoint, so a large mesh has to go
up in parts.  A 200 on the small files reads exactly like a complete backup --
so this verifies by LISTING the prefix and checking every part's byte count,
never by trusting the upload status.

Both the apikey: and Authorization: Bearer headers are required; with
Authorization alone storage returns 403 "Invalid Compact JWS", which looks
exactly like an expired key.

Run: sb_put.py <prefix> <file> [<file> ...]
     e.g. sb_put.py staging/skin/glb car_deskin.glb
"""
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request

SB = "https://tfkvthprsntexrcuqpyd.supabase.co"
BUCKET = "car-meshes"
PART = 22 * 1024 * 1024
KEY = os.environ["SB_KEY"]
H = {"apikey": KEY, "Authorization": "Bearer " + KEY}


def req(method, path, data=None, headers=None, ctype=None):
    h = dict(H)
    if headers:
        h.update(headers)
    if ctype:
        h["Content-Type"] = ctype
    r = urllib.request.Request(f"{SB}/storage/v1/{path}", data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(r, timeout=600) as f:
            return f.status, f.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def put(objpath, blob):
    st, body = req("POST", f"object/{BUCKET}/{objpath}", blob,
                   {"x-upsert": "true"}, "application/octet-stream")
    if st not in (200, 201):
        st, body = req("PUT", f"object/{BUCKET}/{objpath}", blob,
                       {"x-upsert": "true"}, "application/octet-stream")
    return st, body[:200]


def listing(prefix, limit=200):
    body = json.dumps({"prefix": prefix, "limit": limit,
                       "sortBy": {"column": "name", "order": "asc"}}).encode()
    st, b = req("POST", f"object/list/{BUCKET}", body, None, "application/json")
    return st, json.loads(b) if st == 200 else b


prefix = sys.argv[1].strip("/")
files = sys.argv[2:]
lines = []
expect = {}
for path in files:
    raw = open(path, "rb").read()
    name = os.path.basename(path)
    whole = hashlib.sha256(raw).hexdigest()
    parts = [raw[i:i + PART] for i in range(0, len(raw), PART)]
    lines += [f"artefact   : {name}", f"bytes      : {len(raw)}",
              f"sha256     : {whole}",
              f"parts      : {len(parts)}  (part size {PART//1048576} MiB)", "",
              "part order (concatenate in this order):"]
    pnames = []
    for i, p in enumerate(parts):
        pn = f"{name}.part{i:03d}"
        pnames.append(pn)
        st, msg = put(f"{prefix}/{pn}", p)
        expect[pn] = len(p)
        print(f"  PUT {pn:38s} {len(p):9d} bytes -> HTTP {st} {msg if st>=400 else ''}")
        assert st in (200, 201), f"upload failed for {pn}: {st} {msg}"
        lines.append(f"  {pn}  {len(p)} bytes  sha256 {hashlib.sha256(p).hexdigest()}")
    lines += ["", "reassemble:", "  cat " + " ".join(pnames) + f" > {name}",
              f"  sha256sum {name}   # must print {whole}", "",
              "download each part (BOTH headers are required):",
              f'  curl -s -H "apikey: $SB_KEY" -H "Authorization: Bearer $SB_KEY" \\',
              f'    -o PART "{SB}/storage/v1/object/{BUCKET}/{prefix}/PART"', "", "-" * 70, ""]

man = "\n".join(lines) + "\n"
st, msg = put(f"{prefix}/MANIFEST.txt", man.encode())
print(f"  PUT MANIFEST.txt -> HTTP {st}")
assert st in (200, 201)

print("\n=== VERIFY BY LISTING THE PREFIX (not by trusting the 200s) ===")
st, objs = listing(prefix)
assert st == 200, (st, objs)
got = {o["name"]: (o.get("metadata") or {}).get("size") for o in objs}
ok = True
for k, v in sorted(expect.items()):
    g = got.get(k)
    flag = "OK " if g == v else "MISMATCH"
    if g != v:
        ok = False
    print(f"  {flag} {k:40s} expected {v:9d}  listed {g}")
print(f"  {'OK ' if 'MANIFEST.txt' in got else 'MISSING'} MANIFEST.txt listed size {got.get('MANIFEST.txt')}")
print(f"\nlisting holds {len(got)} objects under {BUCKET}/{prefix}/")
for n, s in sorted(got.items()):
    print(f"    {n:44s} {s}")
assert ok and "MANIFEST.txt" in got, "PREFIX LISTING DOES NOT MATCH WHAT WAS UPLOADED"
print("\nVERIFIED: every part is listed at its exact byte count.")
