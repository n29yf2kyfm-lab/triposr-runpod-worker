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
GLASS = 1
RASTER = 160          # cells across the region diagonal (pane grid resolution)
GAUSS_SIGMA = 2.2

sc = trimesh.load(GLB, force="scene")
m = trimesh.util.concatenate([g for g in sc.geometry.values()])
cent = m.triangles_center
label = np.load(LAB)
region = np.load(REG)

all_v, all_f, all_r, off = [], [], [], 0
for rid in sorted(set(region[region >= 0].tolist())):
    fidx = np.where((region == rid) & (label == GLASS))[0]
    if len(fidx) < 300:
        continue
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
    sm = ndimage.binary_dilation(sm, iterations=2)

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

    fy, fx = np.where(sm)
    q = np.stack([vid[fy, fx], vid[fy, fx + 1],
                  vid[fy + 1, fx + 1], vid[fy + 1, fx]], 1)
    tris = np.concatenate([q[:, [0, 1, 2]], q[:, [0, 2, 3]]])
    all_v.append(verts)
    all_f.append(tris + off)
    all_r.append(np.full(len(tris), rid))
    off += len(verts)
    print(f"pane {rid}: {len(fidx)} blob faces -> {len(verts)} verts / "
          f"{len(tris)} clean tris, diag {diag:.2f}")

V = np.vstack(all_v); F = np.vstack(all_f); R = np.concatenate(all_r)
np.savez(OUT, vertices=V, faces=F, region=R)
print(f"panes: {len(V)} verts, {len(F)} tris total -> {OUT}")
