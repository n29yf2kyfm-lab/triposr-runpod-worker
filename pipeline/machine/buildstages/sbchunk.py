#!/usr/bin/env python3
"""sbchunk.py — chunk a large artefact, upload it, and VERIFY BY LISTING.

Rollback #6 destroyed a finished 68 MB deliverable today because it was never
uploaded.  The rules that came out of that, and which this file implements:

  1. a gate is not complete while its primary deliverable exists only on local
     disk.  Evidence is not the deliverable.
  2. chunk-and-upload the ARTEFACT first, before the report about it.
  3. Supabase rejects objects above ~50 MB on BOTH the plain and the resumable
     endpoint, so parts are capped at 22 MB.
  4. verify by LISTING the prefix, not by trusting the upload status -- a 200 on
     the small files reads identically to a complete backup.

The MANIFEST records part order, per-part sha256 and byte count, the whole-file
sha256, and the exact `cat` command that reassembles it.  Both headers are sent
(`apikey` AND `Authorization: Bearer`): with `Authorization` alone this storage
returns `403 Invalid Compact JWS`, which looks exactly like an expired key.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.error
import urllib.request

SB = "https://tfkvthprsntexrcuqpyd.supabase.co"
PART = 22_000_000


def _hdr():
    k = os.environ["SB_KEY"]
    return {"apikey": k, "Authorization": f"Bearer {k}"}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def put(key, data, bucket="car-meshes", content_type="application/octet-stream"):
    url = f"{SB}/storage/v1/object/{bucket}/{key}"
    h = dict(_hdr())
    h["Content-Type"] = content_type
    h["x-upsert"] = "true"
    req = urllib.request.Request(url, data=data, headers=h, method="POST")
    try:
        with urllib.request.urlopen(req) as r:
            return r.status
    except urllib.error.HTTPError as e:
        if e.code in (400, 409):                 # already exists -> replace
            req = urllib.request.Request(url, data=data, headers=h, method="PUT")
            with urllib.request.urlopen(req) as r:
                return r.status
        raise


def listing(prefix, bucket="car-meshes"):
    out, off = [], 0
    while True:
        body = json.dumps({"prefix": prefix, "limit": 100, "offset": off,
                           "sortBy": {"column": "name", "order": "asc"}}).encode()
        h = dict(_hdr())
        h["Content-Type"] = "application/json"
        req = urllib.request.Request(f"{SB}/storage/v1/object/list/{bucket}",
                                     data=body, headers=h)
        d = json.load(urllib.request.urlopen(req))
        if not d:
            break
        out += d
        off += len(d)
        if len(d) < 100:
            break
    return {o["name"]: (o.get("metadata") or {}).get("size") for o in out}


def upload_chunked(path, prefix, bucket="car-meshes", part=PART):
    name = os.path.basename(path)
    total = os.path.getsize(path)
    whole = sha256(path)
    parts = []
    with open(path, "rb") as fh:
        i = 0
        while True:
            b = fh.read(part)
            if not b:
                break
            pn = f"{name}.part_{i:03d}"
            put(f"{prefix}{pn}", b, bucket)
            parts.append((pn, len(b), hashlib.sha256(b).hexdigest()))
            print(f"   uploaded {pn}  {len(b):,} B")
            i += 1
    man = [f"# MANIFEST for {name}",
           f"# whole-file bytes  : {total}",
           f"# whole-file sha256 : {whole}",
           f"# parts             : {len(parts)}", "",
           "# part order, bytes, sha256:"]
    for pn, n, s in parts:
        man.append(f"{pn}  {n}  {s}")
    man += ["", "# reassemble (parts are in lexical order, which is part order):",
            f"cat {name}.part_* > {name}",
            f"sha256sum {name}    # must be {whole}", ""]
    mk = f"{prefix}MANIFEST_{name}.txt"
    put(mk, "\n".join(man).encode(), bucket, "text/plain")
    print(f"   uploaded MANIFEST_{name}.txt")

    # VERIFY BY LISTING -- a 200 on the small files reads exactly like a
    # complete backup, so the listing is the only proof.
    got = listing(prefix, bucket)
    missing = [pn for pn, n, s in parts if pn not in got]
    wrong = [(pn, n, got.get(pn)) for pn, n, s in parts
             if pn in got and got[pn] not in (None, n)]
    ok = not missing and not wrong and f"MANIFEST_{name}.txt" in got
    tot_up = sum(got.get(pn) or 0 for pn, n, s in parts)
    print(f"   LISTING: {len(parts)} parts, {tot_up:,} of {total:,} B present; "
          f"manifest {'present' if f'MANIFEST_{name}.txt' in got else 'MISSING'}")
    if not ok:
        raise SystemExit(f"UPLOAD NOT VERIFIED: missing={missing} wrong={wrong}")
    if tot_up != total:
        raise SystemExit(f"UPLOAD NOT VERIFIED: parts total {tot_up} != {total}")
    return {"name": name, "bytes": total, "sha256": whole,
            "parts": [{"name": pn, "bytes": n, "sha256": s} for pn, n, s in parts],
            "prefix": prefix, "verified_by_listing": True}


if __name__ == "__main__":
    p, pref = sys.argv[1], sys.argv[2]
    if os.path.getsize(p) <= PART:
        put(f"{pref}{os.path.basename(p)}", open(p, "rb").read())
        got = listing(pref)
        print(json.dumps({os.path.basename(p): got.get(os.path.basename(p))}))
    else:
        print(json.dumps(upload_chunked(p, pref), indent=1))
