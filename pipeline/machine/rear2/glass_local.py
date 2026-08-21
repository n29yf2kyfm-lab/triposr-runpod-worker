#!/usr/bin/env python3
"""glass_local.py — run pipeline/ingest/glass_probe.py VERBATIM on a LOCAL glb.

The shipped probe fetches by HTTP Range. Only the byte-source is replaced
(head() reads the local file); every rule in probe() is the shipped one, so
this cannot drift from the wave check.
"""
import json, sys, importlib.util
spec = importlib.util.spec_from_file_location(
    "glass_probe", "/home/user/triposr-runpod-worker/pipeline/ingest/glass_probe.py")
gp = importlib.util.module_from_spec(spec); spec.loader.exec_module(gp)

def local_head(path, n):
    with open(path, "rb") as f:
        return f.read(n)
gp.head = local_head
r = gp.probe("local", url=sys.argv[1])
print(json.dumps(r, indent=1))
if len(sys.argv) > 2: json.dump(r, open(sys.argv[2], "w"), indent=1)
