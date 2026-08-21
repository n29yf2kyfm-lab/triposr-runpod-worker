#!/usr/bin/env python3
"""label_islands.py -- the defect, measured on the WELDED surface.

Body_Shell and Interior are NOT two skins.  Measured on car_rebound.glb:
  * exactly ONE Interior face is a duplicate triangle of a Body_Shell face;
  * 23,232 Interior faces have all three vertices EXACTLY coincident with
    Body_Shell vertices, and 92.4% of those share an edge with a Body_Shell
    BOUNDARY edge -- i.e. they sit IN Body_Shell's holes, on its rim.
So the exterior is ONE triangulated surface whose triangles are PARTITIONED
between materials, and the partition is speckled: single triangles across the
bonnet, cowl, roof and A-pillar carry Interior_Plastic (baseColor 0.031,
near-black) instead of carpaint.  That is the dark speckle.

This script welds every mesh into one surface by exact vertex position, builds
face adjacency across mesh boundaries, and reports the size distribution of
same-material connected components -- so a threshold that separates a SPECKLE
from a real trim BAND can be chosen from data rather than picked.
"""
import sys
from collections import defaultdict

import numpy as np
import trimesh

CAR = sys.argv[1] if len(sys.argv) > 1 else "car_rebound.glb"
Q = 1e-7

sc = trimesh.load(CAR, process=False, force="scene")
names = list(sc.geometry.keys())
mats, Vl, Fl, Gl = [], [], [], []
off = 0
for gi, n in enumerate(names):
    m = sc.geometry[n]
    T, _ = sc.graph.get(n)
    v = trimesh.transformations.transform_points(np.asarray(m.vertices, np.float64), T)
    f = np.asarray(m.faces, np.int64)
    Vl.append(v); Fl.append(f + off); Gl.append(np.full(len(f), gi, np.int32))
    off += len(v)
    mats.append(getattr(m.visual.material, "name", f"mat{gi}"))
V = np.vstack(Vl); F = np.vstack(Fl); G = np.concatenate(Gl)
MATN = sorted(set(mats))
MI = np.array([MATN.index(mats[g]) for g in G])
tri = V[F]
A = 0.5 * np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1)
NF = len(F)

# --- weld by exact position, so adjacency crosses mesh boundaries
key = np.round(V / Q).astype(np.int64)
_, inv = np.unique(key, axis=0, return_inverse=True)
W = inv[F]
print(f"welded {len(V)} verts -> {inv.max()+1} unique positions; {NF} faces")

# --- edge -> faces
e = np.sort(np.concatenate([W[:, [0, 1]], W[:, [1, 2]], W[:, [0, 2]]]), axis=1)
fid = np.tile(np.arange(NF), 3)
ordr = np.lexsort((e[:, 1], e[:, 0]))
e = e[ordr]; fid = fid[ordr]
same = np.all(e[1:] == e[:-1], axis=1)
starts = np.nonzero(~same)[0]
bounds = np.concatenate([[0], starts + 1, [len(e)]])
pairs = []
for a, b in zip(bounds[:-1], bounds[1:]):
    if b - a >= 2:
        grp = fid[a:b]
        for i in range(len(grp)):
            for j in range(i + 1, len(grp)):
                pairs.append((grp[i], grp[j]))
pairs = np.array(pairs, np.int64)
print(f"adjacent face pairs across the welded surface: {len(pairs)}")

# --- connected components of SAME-material faces
import scipy.sparse as sp
import scipy.sparse.csgraph as csg
keep = MI[pairs[:, 0]] == MI[pairs[:, 1]]
p = pairs[keep]
gph = sp.coo_matrix((np.ones(len(p)), (p[:, 0], p[:, 1])), shape=(NF, NF))
ncomp, lab = csg.connected_components(gph, directed=False)
print(f"same-material connected components: {ncomp}")

carea = np.bincount(lab, weights=A, minlength=ncomp)
cn = np.bincount(lab, minlength=ncomp)
cmat = np.zeros(ncomp, np.int64)
cmat[lab] = MI

# neighbour material composition across component boundaries
xb = pairs[MI[pairs[:, 0]] != MI[pairs[:, 1]]]
nb = defaultdict(lambda: defaultdict(float))
for a, b in xb:
    nb[lab[a]][MI[b]] += A[b]
    nb[lab[b]][MI[a]] += A[a]

CP = MATN.index("carpaint")
print(f"\ncarpaint material index {CP}; materials {MATN}")
print("\n=== components by material: count, and how many are SMALL islands ===")
for mi, mn in enumerate(MATN):
    sel = np.nonzero(cmat == mi)[0]
    sel = sel[cn[sel] > 0]
    if not len(sel):
        continue
    a = carea[sel]
    print(f"  {mn:18s} comps {len(sel):6d}  total {a.sum():8.4f} m2  "
          f"largest {a.max():8.5f}  median {np.median(a):.7f}")

print("\n=== DARK-material components that are ISLANDS INSIDE PAINT ===")
print("   (area, face count, share of their boundary neighbours that is carpaint)")
DARK = [MATN.index(x) for x in ("Interior_Plastic", "Arch_Liner", "Underbody", "Trim_Black")
        if x in MATN]
rows = []
for ci in np.nonzero(np.isin(cmat, DARK))[0]:
    if cn[ci] == 0:
        continue
    d = nb.get(ci, {})
    tot = sum(d.values())
    frac = d.get(CP, 0.0) / tot if tot > 0 else 0.0
    rows.append((ci, carea[ci], cn[ci], frac, cmat[ci]))
rows.sort(key=lambda r: -r[1])
tot_isl = 0.0
for thr_a, thr_f in [(1e-3, 0.9), (1e-3, 0.75), (3e-3, 0.75), (1e-2, 0.5), (1e9, 0.0)]:
    s = [r for r in rows if r[1] < thr_a and r[3] >= thr_f]
    print(f"   area<{thr_a:g} m2 & carpaint-boundary>={thr_f:.2f}: "
          f"{len(s):6d} components, {sum(r[2] for r in s):7d} faces, "
          f"{sum(r[1] for r in s):.5f} m2")
print("\n   ten largest dark components (these must NOT be touched -- real trim):")
for r in rows[:10]:
    print(f"     {MATN[r[4]]:18s} area {r[1]:.5f} m2  {r[2]:7d} faces  "
          f"carpaint-boundary {r[3]:.2f}")

np.savez_compressed("islands.npz", lab=lab, cmat=cmat, carea=carea, cn=cn,
                    MI=MI, A=A, MATN=np.array(MATN),
                    frac=np.array([nb.get(c, {}).get(CP, 0.0) /
                                   max(sum(nb.get(c, {}).values()), 1e-12)
                                   for c in range(ncomp)]))
print("\nwrote islands.npz")
