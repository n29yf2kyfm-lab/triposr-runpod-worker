#!/usr/bin/env python3
"""glass_smooth.py — flatten glass-region geometry toward its fitted surface.

Window glass is SMOOTH by nature — a windscreen is a gentle quadric, never
crinkled. On generated meshes the glass area carries the same surface noise
as the panels, and because the material is genuinely transparent the studio
rig turns every noise facet into a mirror shard (the "chrome crinkle" on
the gseg Golf's rear screen). Bilateral filtering helps but cannot reach
the large-amplitude noise there without also chewing panel creases.

So use the label knowledge: for each connected glass region, fit a QUADRIC
height field over the region's plane basis (captures windscreen curvature,
rejects crinkle) and pull every vertex of the region PULL of the way onto
it. Body/wheel/lamp vertices are untouched; shared boundary vertices are
excluded so the glass edge stays sealed to the body.

Run: python3 glass_smooth.py <in.glb> <labels.npy> <out.glb> [pull]
"""
import sys
import numpy as np
import trimesh
import scipy.sparse as sp
from collections import Counter

INP, LAB, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
PULL = float(sys.argv[4]) if len(sys.argv) > 4 else 0.75
GLASS = 1
MIN_REGION = 500

sc = trimesh.load(INP, force="scene")
geoms = list(sc.geometry.items())
verts_l, faces_l, off, spans = [], [], 0, []
for name, gm in geoms:
    verts_l.append(gm.vertices.copy())
    faces_l.append(gm.faces + off)
    spans.append((off, off + len(gm.vertices)))
    off += len(gm.vertices)
V = np.vstack(verts_l)
Fc = np.vstack(faces_l)
label = np.load(LAB)

scale = float(np.ptp(V, axis=0).max())
key = np.round(V / (1e-6 * scale)).astype(np.int64)
_, weld, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
Vw = V[weld].copy()
Fw = inv[Fc]

mw = trimesh.Trimesh(vertices=Vw, faces=Fw, process=False)
adj = mw.face_adjacency
gmask = label == GLASS
same = gmask[adj[:, 0]] & gmask[adj[:, 1]]
g = sp.csr_matrix((np.ones(int(same.sum())), (adj[same, 0], adj[same, 1])),
                  shape=(len(label), len(label)))
_, comp = sp.csgraph.connected_components(g + g.T, directed=False)
comp = comp.copy(); comp[~gmask] = -1

# vertices of non-glass faces: frozen (keeps the glass rim sealed to the body)
nonglass_v = np.zeros(len(Vw), bool)
nonglass_v[Fw[~gmask].ravel()] = True

moved_total = 0
for cid, n in Counter(comp[gmask]).items():
    if n < MIN_REGION:
        continue
    fidx = np.where(comp == cid)[0]
    vids = np.unique(Fw[fidx].ravel())
    vids = vids[~nonglass_v[vids]]
    if len(vids) < 50:
        continue
    P = Vw[vids]
    ctr = P.mean(0)
    _, _, Vt = np.linalg.svd(P - ctr, full_matrices=False)
    b1, b2, nrm = Vt[0], Vt[1], Vt[2]
    u = (P - ctr) @ b1
    v = (P - ctr) @ b2
    h = (P - ctr) @ nrm
    A = np.stack([np.ones_like(u), u, v, u * u, u * v, v * v], 1)
    coef, *_ = np.linalg.lstsq(A, h, rcond=None)
    hfit = A @ coef
    resid = h - hfit
    Vw[vids] -= PULL * resid[:, None] * nrm
    moved_total += len(vids)
    print(f"  region {cid}: {n} faces, {len(vids)} verts, "
          f"noise rms {resid.std()*1000:.2f} -> {(resid.std()*(1-PULL))*1000:.2f} (per-mille)")

print(f"flattened {moved_total} glass verts (pull={PULL})")
Vnew = Vw[inv]
for (name, gm), (a, b) in zip(geoms, spans):
    gm.vertices = Vnew[a:b]
sc.export(OUT)
import os
print("wrote", OUT, os.path.getsize(OUT), "bytes")
