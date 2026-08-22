#!/usr/bin/env python3
"""glass_probe_local.py — run the project's glazing probe against a LOCAL GLB.

pipeline/ingest/glass_probe.py reads the glTF JSON chunk over HTTP Range from
the bucket, which is right for auditing a wave and useless for checking a file
you just wrote. This reuses its `probe()` verdict logic verbatim -- the
classifier is not reimplemented, because a second implementation would drift
from the one every catalogue ruling was made with -- and only swaps the source
of the JSON chunk for a local read.

Run: python3 glass_probe_local.py <file.glb> [file2.glb ...]
"""
import json
import struct
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "ingest"))
import glass_probe as GP


def local_gltf_json(path):
    b = open(path, "rb").read()
    if b[:4] != b"glTF":
        raise ValueError("not a GLB")
    off = 12
    while off < len(b):
        ln, ty = struct.unpack_from("<II", b, off)
        if ty == 0x4E4F534A:
            return json.loads(b[off + 8: off + 8 + ln].decode("utf-8", "replace"))
        off += 8 + ln + ((4 - ln % 4) % 4 if ln % 4 else 0)
    raise ValueError("no JSON chunk")


for p in sys.argv[1:]:
    GP.gltf_json = lambda _u, _p=p: local_gltf_json(_p)   # swap the fetch only
    try:
        r = GP.probe(os.path.basename(p), url="local")
    except Exception as e:
        r = {"verdict": "unknown", "error": f"{type(e).__name__}: {e}"}
    print(f"{os.path.basename(p)}: verdict={r.get('verdict')} "
          f"certainty={r.get('certainty')} "
          f"glazing_named={r.get('glazing_named')} "
          f"n_transparent={r.get('n_transparent')} "
          f"flat_shell={r.get('flat_shell')}")
