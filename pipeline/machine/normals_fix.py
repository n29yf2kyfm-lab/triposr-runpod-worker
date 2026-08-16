#!/usr/bin/env python3
"""normals_fix.py — write smooth welded vertex normals into an assembled GLB.

trimesh submesh exports carry NO vertex normals (the finish_car lesson,
re-measured on the gseg Golf v6: zero NORMAL accessors on six primitives),
so every triangle shades FLAT and the studio clearcoat renders the car as
crumpled foil — the "crystalline faceting" the eye audits kept flagging.

Fix: per geometry (= per material, so material boundaries stay hard),
weld vertex positions across the fragment soup and average area-weighted
face normals per welded position — fragment seams shade continuously.
Geometry is untouched; only NORMAL data is added.

Run: python3 normals_fix.py <in.glb> <out.glb>
"""
import sys
import numpy as np
import trimesh

INP, OUT = sys.argv[1], sys.argv[2]

sc = trimesh.load(INP, force="scene")
for name, gm in sc.geometry.items():
    V, F = gm.vertices, gm.faces
    scale = float(np.ptp(V, axis=0).max()) or 1.0
    key = np.round(V / (1e-6 * scale)).astype(np.int64)
    _, inv = np.unique(key, axis=0, return_inverse=True)
    fn = gm.face_normals
    fa = gm.area_faces
    acc = np.zeros((inv.max() + 1, 3))
    for k in range(3):
        np.add.at(acc, inv[F[:, k]], fn * fa[:, None])
    n = acc[inv]
    ln = np.linalg.norm(n, axis=1, keepdims=True)
    n = np.where(ln > 1e-12, n / np.clip(ln, 1e-12, None), [0.0, 1.0, 0.0])
    gm.vertex_normals = n
    print(f"{name}: {len(V)} verts, {len(V) - (inv.max()+1)} seam duplicates share normals")

sc.export(OUT)

# verify the exporter actually wrote them — a fix that does not fire is the
# documented failure class
import json, struct
b = open(OUT, "rb").read()
jlen = struct.unpack("<I", b[12:16])[0]
g = json.loads(b[20:20 + jlen])
missing = [m["name"] for m in g["meshes"]
           for p in m["primitives"] if "NORMAL" not in p["attributes"]]
if missing:
    raise SystemExit(f"NORMALS NOT WRITTEN for {missing} — exporter dropped them")
import os
print("wrote", OUT, os.path.getsize(OUT), "bytes — NORMAL present on all primitives")
