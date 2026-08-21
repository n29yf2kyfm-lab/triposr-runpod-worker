#!/usr/bin/env python3
"""sb_chunk.py — put a large artefact in the bucket, in parts, and PROVE it.

RULE ZERO. Rollback #6 destroyed a finished 68 MB deliverable that existed
only on local disk. Everything DESCRIBING it survived — a verifier's 25-row
table, 19 negative controls, a certified sha256, 15 proof renders — and none
of it could bring the file back. The bucket held the code and the reports and
not the thing they were about.

So: the artefact goes up FIRST, before the report about it, in parts small
enough that neither Supabase endpoint refuses them (measured ceiling ~50 MB on
both the plain and the resumable path; 22 MB parts sit far under it), with a
MANIFEST carrying part order, byte counts, per-part sha256 and the whole-file
sha256, and a reassembly command a human can paste.

And it is verified by LISTING THE PREFIX afterwards, not by trusting the 200s.
A 200 on the small files reads identically to a complete backup, and a
truncated 50-row listing has already caused this project to declare a present
artefact missing. The listing here pages.

Storage needs BOTH `apikey:` and `Authorization: Bearer`. With Authorization
alone the bucket returns 403 "Invalid Compact JWS", which reads exactly like
an expired key and has cost this project hours.

Run:
    python3 sb_chunk.py put FILE staging/merge/glb [--part-mb 22]
    python3 sb_chunk.py list staging/merge
    python3 sb_chunk.py get staging/merge/glb/car_merged.glb OUT.glb
"""
import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request

SB = "https://tfkvthprsntexrcuqpyd.supabase.co"
BUCKET = "car-meshes"


def _key():
    k = os.environ.get("SB_KEY")
    if not k:
        raise SystemExit("SB_KEY not set: set -a; . /root/.alam3d_env; set +a")
    return k


def _hdr(extra=None):
    h = {"apikey": _key(), "Authorization": f"Bearer {_key()}"}
    h.update(extra or {})
    return h


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def post(path, blob, ctype="application/octet-stream", timeout=1800):
    rq = urllib.request.Request(
        f"{SB}/storage/v1/object/{BUCKET}/{path}", data=blob, method="POST",
        headers=_hdr({"Content-Type": ctype, "x-upsert": "true"}))
    with urllib.request.urlopen(rq, timeout=timeout) as r:
        return r.status


def fetch(path, timeout=1800):
    rq = urllib.request.Request(f"{SB}/storage/v1/object/{BUCKET}/{path}",
                                headers=_hdr())
    with urllib.request.urlopen(rq, timeout=timeout) as r:
        return r.read()


def listing(prefix, limit=100):
    """Every object under `prefix`, paged. A single page is not a listing."""
    out, off = [], 0
    while True:
        body = json.dumps(dict(prefix=prefix, limit=limit, offset=off,
                               sortBy=dict(column="name",
                                           order="asc"))).encode()
        rq = urllib.request.Request(
            f"{SB}/storage/v1/object/list/{BUCKET}", data=body, method="POST",
            headers=_hdr({"Content-Type": "application/json"}))
        with urllib.request.urlopen(rq, timeout=300) as r:
            page = json.loads(r.read())
        out += page
        if len(page) < limit:
            return out
        off += limit


def put(local, prefix, part_mb=22):
    size = os.path.getsize(local)
    whole = _sha(local)
    name = os.path.basename(local)
    part = part_mb * 1024 * 1024
    parts = []
    with open(local, "rb") as fh:
        i = 0
        while True:
            blk = fh.read(part)
            if not blk:
                break
            pn = f"{name}.part{i:03d}"
            post(f"{prefix}/{pn}", blk)
            parts.append((pn, len(blk), hashlib.sha256(blk).hexdigest()))
            print(f"  uploaded {pn}  {len(blk)} bytes")
            i += 1
    man = [
        f"artefact   : {name}",
        f"bytes      : {size}",
        f"sha256     : {whole}",
        f"parts      : {len(parts)}  (part size {part_mb} MiB)",
        "",
        "part order (concatenate in this order):",
    ]
    for pn, n, s in parts:
        man.append(f"  {pn}  {n} bytes  sha256 {s}")
    man += [
        "",
        "reassemble:",
        f"  cat {' '.join(p[0] for p in parts)} > {name}",
        f"  sha256sum {name}   # must print {whole}",
        "",
        "download each part (both headers are required):",
        f'  curl -s -H "apikey: $SB_KEY" -H "Authorization: Bearer $SB_KEY" \\',
        f'    -o PART "{SB}/storage/v1/object/{BUCKET}/{prefix}/PART"',
        "",
        "python: pipeline/machine/merge/sb_chunk.py get "
        f"{prefix}/{name} OUT.glb",
        "",
    ]
    post(f"{prefix}/MANIFEST.txt", "\n".join(man).encode(), "text/plain")
    print("  uploaded MANIFEST.txt")
    return dict(name=name, bytes=size, sha256=whole,
                parts=[dict(name=p[0], bytes=p[1], sha256=p[2]) for p in parts],
                prefix=prefix)


def get(remote, out):
    """Reassemble from parts (or fetch whole if it is not chunked)."""
    prefix = os.path.dirname(remote)
    name = os.path.basename(remote)
    objs = {o["name"] for o in listing(prefix)}
    parts = sorted(n for n in objs if n.startswith(name + ".part"))
    tmp = out + ".partial"
    with open(tmp, "wb") as fh:
        if parts:
            for p in parts:
                fh.write(fetch(f"{prefix}/{p}"))
        else:
            fh.write(fetch(remote))
    os.replace(tmp, out)
    return _sha(out)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("put")
    p.add_argument("file")
    p.add_argument("prefix")
    p.add_argument("--part-mb", type=int, default=22)
    l = sub.add_parser("list")
    l.add_argument("prefix")
    gg = sub.add_parser("get")
    gg.add_argument("remote")
    gg.add_argument("out")
    a = ap.parse_args()
    if a.cmd == "put":
        r = put(a.file, a.prefix, a.part_mb)
        print(json.dumps(r, indent=1))
    elif a.cmd == "list":
        rows = listing(a.prefix)
        tot = 0
        for o in rows:
            m = o.get("metadata") or {}
            tot += int(m.get("size") or 0)
            print(f"  {o['name']:52s} {m.get('size', '-')}")
        print(f"  ({len(rows)} objects, {tot} bytes under {a.prefix})")
    else:
        print(get(a.remote, a.out))


if __name__ == "__main__":
    main()
