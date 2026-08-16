#!/usr/bin/env python3
"""rear_kit2.py — PARAMETRIC rear lamps (designed, not detected).

The rear clay diagnostic proved the lamp LABEL is a ragged asymmetric blob
— any lens fitted over it inherits the damage (the rejected v26 pass). So
the lamps are now DESIGNED: two mirror-symmetric wedge units placed from
the car's measured dimensions, conformed to the local body surface by a
quadric fit. The label contributes nothing; symmetry is by construction.

Each unit: horizontal wedge, taller at the outboard edge (the Mk8-family
signature), 15mm proud of the fitted surface, with soft corners.

Also emits the number plate + frame (unchanged from rear_kit).

Run: python3 rear_kit2.py <canon.glb> <labels.npy> <out.npz>
"""
import sys
import numpy as np
import trimesh
from scipy import ndimage

GLB, LAB, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
BODY = 0
RASTER_CELL = 0.012           # metres-ish per cell
PROUD = 0.038

sc = trimesh.load(GLB, force="scene")
m = trimesh.util.concatenate([g for g in sc.geometry.values()])
cent = m.triangles_center
label = np.load(LAB)
x, y, z = cent[:, 0], cent[:, 1], cent[:, 2]
L0 = x.min()
xf = (x - L0) / (x.max() - L0)                # rear = LOW x
H0 = y.min(); H = y.max() - H0

# designed lamp outline in (|z|, y): outboard edge tall, inboard tapered
Z_OUT, Z_IN = 0.93, 0.42
Y_OUT_LO, Y_OUT_HI = H0 + 0.505 * H, H0 + 0.605 * H
Y_IN_LO, Y_IN_HI = H0 + 0.525 * H, H0 + 0.585 * H


def inside_wedge(az, ay):
    if az < Z_IN or az > Z_OUT:
        return False
    t = (az - Z_IN) / (Z_OUT - Z_IN)
    lo = Y_IN_LO + t * (Y_OUT_LO - Y_IN_LO)
    hi = Y_IN_HI + t * (Y_OUT_HI - Y_IN_HI)
    return lo <= ay <= hi


lens_v, lens_f, off = [], [], 0
for sw in (1, -1):
    zone = ((label == BODY) & (xf < 0.10) & (z * sw > 0.30) &
            (y > H0 + 0.42 * H) & (y < H0 + 0.68 * H))
    P = cent[zone]
    if len(P) < 200:
        print(f"lamp {sw:+d}: only {len(P)} surface faces — skipped")
        continue
    ctr = P.mean(0)
    _, _, Vt = np.linalg.svd(P - ctr, full_matrices=False)
    b1, b2, nrm = Vt[0], Vt[1], Vt[2]
    outd = np.array([-1.0, 0, 0.35 * sw])
    if np.dot(nrm, outd) < 0:
        nrm = -nrm
    u = (P - ctr) @ b1
    v = (P - ctr) @ b2
    h = (P - ctr) @ nrm
    A = np.stack([np.ones_like(u), u, v, u * u, u * v, v * v], 1)
    coef, *_ = np.linalg.lstsq(A, h, rcond=None)
    lo = np.stack([u, v], 1).min(0) - 0.05
    hi = np.stack([u, v], 1).max(0) + 0.05
    gw = int(np.ceil((hi[0] - lo[0]) / RASTER_CELL)) + 2
    gh = int(np.ceil((hi[1] - lo[1]) / RASTER_CELL)) + 2

    # world position of every cell centre via the fit, then the DESIGNED test
    cu, cv = np.meshgrid(lo[0] + np.arange(gw) * RASTER_CELL,
                         lo[1] + np.arange(gh) * RASTER_CELL)
    ch = (coef[0] + coef[1] * cu + coef[2] * cv + coef[3] * cu * cu +
          coef[4] * cu * cv + coef[5] * cv * cv)
    W = (ctr[None, None, :] + cu[..., None] * b1 + cv[..., None] * b2 +
         ch[..., None] * nrm)
    sm = np.zeros((gh, gw), bool)
    for j in range(gh):
        for i in range(gw):
            w = W[j, i]
            sm[j, i] = inside_wedge(w[2] * sw, w[1])
    sm = ndimage.gaussian_filter(sm.astype(np.float32), 1.2) > 0.45  # soft corners
    if not sm.any():
        print(f"lamp {sw:+d}: designed outline missed the surface — check dims")
        continue

    corner = np.zeros((gh + 1, gw + 1), bool)
    corner[:-1, :-1] |= sm; corner[1:, :-1] |= sm
    corner[:-1, 1:] |= sm;  corner[1:, 1:] |= sm
    vid = np.full((gh + 1, gw + 1), -1, np.int64)
    cy, cx = np.where(corner)
    vid[cy, cx] = np.arange(len(cy))
    gu = lo[0] + cx * RASTER_CELL
    gv = lo[1] + cy * RASTER_CELL
    gh_ = (coef[0] + coef[1] * gu + coef[2] * gv + coef[3] * gu * gu +
           coef[4] * gu * gv + coef[5] * gv * gv)
    verts = ctr + gu[:, None] * b1 + gv[:, None] * b2 + gh_[:, None] * nrm \
        + PROUD * nrm
    fy, fx = np.where(sm)
    q = np.stack([vid[fy, fx], vid[fy, fx + 1],
                  vid[fy + 1, fx + 1], vid[fy + 1, fx]], 1)
    tris = np.concatenate([q[:, [0, 1, 2]], q[:, [0, 2, 3]]])
    lens_v.append(verts); lens_f.append(tris + off); off += len(verts)
    print(f"lamp {sw:+d}: designed wedge -> {len(verts)} verts / {len(tris)} tris")

# ---- number plate + frame (same recipe as rear_kit)
psel = (label == BODY) & (xf < 0.05) & (np.abs(z) < 0.35) & \
       (y > H0 + 0.18 * H) & (y < H0 + 0.42 * H)
P = cent[psel]
ctr = P.mean(0)
_, _, Vt = np.linalg.svd(P - ctr, full_matrices=False)
nrm = Vt[2]
if nrm[0] > 0:
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

np.savez(OUT, lens_v=np.vstack(lens_v), lens_f=np.vstack(lens_f),
         plate_v=plate_v, plate_f=plate_f, frame_v=frame_v, frame_f=frame_f,
         parametric=np.array([1]))
print("wrote", OUT)
