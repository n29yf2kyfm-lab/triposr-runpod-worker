#!/usr/bin/env python3
"""despike.py — remove antenna-class spike artefacts from a generated shell.

Every generator this project has tested grows thin spikes (the roof "fin"
on the Pixal Golf, flagged in every review round). They are not antennas:
they are reconstruction noise — a few dozen faces on a long thin stalk far
outside the local surface.

Detection is local, not global: a vertex is a spike if its displacement
along the local surface normal exceeds SPIKE_H, measured against the
median of its neighbourhood. Spike vertices are PULLED BACK onto the local
surface (not deleted — deleting holes a watertight shell, the wheel_swap
lesson), so the roof stays sealed by construction.

Run: python3 despike.py <in.glb> <out.glb> [spike_h] [radius]
"""
import sys
import numpy as np
import trimesh
from scipy.spatial import cKDTree

INP, OUT = sys.argv[1], sys.argv[2]
SPIKE_H = float(sys.argv[3]) if len(sys.argv) > 3 else 0.030   # metres
RADIUS = float(sys.argv[4]) if len(sys.argv) > 4 else 0.070

sc = trimesh.load(INP, force="scene")
geoms = list(sc.geometry.items())
verts_l, off, spans = [], 0, []
for name, gm in geoms:
    verts_l.append(gm.vertices.copy())
    spans.append((off, off + len(gm.vertices)))
    off += len(gm.vertices)
V = np.vstack(verts_l)

tree = cKDTree(V)
nbrs = tree.query_ball_point(V, RADIUS)
disp = np.zeros(len(V))
target = V.copy()
for i, nb in enumerate(nbrs):
    if len(nb) < 8:
        continue
    P = V[nb]
    c = P.mean(0)
    # local plane by SVD; distance of this vertex from it
    _, _, Vt = np.linalg.svd(P - c, full_matrices=False)
    n = Vt[2]
    d = float((V[i] - c) @ n)
    med = float(np.median((P - c) @ n))
    disp[i] = abs(d - med)
    if abs(d - med) > SPIKE_H:
        target[i] = V[i] - (d - med) * n            # pull back to the surface

hits = disp > SPIKE_H
print(f"{len(V)} verts, spike threshold {SPIKE_H*1000:.0f}mm: "
      f"{int(hits.sum())} spike verts pulled back "
      f"(max displacement {disp.max()*1000:.0f}mm)")
if hits.any():
    hz = V[hits]
    print(f"  spike zone: x {hz[:,0].min():.2f}..{hz[:,0].max():.2f}  "
          f"y {hz[:,1].min():.2f}..{hz[:,1].max():.2f}  "
          f"z {hz[:,2].min():.2f}..{hz[:,2].max():.2f}")

for (name, gm), (a, b) in zip(geoms, spans):
    gm.vertices = target[a:b]
sc.export(OUT)
import os
print("wrote", OUT, os.path.getsize(OUT), "bytes")
