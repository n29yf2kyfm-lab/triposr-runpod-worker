#!/usr/bin/env python3
"""glass_panes.py — CONSTRUCT glazing as clean geometry (component rebuild).

The v10 review is right: relabeled neural-blob faces have hit their limit —
crinkled glass geometry reflects the studio as shattered mirror no matter
how transparent the material is. But the machine already KNOWS each window:
seg_boundary stamped a per-window region and outline, and glass_smooth fits
a quadric surface per window that lands at real-glass residuals (2-5 per
mille). So stop repairing the blob: EMIT a fresh, regular grid mesh on each
window's fitted quadric, clipped to its smoothed stencil outline. The
original glass faces are then dropped at assembly (assemble2.py) — the
panes replace them entirely, the dark interior stays behind them.

Output: <out.npz> holding pane vertices/faces, plus per-face region ids.

Run: python3 glass_panes.py <canon.glb> <labels.npy> <regions.npy> <out.npz>
"""
import sys
import numpy as np
import trimesh
from scipy import ndimage

GLB, LAB, REG, OUT = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
GLASS, UNSEEN, BODY = 1, 4, 0
RASTER = 160          # cells across the region diagonal (pane grid resolution)
GAUSS_SIGMA = 2.2
OFFSET = 0.012        # push the pane OUTBOARD: the fit sits inboard of the
                      # blob surface, and inner-skin interior fragments poke
                      # through as white dots (measured, v10 left flank)
SHELL_OUT = 0.03      # interior faces from 3cm outside the pane surface...
SHELL_IN = 0.10       # ...to 10cm inside it are floating skin/junk: against
                      # the dark occluder every lit fragment reads as a white
                      # dot on the glass (measured v11/v12) — purge the band

sc = trimesh.load(GLB, force="scene")
m = trimesh.util.concatenate([g for g in sc.geometry.values()])
cent = m.triangles_center
label = np.load(LAB)
region = np.load(REG)
int_idx = np.where(label == UNSEEN)[0]
body_idx = np.where(label == BODY)[0]
drop = np.zeros(len(label), bool)
body_cand = np.zeros(len(label), bool)   # floating chips in the aperture —
                                         # assemble2 keeps only those in small
                                         # components (the surround ring is
                                         # connected to the shell and survives)

# MERGE overlapping regions first — the boundary stencils overlap, so one
# physical window can carry several region ids, and building a pane per id
# STACKS offset quadric sheets that intersect: grazing transmission through
# the stack blooms as white dots (the v10-v16 saga; bisection-proven — the
# left flank carried FOUR stacked panes, the clean right flank one).
rids = [r for r in sorted(set(region[region >= 0].tolist()))
        if (region == r).sum() >= 300]
info = {}
for r in rids:
    fi = np.where((region == r) & (label == GLASS))[0]
    if len(fi) < 300:
        continue
    P = cent[fi]
    c_ = P.mean(0)
    _, _, Vt_ = np.linalg.svd(P - c_, full_matrices=False)
    info[r] = (fi, c_, Vt_[2], P.min(0), P.max(0))
parent = {r: r for r in info}
def find(r):
    while parent[r] != r:
        parent[r] = parent[parent[r]]; r = parent[r]
    return r
for i, ra in enumerate(list(info)):
    for rb in list(info)[i + 1:]:
        fa, ca, na, loa, hia = info[ra]
        fb, cb, nb, lob, hib = info[rb]
        if abs(np.dot(na, nb)) < 0.80:
            continue
        ov = np.minimum(hia, hib) - np.maximum(loa, lob)
        if (ov > 0).all():                      # 3D bboxes overlap
            parent[find(ra)] = find(rb)
groups = {}
for r in info:
    groups.setdefault(find(r), []).append(r)
print(f"{len(info)} regions -> {len(groups)} merged windows")

