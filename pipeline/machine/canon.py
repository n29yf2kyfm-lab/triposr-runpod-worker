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

DIMENSIONS: pass --spec to scale the canonicalised car onto published
figures. This is not cosmetic — measured 2026-08-19 on two different cars
from two unrelated photographs, Pixal comes out systematically TOO TALL:
    Yaris  H/L 0.420 vs 0.389 real  (+8%)
    Golf   H/L 0.381 vs ~0.341 real (+12%)
A bias that reproduces across cars and inputs is a property of the
generator, not of the photograph (square-padding the input moved crease
density 159.1 -> 162.2 and left H/L identical, which is what ruled the
input framing out). So it cannot be fixed by better sourcing, and it CAN be
corrected deterministically once per car from its published length/width/
height. Without --spec the stage only measures and reports, as before.

Run: python3 canon.py <in.glb> <out.glb> [--flip-up] [--spec specs/car.json]
"""
import os
import sys
import numpy as np
import trimesh

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from carspec import CarSpec

INP, OUT = sys.argv[1], sys.argv[2]
FLIP = "--flip-up" in sys.argv
SPEC = None
for _i, _a in enumerate(sys.argv):
    if _a == "--spec":
        SPEC = sys.argv[_i + 1]
spec = CarSpec.empty() if SPEC is None else CarSpec.load(SPEC)

sc = trimesh.load(INP, force="scene")
# bake node transforms before measuring: geometry.values() alone drops them,
# and the OBB would then be computed in a different frame from the vertices
# the transform is applied to (the instance-collapse class, 2026-08-19).
for _node in sc.graph.nodes_geometry:
    _T, _gn = sc.graph[_node]
    if _T is not None and not np.allclose(_T, np.eye(4)):
        sc.geometry[_gn].apply_transform(_T)
        sc.graph.update(frame_to=_node, matrix=np.eye(4), geometry=_gn)
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

m2 = trimesh.util.concatenate([g for g in sc.geometry.values()])
e = m2.extents
print(f"canonical extents L={e[0]:.3f} H={e[1]:.3f} W={e[2]:.3f} "
      f"(expect L>W>H; H/L={e[1]/e[0]:.3f})")

# ---- optional: scale onto published dimensions -------------------------
tgt = {k: spec.dim(k)[0] for k in ("length_m", "height_m", "width_m")}
if any(tgt.values()):
    if not all(tgt.values()):
        raise SystemExit(f"REFUSED: spec must give length_m, height_m AND "
                         f"width_m to scale proportions; got {tgt}")
    # TWO SEPARATE THINGS, and only the second is suspicious:
    #   1. UNIT/SIZE: a generated mesh is normalised (measured L=0.973 here)
    #      while the spec is in metres, so the uniform factor is ~4x. That is
    #      a conversion and may be any magnitude.
    #   2. PROPORTION: after the uniform fit, the residual per-axis stretch is
    #      the generator's shape bias (the ~10% height error). THAT is what a
    #      sane range must bound — a large residual means a units or axis
    #      mix-up, not a bias worth correcting.
    uniform = tgt["length_m"] / e[0]
    resid = np.array([1.0,
                      tgt["height_m"] / (e[1] * uniform),
                      tgt["width_m"] / (e[2] * uniform)])
    if not np.all((resid > 0.65) & (resid < 1.35)):
        raise SystemExit(f"REFUSED: residual proportion correction "
                         f"{np.round(resid,3)} outside +-35% after the uniform "
                         f"fit (x{uniform:.3f}) — check the spec units and the "
                         "axis order")
    s = uniform * resid
    print(f"uniform fit x{uniform:.3f}; residual proportion correction "
          f"H x{resid[1]:.3f} W x{resid[2]:.3f}")
    for gm in sc.geometry.values():
        v = gm.vertices.copy()
        v *= s                       # about the canonical origin: x/z are
        gm.vertices = v              # centred and y sits on the ground
    m3 = trimesh.util.concatenate([g for g in sc.geometry.values()])
    e3 = m3.extents
    print(f"scaled to spec: x{s[0]:.3f} y{s[1]:.3f} z{s[2]:.3f}  -> "
          f"L={e3[0]:.3f} H={e3[1]:.3f} W={e3[2]:.3f} (H/L={e3[1]/e3[0]:.3f})")
    for k, got, want in (("length", e3[0], tgt["length_m"]),
                         ("height", e3[1], tgt["height_m"]),
                         ("width",  e3[2], tgt["width_m"])):
        if abs(got / want - 1) > 0.01:
            raise SystemExit(f"REFUSED: post-scale {k} {got:.4f} vs spec "
                             f"{want} — verification failed")
    print("verified: all three dimensions within 1% of spec")
else:
    print("no spec dimensions supplied — proportions REPORTED, not corrected")

sc.export(OUT, include_normals=True)   # submesh/scene exports drop NORMALs
print("wrote", OUT)
