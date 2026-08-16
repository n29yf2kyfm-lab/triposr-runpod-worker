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
gmask = label == GLASS

# grouping: PREFER the per-window region ids seg_boundary saves — welded
# connectivity merges the whole greenhouse into one blob (measured: one 51k
# region spanning rear screen + both flanks, quadric rms 117 per-mille).
reg_file = LAB.replace(".npy", "_regions.npy")
import os
if os.path.exists(reg_file):
    comp = np.load(reg_file).astype(np.int64)
    comp[~gmask] = -1
    print(f"grouping by seg_boundary window ids ({reg_file})")
else:
    adj0 = mw.face_adjacency
    same = gmask[adj0[:, 0]] & gmask[adj0[:, 1]]
    g = sp.csr_matrix((np.ones(int(same.sum())), (adj0[same, 0], adj0[same, 1])),
                      shape=(len(label), len(label)))
    _, comp = sp.csgraph.connected_components(g + g.T, directed=False)
    comp = comp.copy(); comp[~gmask] = -1
    print("grouping by welded connectivity (no regions file)")

# vertices of non-glass faces: frozen (keeps the glass rim sealed to the body)
nonglass_v = np.zeros(len(Vw), bool)
nonglass_v[Fw[~gmask].ravel()] = True

fn = mw.face_normals

# A connected "region" can weld SEVERAL windows into one blob (measured on the
# gseg Golf: 51k faces spanning the rear screen and its neighbours, fit rms
# 117 per-mille — one quadric across different windows is garbage and pulling
# toward it makes things WORSE). So: fit; if the residual says "not one
# surface", split the faces by k-means on their NORMALS and recurse.
RMS_OK = 0.030          # absolute units; a real single window fits well under this
RMS_CEIL = 0.050        # a leaf STILL above this is not a window surface: NO pull
MAX_DEPTH = 3


def kmeans2(N):
    d = N @ N.T if len(N) < 3 else None
    i0 = 0
    i1 = int(np.argmin(N @ N[i0]))
    c = np.stack([N[i0], N[i1]])
    for _ in range(12):
        a = (N @ c.T).argmax(1)
        nc = np.stack([N[a == k].mean(0) if (a == k).any() else c[k]
                       for k in range(2)])
        nc /= np.linalg.norm(nc, axis=1, keepdims=True).clip(1e-12)
        if np.allclose(nc, c):
            break
        c = nc
    return a


def region_verts(fidx):
    vids = np.unique(Fw[fidx].ravel())
    return vids[~nonglass_v[vids]]


moved_total = 0
queue = [(np.where(comp == cid)[0], 0) for cid, n in
         Counter(comp[gmask]).items() if n >= MIN_REGION and cid != -1]
while queue:
    fidx, depth = queue.pop()
    vids = region_verts(fidx)
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
    resid = h - A @ coef
    rms = float(resid.std())
    if rms > RMS_OK and depth < MAX_DEPTH and len(fidx) >= 2 * MIN_REGION:
        a = kmeans2(fn[fidx])
        if 0 < int(a.sum()) < len(a):
            print(f"  split {len(fidx)} faces (rms {rms*1000:.1f}) -> "
                  f"{int((a==0).sum())} + {int((a==1).sum())}")
            queue.append((fidx[a == 0], depth + 1))
            queue.append((fidx[a == 1], depth + 1))
            continue
    if rms > RMS_CEIL:
        print(f"  SKIP {len(fidx)} faces: rms {rms*1000:.1f} — not one surface, "
              f"pulling would deform, leaving geometry alone")
        continue
    # taper the pull to zero at the region border: border verts are frozen
    # (sealed to the body), so a full pull one ring in tilts the border faces
    # sharply and they render as dark chips along every window edge (seen on
    # the gseg Golf v5). Ramp over TAPER_RINGS vertex rings instead.
    TAPER_RINGS = 4
    allv = np.unique(Fw[fidx].ravel())
    frozen = set(allv[nonglass_v[allv]].tolist())
    nb = {}
    for tri in Fw[fidx]:
        for a_, b_ in ((0, 1), (1, 2), (2, 0)):
            nb.setdefault(tri[a_], set()).add(tri[b_])
            nb.setdefault(tri[b_], set()).add(tri[a_])
    dist = {v: 0 for v in frozen}
    frontier = set(frozen)
    for ring in range(1, TAPER_RINGS + 1):
        nxt = set()
        for v_ in frontier:
            for w_ in nb.get(v_, ()):
                if w_ not in dist:
                    dist[w_] = ring
                    nxt.add(w_)
        frontier = nxt
    wgt = np.array([min(1.0, dist.get(v_, TAPER_RINGS + 1) / (TAPER_RINGS + 1))
                    for v_ in vids])
    Vw[vids] -= (wgt * PULL)[:, None] * resid[:, None] * nrm
    moved_total += len(vids)
    print(f"  fit {len(fidx)} faces, {len(vids)} verts, "
          f"rms {rms*1000:.2f} -> {rms*(1-PULL)*1000:.2f} (per-mille), tapered")

print(f"flattened {moved_total} glass verts (pull={PULL})")
Vnew = Vw[inv]
for (name, gm), (a, b) in zip(geoms, spans):
    gm.vertices = Vnew[a:b]
sc.export(OUT)
import os
print("wrote", OUT, os.path.getsize(OUT), "bytes")