all_v, all_f, all_r, off = [], [], [], 0
for gid, members in sorted(groups.items()):
    fidx = np.concatenate([info[r][0] for r in members])
    rid = gid
    # surface fit on the region's face centroids (same maths as glass_smooth)
    P = cent[fidx]
    ctr = P.mean(0)
    _, _, Vt = np.linalg.svd(P - ctr, full_matrices=False)
    b1, b2, nrm = Vt[0], Vt[1], Vt[2]
    u = (P - ctr) @ b1
    v = (P - ctr) @ b2
    h = (P - ctr) @ nrm
    A = np.stack([np.ones_like(u), u, v, u * u, u * v, v * v], 1)
    coef, *_ = np.linalg.lstsq(A, h, rcond=None)

    # stencil raster of the window outline (seg_boundary's recipe)
    lo = np.stack([u, v], 1).min(0)
    hi = np.stack([u, v], 1).max(0)
    diag = float(np.hypot(*(hi - lo)))
    cell = diag / RASTER
    gw = int(np.ceil((hi[0] - lo[0]) / cell)) + 3
    gh = int(np.ceil((hi[1] - lo[1]) / cell)) + 3
    ras = np.zeros((gh, gw), bool)
    iu = ((u - lo[0]) / cell).astype(int).clip(0, gw - 1)
    iv = ((v - lo[1]) / cell).astype(int).clip(0, gh - 1)
    ras[iv, iu] = True
    ras = ndimage.binary_closing(ras, iterations=3)
    ras = ndimage.binary_fill_holes(ras)
    sm = ndimage.gaussian_filter(ras.astype(np.float32), GAUSS_SIGMA) > 0.5
    # DILATE two cells: the pane must tuck BEHIND the body aperture edge.
    # (v10 first cut eroded instead — that left a visible gap ring around
    # every window, the review's "black cracks" defect, self-inflicted.)
    sm = ndimage.binary_dilation(sm, iterations=4)

    # grid vertices at cell corners where any adjacent cell is inside
    corner = np.zeros((gh + 1, gw + 1), bool)
    corner[:-1, :-1] |= sm; corner[1:, :-1] |= sm
    corner[:-1, 1:] |= sm;  corner[1:, 1:] |= sm
    vid = np.full((gh + 1, gw + 1), -1, np.int64)
    cy, cx = np.where(corner)
    vid[cy, cx] = np.arange(len(cy))
    cu = lo[0] + cx * cell
    cv = lo[1] + cy * cell
    ch = (coef[0] + coef[1] * cu + coef[2] * cv +
          coef[3] * cu * cu + coef[4] * cu * cv + coef[5] * cv * cv)
    verts = ctr + cu[:, None] * b1 + cv[:, None] * b2 + ch[:, None] * nrm

    # outward = away from the car's centre, so the pane covers stray skin
    outward = nrm if np.dot(nrm, ctr - cent.mean(0)) >= 0 else -nrm
    verts = verts + OFFSET * outward

    fy, fx = np.where(sm)
    q = np.stack([vid[fy, fx], vid[fy, fx + 1],
                  vid[fy + 1, fx + 1], vid[fy + 1, fx]], 1)
    tris = np.concatenate([q[:, [0, 1, 2]], q[:, [0, 2, 3]]])
    all_v.append(verts)
    all_f.append(tris + off)
    all_r.append(np.full(len(tris), rid))
    off += len(verts)

    # flag inner-skin interior fragments inside this window's shell
    ic = cent[int_idx]
    iu = (ic - ctr) @ b1
    iv2 = (ic - ctr) @ b2
    ih = (ic - ctr) @ nrm
    ihfit = (coef[0] + coef[1] * iu + coef[2] * iv2 +
             coef[3] * iu * iu + coef[4] * iu * iv2 + coef[5] * iv2 * iv2)
    d_ = ih - ihfit
    if np.dot(nrm, ctr - cent.mean(0)) < 0:
        d_ = -d_                            # sign so positive = outboard
    inb = ((iu > lo[0]) & (iu < hi[0]) & (iv2 > lo[1]) & (iv2 < hi[1]) &
           (d_ < SHELL_OUT) & (d_ > -SHELL_IN))
    ci2 = int_idx[inb]
    cu2 = ((iu[inb] - lo[0]) / cell).astype(int).clip(0, gw - 1)
    cv2 = ((iv2[inb] - lo[1]) / cell).astype(int).clip(0, gh - 1)
    hit = sm[cv2, cu2]
    drop[ci2[hit]] = True

    # BODY chips floating in the aperture: seg_boundary flips out-of-stencil
    # glass to body, and on the weak-mask flank those are debris hovering in
    # the window that the respray paints — the white dots (CENSUS-confirmed:
    # 8,644 small-component body faces in the left side window vs 3,568
    # right). Footprint eroded 5% so the surround ring is never flagged.
    bc = cent[body_idx]
    bu = (bc - ctr) @ b1
    bv = (bc - ctr) @ b2
    bh = (bc - ctr) @ nrm
    bhfit = (coef[0] + coef[1] * bu + coef[2] * bv +
             coef[3] * bu * bu + coef[4] * bu * bv + coef[5] * bv * bv)
    bd = bh - bhfit
    if np.dot(nrm, ctr - cent.mean(0)) < 0:
        bd = -bd
    mx, my = 0.09 * (hi[0] - lo[0]), 0.09 * (hi[1] - lo[1])
    binb = ((bu > lo[0] + mx) & (bu < hi[0] - mx) &
            (bv > lo[1] + my) & (bv < hi[1] - my) &
            (np.abs(bd) < 0.04))
    ci3 = body_idx[binb]
    cu3 = ((bu[binb] - lo[0]) / cell).astype(int).clip(0, gw - 1)
    cv3 = ((bv[binb] - lo[1]) / cell).astype(int).clip(0, gh - 1)
    body_cand[ci3[sm[cv3, cu3]]] = True
    print(f"pane {rid}: {len(fidx)} blob faces -> {len(verts)} verts / "
          f"{len(tris)} clean tris, diag {diag:.2f}, "
          f"inner-skin flagged {int(hit.sum())}")

V = np.vstack(all_v); F = np.vstack(all_f); R = np.concatenate(all_r)
np.savez(OUT, vertices=V, faces=F, region=R, drop=np.where(drop)[0],
         body_cand=np.where(body_cand)[0])
print(f"panes: {len(V)} verts, {len(F)} tris total, "
      f"{int(drop.sum())} inner-skin + {int(body_cand.sum())} body-chip "
      f"candidates flagged -> {OUT}")
