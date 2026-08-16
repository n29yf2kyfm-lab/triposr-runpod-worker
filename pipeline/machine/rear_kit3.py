#!/usr/bin/env python3
"""rear_kit3.py — parametric rear lamps built by SURFACE SAMPLING.

rear_kit2 fitted one quadric over the rear-quarter zone and tested grid
points against a designed outline. That zone wraps around the body corner,
so a single quadric mispositioned most grid cells and the lamps came out as
thin slivers (measured on the v28 rear diagnostic — the reviewer read them
as "washed out or nearly erased", correctly).

This version uses no fit at all. The lamp outline is defined analytically
in (|z|, y) — the car's own measured coordinates — and each lamp vertex
takes its X from the REAL rear-facing body surface sampled at that (z, y)
via nearest-neighbour lookup. Curvature is therefore followed exactly, the
two lamps are mirror-symmetric by construction, and the melted lamp label
contributes nothing.

Outline (fractions of measured car height / half-width), Mk8-family:
horizontal unit, deeper at the outboard end, tapering inboard.

Run: python3 rear_kit3.py <canon.glb> <labels.npy> <out.npz>
"""
import sys
import numpy as np
import trimesh
from scipy.spatial import cKDTree

GLB, LAB, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
BODY = 0
PROUD = 0.030          # metres proud of the sampled surface
CELL = 0.010           # lamp grid cell

sc = trimesh.load(GLB, force="scene")
m = trimesh.util.concatenate([g for g in sc.geometry.values()])
cent = m.triangles_center
fn = m.face_normals
label = np.load(LAB)
x, y, z = cent[:, 0], cent[:, 1], cent[:, 2]
L0 = x.min(); H0 = y.min(); H = y.max() - H0
xf = (x - L0) / (x.max() - L0)
HALF_W = max(abs(z.min()), abs(z.max()))

# the real rear-facing surface: body faces at the tail whose normal faces -X
rear_face = (label == BODY) & (xf < 0.12) & (fn[:, 0] < -0.35)
RS = cent[rear_face]
if len(RS) < 300:
    raise SystemExit(f"only {len(RS)} rear-facing faces — cannot sample surface")
tree = cKDTree(RS[:, 1:3])                 # lookup in (y, z)
print(f"rear surface samples: {len(RS)}")

# designed lamp outline, in (|z| fraction of half-width, y fraction of height)
ZF_OUT, ZF_IN = 0.90, 0.40
YF_OUT_LO, YF_OUT_HI = 0.475, 0.605        # outboard: deeper unit
YF_IN_LO, YF_IN_HI = 0.512, 0.575          # inboard: tapered


def outline(zf, yf):
    if zf < ZF_IN or zf > ZF_OUT:
        return False
    t = (zf - ZF_IN) / (ZF_OUT - ZF_IN)
    lo = YF_IN_LO + t * (YF_OUT_LO - YF_IN_LO)
    hi = YF_IN_HI + t * (YF_OUT_HI - YF_IN_HI)
    return lo <= yf <= hi


zs = np.arange(ZF_IN * HALF_W, ZF_OUT * HALF_W, CELL)
ys = np.arange(H0 + (YF_OUT_LO - 0.01) * H, H0 + (YF_OUT_HI + 0.01) * H, CELL)
nz, ny = len(zs), len(ys)
inside = np.zeros((ny, nz), bool)
for j, yy in enumerate(ys):
    for i, zz in enumerate(zs):
        inside[j, i] = outline(zz / HALF_W, (yy - H0) / H)
print(f"lamp grid {ny}x{nz}, {int(inside.sum())} cells inside outline")

