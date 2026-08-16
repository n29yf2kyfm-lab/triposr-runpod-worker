#!/usr/bin/env python3
"""seg_boundary.py — straighten glass label boundaries with per-region 2D stencils.

The agent eye and the human eye both flagged the same #1 defect on the gseg
Golf: ragged, crinkled glass borders. The cause is that labels are per-FACE
and the Pixal triangulation does not follow the DLO, so the projected-vote
boundary dithers along the window edge. The fix is the pattern that already
beat boundary dither once (the 2026-08-13 glazing-tighten session): a 2D
STENCIL. Per connected glass region:

  1. fit a plane to the region's face centroids (SVD),
  2. rasterise the region into that plane at ~1/220 of its diagonal,
  3. morphological close -> fill holes -> gaussian smooth -> re-threshold,
     giving one clean smooth outline,
  4. re-stamp every candidate face (thin band around the plane, normal
     aligned, inside the expanded 2D bbox) from the raster.

Glass is then EXHAUSTIVE: any glass face outside every stamped region
reverts to body. That single rule also deletes the stray chrome smears
(tailgate band, cowl spill) — they are exactly "glass labels that belong to
no window plane".

Run: python3 seg_boundary.py <canon.glb> <labels.npy> <out_labels.npy>
"""
import sys
import numpy as np
import trimesh
import scipy.sparse as sp
from scipy import ndimage
from collections import Counter

GLB, INP, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
BODY, GLASS, WHEEL, LAMP, UNSEEN = 0, 1, 2, 3, 4

sc = trimesh.load(GLB, force="scene")
m = trimesh.util.concatenate([g for g in sc.geometry.values()])
cent = m.triangles_center
fnorm = m.face_normals
label = np.load(INP).copy()
F = len(label)
adj = m.face_adjacency

MIN_REGION = 800          # faces; smaller glass regions are noise -> body
BAND_FRAC = 0.030         # stencil band half-thickness, fraction of region diag
RASTER = 220              # cells across the region diagonal
GAUSS_SIGMA = 2.2         # cells; the smoothing that straightens the outline

mask = label == GLASS
same = mask[adj[:, 0]] & mask[adj[:, 1]]
g = sp.csr_matrix((np.ones(int(same.sum())), (adj[same, 0], adj[same, 1])),
                  shape=(F, F))
_, comp = sp.csgraph.connected_components(g + g.T, directed=False)
comp = comp.copy(); comp[~mask] = -1
sizes = Counter(comp[mask])
regions = [cid for cid, n in sizes.items() if n >= MIN_REGION]
print(f"glass regions >= {MIN_REGION} faces: {len(regions)} "
      f"(of {len(sizes)} total, {int(mask.sum())} glass faces)")

stamped_glass = np.zeros(F, bool)
for cid in regions:
    ridx = np.where(comp == cid)[0]
    pts = cent[ridx]
    ctr = pts.mean(0)
    _, _, Vt = np.linalg.svd(pts - ctr, full_matrices=False)
    b1, b2, nrm = Vt[0], Vt[1], Vt[2]
    uv_r = (pts - ctr) @ np.stack([b1, b2], 1)
    diag = float(np.hypot(*(uv_r.max(0) - uv_r.min(0))))
    band = BAND_FRAC * diag

    d_all = (cent - ctr) @ nrm
    nd_all = np.abs(fnorm @ nrm)
    uv_all = (cent - ctr) @ np.stack([b1, b2], 1)
    lo, hi = uv_r.min(0) - 0.06 * diag, uv_r.max(0) + 0.06 * diag
    cand = ((np.abs(d_all) < band) & (nd_all > 0.5) &
            (uv_all[:, 0] > lo[0]) & (uv_all[:, 0] < hi[0]) &
            (uv_all[:, 1] > lo[1]) & (uv_all[:, 1] < hi[1]) &
            np.isin(label, (BODY, GLASS)))

    cell = diag / RASTER
    gw = int(np.ceil((hi[0] - lo[0]) / cell)) + 1
    gh = int(np.ceil((hi[1] - lo[1]) / cell)) + 1
    ras = np.zeros((gh, gw), bool)
    iu = ((uv_r[:, 0] - lo[0]) / cell).astype(int).clip(0, gw - 1)
    iv = ((uv_r[:, 1] - lo[1]) / cell).astype(int).clip(0, gh - 1)
    ras[iv, iu] = True
    ras = ndimage.binary_closing(ras, iterations=3)
    ras = ndimage.binary_fill_holes(ras)
    sm = ndimage.gaussian_filter(ras.astype(np.float32), GAUSS_SIGMA) > 0.5

    ci = np.where(cand)[0]
    cu = ((uv_all[ci, 0] - lo[0]) / cell).astype(int).clip(0, gw - 1)
    cv = ((uv_all[ci, 1] - lo[1]) / cell).astype(int).clip(0, gh - 1)
    inside = sm[cv, cu]
    label[ci[inside]] = GLASS
    stamped_glass[ci[inside]] = True
    out_idx = ci[~inside]           # outside this stencil: revert glass -> body,
    flip = out_idx[(label[out_idx] == GLASS) & ~stamped_glass[out_idx]]
    label[flip] = BODY              # unless another region already stamped it
    print(f"  region {cid}: {len(ridx)} faces, diag {diag:.3f}, "
          f"stamped {int(inside.sum())} in / {int((~inside).sum())} out")

# glass is exhaustive: anything still glass but never stamped is a smear
stray = (label == GLASS) & ~stamped_glass
label[stray] = BODY
print(f"stray glass reverted to body: {int(stray.sum())}")

# lamp hygiene: real lamps live in the OUTER thirds. Measured on the gseg
# Golf v2: 13,364 lamp faces spanned the tailgate as a full-width band
# (DINO's "tail light" boxes over-shoot), and the dark-gloss lens material
# renders that band as mirror chrome. Evict centre-span lamp label to body —
# the baked texture carries the real lamp graphics there anyway.
z = cent[:, 2]
half_w = max(abs(z.min()), abs(z.max()))
zc = np.abs(z) / half_w
lamp_mid = (label == LAMP) & (zc < 0.45)
label[lamp_mid] = BODY
print(f"lamp centre-band evicted to body: {int(lamp_mid.sum())}")

# absorb crumbs the restamp left behind (single scan per label)
for target in range(5):
    tm = label == target
    if not tm.any():
        continue
    same = tm[adj[:, 0]] & tm[adj[:, 1]]
    g = sp.csr_matrix((np.ones(int(same.sum())), (adj[same, 0], adj[same, 1])),
                      shape=(F, F))
    _, comp2 = sp.csgraph.connected_components(g + g.T, directed=False)
    comp2 = comp2.copy(); comp2[~tm] = -1
    sizes2 = Counter(comp2[tm])
    small = {cid for cid, n in sizes2.items() if n < 400}
    if not small:
        continue
    bv = {cid: Counter() for cid in small}
    for a, b in adj:
        ca, cb = comp2[a], comp2[b]
        if ca in small and cb != ca:
            bv[ca][label[b]] += 1
        if cb in small and ca != cb:
            bv[cb][label[a]] += 1
    for cid, cnt in bv.items():
        if cnt:
            label[comp2 == cid] = cnt.most_common(1)[0][0]

np.save(OUT, label)
NAMES = ["body", "glass", "wheel", "lamp", "interior"]
share = {NAMES[i]: round(100 * float((label == i).mean()), 2) for i in range(5)}
print("face share:", share)
