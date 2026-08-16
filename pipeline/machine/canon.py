#!/usr/bin/env python3
"""canon.py — canonicalise a generated (camera-space) car mesh.

Pixal3D is pixel-aligned, which means CAMERA space: the car comes out lying
diagonally in its volume (measured 2026-08-15: raw ext 0.909 x 0.528 x 0.915
for a 3/4 input). Everything downstream (seg stack, priors, render rig)
assumes the canonical pose: LENGTH ON X, Y UP, ground at y=0, centred.

Method: oriented bounding box -> axis assignment by extent order (a car is
always length > width > height) -> up-sign by the footprint test (the floor
slab of a car covers more of the XZ footprint than the roof slab, because
floors are flat and full-width while roofs are narrower and curved).
Nose direction is NOT resolved here — it does not affect materials or
gates, and the catalogue orienter (orient_catalogue.py) owns final axis
convention at ship time.

The transform is applied to vertices per geometry IN the scene, so
materials, UVs and textures pass through untouched.

Run: python3 canon.py <in.glb> <out.glb> [--flip-up]
"""
import sys
import numpy as np
import trimesh

INP, OUT = sys.argv[1], sys.argv[2]
FLIP = "--flip-up" in sys.argv

sc = trimesh.load(INP, force="scene")
m = trimesh.util.concatenate([g for g in sc.geometry.values()])
T, ext = trimesh.bounds.oriented_bounds(m)      # T: world -> obb frame
order = np.argsort(ext)[::-1]                   # longest, middle, shortest
# target: longest -> X, middle -> Z (width), shortest -> Y (height)
perm = np.zeros((3, 3))
perm[0, order[0]] = 1                           # X <- longest
perm[2, order[1]] = 1                           # Z <- middle
perm[1, order[2]] = 1                           # Y <- shortest
if np.linalg.det(perm) < 0:
    perm[2] = -perm[2]                          # keep it a rotation
M = np.eye(4)
M[:3, :3] = perm
M = M @ T

pts = trimesh.transform_points(m.vertices, M)
y = pts[:, 1]
lo, hi = np.percentile(y, [2, 98])
h = hi - lo
slab_f = pts[y < lo + 0.06 * h]                 # candidate floor slab
slab_r = pts[y > hi - 0.06 * h]                 # candidate roof slab


def footprint(p):
    if len(p) < 10:
        return 0.0
    return float(np.ptp(p[:, 0]) * np.ptp(p[:, 2]))


up_ok = footprint(slab_f) >= footprint(slab_r)  # floor should be the WIDE slab
if (not up_ok) ^ FLIP:
    R = trimesh.transformations.rotation_matrix(np.pi, [1, 0, 0])
    M = R @ M
    print("up-sign: FLIPPED (floor footprint test)")
else:
    print("up-sign: kept")

pts = trimesh.transform_points(m.vertices, M)
C = np.eye(4)
C[:3, 3] = [-(pts[:, 0].min() + pts[:, 0].max()) / 2,
            -pts[:, 1].min(),
            -(pts[:, 2].min() + pts[:, 2].max()) / 2]
M = C @ M

for gm in sc.geometry.values():
    gm.vertices = trimesh.transform_points(gm.vertices, M)
sc.export(OUT)
m2 = trimesh.util.concatenate([g for g in sc.geometry.values()])
e = m2.extents
print(f"canonical extents L={e[0]:.3f} H={e[1]:.3f} W={e[2]:.3f} "
      f"(expect L>W>H; H/L={e[1]/e[0]:.3f})")
print("wrote", OUT)