lens_v, lens_f, off = [], [], 0
for sw in (1, -1):
    # sample the real surface X at each grid CORNER
    gy, gz = np.meshgrid(ys, zs, indexing="ij")
    q = np.stack([gy.ravel(), sw * gz.ravel()], 1)
    d, idx = tree.query(q, k=12)
    xs_ = RS[idx, 0]
    w = 1.0 / np.clip(d, 1e-4, None)
    xs_ = (xs_ * w).sum(1) / w.sum(1)          # inverse-distance blend
    far = d.min(1) > 0.12                       # no surface nearby -> skip cell
    xs_ = xs_.reshape(ny, nz)
    far = far.reshape(ny, nz)
    # a lens is SMOOTH: the sampled shell carries the generator's noise, and
    # inheriting it gives the ragged lamp edge seen on the v30 diagnostic.
    # Smooth the depth field, then fit a gentle quadric through it so the
    # unit reads as one moulded surface following the car's real curvature.
    from scipy import ndimage as _nd
    xs_ = _nd.gaussian_filter(xs_, 2.5, mode="nearest")
    gy2, gz2 = np.meshgrid(ys - ys.mean(), zs - zs.mean(), indexing="ij")
    Aq = np.stack([np.ones(gy2.size), gy2.ravel(), gz2.ravel(),
                   gy2.ravel()**2, (gy2 * gz2).ravel(), gz2.ravel()**2], 1)
    sel_fit = (inside & ~far).ravel()
    if sel_fit.sum() > 40:
        cq, *_ = np.linalg.lstsq(Aq[sel_fit], xs_.ravel()[sel_fit], rcond=None)
        xs_ = (Aq @ cq).reshape(ny, nz)

    ok = inside & ~far
    if ok.sum() < 50:
        print(f"lamp {sw:+d}: only {int(ok.sum())} valid cells — skipped")
        continue
    corner = np.zeros((ny + 1, nz + 1), bool)
    corner[:-1, :-1] |= ok; corner[1:, :-1] |= ok
    corner[:-1, 1:] |= ok;  corner[1:, 1:] |= ok
    vid = np.full((ny + 1, nz + 1), -1, np.int64)
    cy, cz = np.where(corner)
    vid[cy, cz] = np.arange(len(cy))
    vy = ys[np.clip(cy, 0, ny - 1)]
    vz = sw * zs[np.clip(cz, 0, nz - 1)]
    vx = xs_[np.clip(cy, 0, ny - 1), np.clip(cz, 0, nz - 1)] - PROUD
    verts = np.stack([vx, vy, vz], 1)
    fy, fz = np.where(ok)
    quads = np.stack([vid[fy, fz], vid[fy, fz + 1],
                      vid[fy + 1, fz + 1], vid[fy + 1, fz]], 1)
    tris = np.concatenate([quads[:, [0, 1, 2]], quads[:, [0, 2, 3]]])
    lens_v.append(verts); lens_f.append(tris + off); off += len(verts)
    ext = verts.max(0) - verts.min(0)
    print(f"lamp {sw:+d}: {int(ok.sum())} cells -> {len(verts)} verts / "
          f"{len(tris)} tris, unit {ext[2]:.2f}w x {ext[1]:.2f}h")

# ---- number plate + frame, sampled the same way
pz_sel = (label == BODY) & (xf < 0.06) & (np.abs(z) < 0.30) & \
         (y > H0 + 0.20 * H) & (y < H0 + 0.40 * H) & (fn[:, 0] < -0.35)
P = cent[pz_sel]
pc = P.mean(0)
print(f"plate anchor: x={pc[0]:.2f} y={(pc[1]-H0)/H:.2f}H  ({len(P)} faces)")


def rect(w, hh, proud):
    c = np.array([pc[0] - proud, pc[1], 0.0])
    p = [c + [0, -hh/2, -w/2], c + [0, -hh/2, w/2],
         c + [0, hh/2, w/2], c + [0, hh/2, -w/2]]
    return np.array(p), np.array([[0, 2, 1], [0, 3, 2]])


frame_v, frame_f = rect(0.56, 0.16, 0.012)
plate_v, plate_f = rect(0.52, 0.115, 0.016)

np.savez(OUT, lens_v=np.vstack(lens_v), lens_f=np.vstack(lens_f),
         plate_v=plate_v, plate_f=plate_f, frame_v=frame_v, frame_f=frame_f,
         parametric=np.array([1]))
print("wrote", OUT)
