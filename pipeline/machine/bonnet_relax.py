#!/usr/bin/env python3
"""bonnet_relax.py — relax the scuttle dish that focuses sun into a clipped pool.

Stage-3's clipping gate located ~1,400 clipped pixels in ONE pool on the
bonnet/scuttle (locked right_ortho, overlay in qc/stage3/). Material moves
within the brief's band were tested and REFUTED: rough 0.24->0.28 +
clearcoat 0.08->0.12 spread the highlight and RAISED clipping 0.942% ->
1.037%. The cause is geometry: a concave melt dish acting as a focusing
mirror.

Fix: capped Laplacian relaxation of carpaint vertices INSIDE the scuttle
box only, with an edge feather (weight ramps to zero at the region border
so no step is introduced) and a hard per-vertex displacement cap. This is
curvature relaxation of a measured defect region — the panel's overall
shape survives because the cap is millimetres.

Run: python3 bonnet_relax.py <in.glb> <out.glb> [cap_mm]
"""
import json
import struct
import sys
import numpy as np
import trimesh

INP, OUT = sys.argv[1], sys.argv[2]
CAP = float(sys.argv[3]) / 1000 if len(sys.argv) > 3 else 0.008
BOX = dict(x=(1.10, 1.98), y=(0.60, 0.90), z=(-0.78, 0.78))
# ^ corrected: proper unprojection of the clipped pool (rows 380-440 at
#   CY 0.766, 2.19mm/px) puts it at y 0.68-0.81, x 1.28-1.9 — the bonnet
#   slope toward the nose. The first box (y 0.88-1.15) missed it entirely
#   and measured a null result (0.948% vs 0.942%).
ITERS = 40

sc = trimesh.load(INP, force="scene")
cp = sc.geometry["carpaint"]
V = cp.vertices.copy()
sel = (V[:, 0] > BOX["x"][0]) & (V[:, 0] < BOX["x"][1]) & \
      (V[:, 1] > BOX["y"][0]) & (V[:, 1] < BOX["y"][1]) & \
      (V[:, 2] > BOX["z"][0]) & (V[:, 2] < BOX["z"][1])
print(f"scuttle region: {sel.sum()} verts of {len(V)}")

# feather: weight 1 deep inside, 0 at the border (30mm ramp)
fx = np.minimum(V[:, 0] - BOX["x"][0], BOX["x"][1] - V[:, 0])
fy = np.minimum(V[:, 1] - BOX["y"][0], BOX["y"][1] - V[:, 1])
w = np.clip(np.minimum(fx, fy) / 0.03, 0, 1) * sel

# vertex adjacency from edges
e = cp.edges_unique
nbr = {}
for a, b in e:
    nbr.setdefault(int(a), []).append(int(b))
    nbr.setdefault(int(b), []).append(int(a))
idx = np.where(sel)[0]
orig = V.copy()
# METHOD RECORD (all measured on the same locked cameras):
#   Laplacian, wrong box (y .88-1.15), 8mm  -> 0.948% (null — box missed pool)
#   Laplacian, corrected box,        12mm  -> 0.841%  <- BEST, kept
#   quadric-blend toward fit,        15mm  -> 0.922%  (fit resid p95 69.9mm:
#       the melt sits ~7cm from ANY smooth design surface — a capped spot
#       fix cannot reach it; that is Stage-6 reconstruction territory)
for _ in range(ITERS):
    newV = V.copy()
    for i in idx:
        ns = nbr.get(int(i))
        if not ns:
            continue
        newV[i] = V[i] + w[i] * 0.5 * (V[ns].mean(0) - V[i])
    V = newV
disp = V - orig
d = np.linalg.norm(disp, axis=1)
over = d > CAP
if over.any():
    V[over] = orig[over] + disp[over] * (CAP / d[over])[:, None]
moved = (d > 1e-6).sum()
print(f"relaxed {moved} verts, cap {CAP*1000:.0f}mm, "
      f"mean disp {d[d>1e-6].mean()*1000:.1f}mm, capped {over.sum()}")
cp.vertices = V

out = trimesh.Scene()
for node in sc.graph.nodes_geometry:
    T, gn = sc.graph[node]
    if gn not in out.geometry:
        out.add_geometry(sc.geometry[gn], geom_name=gn, node_name=node, transform=T)
    else:
        out.graph.update(frame_to=node, matrix=T, geometry=gn)
out.export(OUT, include_normals=True)
with open(OUT, "rb") as fh:
    fh.seek(12); ln, _ = struct.unpack("<II", fh.read(8)); j = json.loads(fh.read(ln))
missing = [m.get("name") for m in j["meshes"]
           if any("NORMAL" not in p["attributes"] for p in m["primitives"])]
if missing:
    raise SystemExit(f"REFUSED: NORMAL missing on {missing[:4]}")
import os
print(f"wrote {OUT} ({os.path.getsize(OUT)} bytes)")
