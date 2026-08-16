#!/usr/bin/env python3
"""seg_refine.py — symmetry + zone refinements on projected labels.

Fixes the two defects the label render showed (2026-08-16):
  * one flank's side glass patchy (weak masks in the views that saw it) —
    the car is left/right symmetric, so a body face whose mirror partner is
    glass, in the side-glass height band, becomes glass. Mirror completion
    is applied to wheels the same way.
  * tail-lamp band overshooting across the tailgate — lamps live near the
    body's edges; lamp faces closer than 30% of half-width to the
    centreline revert to body.
Then neighbour-majority smoothing and small-island absorption re-run.

Run: python3 seg_refine.py <canon.glb> <labels.npy> <out_labels.npy>
"""
import sys
import numpy as np
import trimesh
from collections import Counter
from scipy.spatial import cKDTree
import scipy.sparse as sp

GLB, INP, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
BODY, GLASS, WHEEL, LAMP, UNSEEN = 0, 1, 2, 3, 4
NAMES = np.array(["body", "glass", "wheel", "lamp", "interior"])

sc = trimesh.load(GLB, force="scene")
m = trimesh.util.concatenate([g for g in sc.geometry.values()])
cent = m.triangles_center
label = np.load(INP).copy()
F = len(label)

x, y, z = cent[:, 0], cent[:, 1], cent[:, 2]      # glTF: X length, Y up, Z width
yf = (y - y.min()) / (y.max() - y.min())
half_w = max(abs(z.min()), abs(z.max()))
zc = np.abs(z) / half_w                            # 0 centre .. 1 sill

tree = cKDTree(cent)
mir = np.stack([x, y, -z], 1)
d, partner = tree.query(mir, k=1)
ok = d < 0.01 * (x.max() - x.min())                # partner within 1% of length

plab = np.where(ok, label[partner], -1)
# glass completion: symmetric partner says glass, face is body, side-glass band
grow = (label == BODY) & (plab == GLASS) & (yf > 0.42) & (zc > 0.55)
label[grow] = GLASS
# wheel completion
groww = (label == BODY) & (plab == WHEEL) & (yf < 0.5)
label[groww] = WHEEL
# lamp eviction: no lamps near the centreline (tailgate overshoot)
label[(label == LAMP) & (zc < 0.30)] = BODY
print(f"refine: +{int(grow.sum())} glass, +{int(groww.sum())} wheel, "
      f"lamp evicted {int(((label == LAMP) & (zc < 0.30)).sum())}")

adj = m.face_adjacency
neigh = [[] for _ in range(F)]
for a, b in adj:
    neigh[a].append(b); neigh[b].append(a)
for _ in range(4):
    new = label.copy()
    for i in range(F):
        cnt = Counter(label[j] for j in neigh[i]); cnt[label[i]] += 1
        new[i] = cnt.most_common(1)[0][0]
    if (new == label).all():
        break
    label = new
for target in range(5):
    mask = label == target
    if not mask.any():
        continue
    same = mask[adj[:, 0]] & mask[adj[:, 1]]
    g = sp.csr_matrix((np.ones(int(same.sum())), (adj[same, 0], adj[same, 1])), shape=(F, F))
    _, comp = sp.csgraph.connected_components(g + g.T, directed=False)
    comp = comp.copy(); comp[~mask] = -1
    sizes = Counter(comp[mask])
    small = {cid for cid, n in sizes.items() if n < 400}
    if not small:
        continue
    bv = {cid: Counter() for cid in small}
    for a, b in adj:
        ca, cb = comp[a], comp[b]
        if ca in small and cb != ca:
            bv[ca][label[b]] += 1
        if cb in small and ca != cb:
            bv[cb][label[a]] += 1
    for cid, cnt in bv.items():
        if cnt:
            label[comp == cid] = cnt.most_common(1)[0][0]

np.save(OUT, label)
share = {str(NAMES[i]): round(100 * float((label == i).mean()), 2) for i in range(5)}
ext = (label != UNSEEN)
gshare_ext = 100 * float((label == GLASS).sum()) / max(1, int(ext.sum()))
print("face share:", share)
print(f"glass as % of EXTERIOR(seen) faces: {gshare_ext:.2f}")
