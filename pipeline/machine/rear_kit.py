#!/usr/bin/env python3
"""rear_kit.py — constructed rear components (the machine's rear rebuild).

The rear third is the last melted zone (v10 review: "rebuild the entire
rear"). Full hatch/bumper re-sculpt is licensed-mesh territory, but the
two components that carry the rear READ are constructible with the same
method that fixed the glass:

  * TAIL LAMP LENSES — one fitted lens pane per corner cluster, built on a
    quadric over the lamp-labeled faces, sitting 10mm proud. Dark red
    gloss: reads as a real lamp unit instead of melted chrome.
  * NUMBER PLATE + FRAME — flat rectangles on a plane fitted to the centre
    tailgate at plate height, 8mm proud. A crisp plate anchors the whole
    rear the way the grille anchors the nose.

Run: python3 rear_kit.py <canon.glb> <labels.npy> <out.npz>
"""
import sys
import numpy as np
import trimesh
from scipy import ndimage

GLB, LAB, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
BODY, GLASS, WHEEL, LAMP, UNSEEN = 0, 1, 2, 3, 4
RASTER = 90
PROUD = 0.022

sc = trimesh.load(GLB, force="scene")
m = trimesh.util.concatenate([g for g in sc.geometry.values()])
cent = m.triangles_center
label = np.load(LAB)
x, y, z = cent[:, 0], cent[:, 1], cent[:, 2]
L0, L1 = x.min(), x.max()
xf = (x - L0) / (L1 - L0)                     # rear = LOW x on this pose
H = y.max() - y.min()


def grid_on_fit(P, extra_dilate=3, offset=PROUD, outdir=None):
    """Fit quadric to points, raster stencil, return (verts, tris)."""
    ctr = P.mean(0)
    _, _, Vt = np.linalg.svd(P - ctr, full_matrices=False)
    b1, b2, nrm = Vt[0], Vt[1], Vt[2]
    if outdir is not None and np.dot(nrm, outdir) < 0:
        nrm = -nrm
    u = (P - ctr) @ b1
    v = (P - ctr) @ b2
    h = (P - ctr) @ nrm
    A = np.stack([np.ones_like(u), u, v, u * u, u * v, v * v], 1)
    coef, *_ = np.linalg.lstsq(A, h, rcond=None)
    lo = np.stack([u, v], 1).min(0); hi = np.stack([u, v], 1).max(0)
    diag = float(np.hypot(*(hi - lo)))
    cell = diag / RASTER
    gw = int(np.ceil((hi[0] - lo[0]) / cell)) + 3
    gh = int(np.ceil((hi[1] - lo[1]) / cell)) + 3
    ras = np.zeros((gh, gw), bool)
    iu = ((u - lo[0]) / cell).astype(int).clip(0, gw - 1)
    iv = ((v - lo[1]) / cell).astype(int).clip(0, gh - 1)
    ras[iv, iu] = True
    ras = ndimage.binary_closing(ras, iterations=4)
    ras = ndimage.binary_fill_holes(ras)
    sm = ndimage.gaussian_filter(ras.astype(np.float32), 1.6) > 0.5
    sm = ndimage.binary_dilation(sm, iterations=extra_dilate)
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
    verts = (ctr + cu[:, None] * b1 + cv[:, None] * b2 + ch[:, None] * nrm
             + offset * nrm)
    fy, fx = np.where(sm)
    q = np.stack([vid[fy, fx], vid[fy, fx + 1],
                  vid[fy + 1, fx + 1], vid[fy + 1, fx]], 1)
    tris = np.concatenate([q[:, [0, 1, 2]], q[:, [0, 2, 3]]])
    return verts, tris


# ---- tail lamp lenses, one per corner cluster
lens_v, lens_f, off = [], [], 0
for sw in (1, -1):
    sel = (label == LAMP) & (xf < 0.25) & (z * sw > 0.2)
    if sel.sum() < 150:
        print(f"tail {sw:+d}: only {int(sel.sum())} lamp faces — skipped")
        continue
    P = cent[sel]
    v_, f_ = grid_on_fit(P, outdir=np.array([-1.0, 0, 0.4 * sw]))
    lens_v.append(v_); lens_f.append(f_ + off); off += len(v_)
    print(f"tail lens {sw:+d}: {int(sel.sum())} lamp faces -> "
          f"{len(v_)} verts / {len(f_)} tris")

# ---- number plate + frame on the centre tailgate
psel = (label == BODY) & (xf < 0.05) & (np.abs(z) < 0.35) & \
       (y > y.min() + 0.18 * H) & (y < y.min() + 0.42 * H)
P = cent[psel]
print(f"plate zone: {int(psel.sum())} body faces")
ctr = P.mean(0)
_, _, Vt = np.linalg.svd(P - ctr, full_matrices=False)
nrm = Vt[2]
if nrm[0] > 0:                                # plate faces -X (rearwards)
    nrm = -nrm
up = np.array([0.0, 1.0, 0.0])
right = np.cross(up, nrm); right /= np.linalg.norm(right)
pup = np.cross(nrm, right)


def rect(w, hh, proud):
    c = ctr + proud * nrm
    p = [c - w/2*right - hh/2*pup, c + w/2*right - hh/2*pup,
         c + w/2*right + hh/2*pup, c - w/2*right + hh/2*pup]
    return np.array(p), np.array([[0, 1, 2], [0, 2, 3]])

frame_v, frame_f = rect(0.60, 0.17, 0.006)
plate_v, plate_f = rect(0.55, 0.125, 0.010)

np.savez(OUT,
         lens_v=np.vstack(lens_v), lens_f=np.vstack(lens_f),
         plate_v=plate_v, plate_f=plate_f,
         frame_v=frame_v, frame_f=frame_f)
print("wrote", OUT)
