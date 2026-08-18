#!/usr/bin/env python3
"""lamp_recess.py — carve lamp APERTURES into the body under the lens solids.

Why: the view-axis occlusion probe on golf_v37 measured the body shell
standing proud of the shrink-wrapped lens solids — rear outer R 61% of
lens points occluded (median 19mm), front head lens L 77% (median 34mm).
The lens wrap is a smoothed grid; the generator's body has bumps the
smoothing rides over, so locally the shell pokes through the lens. A
bigger stand-off cannot honestly cover 34mm — the lamps would float.

The fix real cars use: the lamp sits in an APERTURE. This stage pushes
body vertices that lie under a lens footprint inward along the local lens
normal until they sit clear below the lens inner skin. The recess is
covered by the lens solid and its perimeter wall; the step at the rim
reads as the lamp's shut line. This is geometry replacement, not
concealment — the aperture is carved, the lens stays a separate solid.

Only INTERIOR grid points define the footprint (the rim ring is excluded)
so the recess never escapes the lens silhouette.

VERDICT (2026-08-18, measured on golf_v37b renders): DO NOT USE. The
recess pulled 1,657 verts (median 25-36mm, max 84mm) and the rear diag
showed cyan body SHARDS torn across both lamps — faces with one pulled
and one unpulled vertex stretch diagonally across the aperture and still
cross the lens band. This is the recorded "vertex-pull DENTS panels"
failure mode from the Golf gap fixes, reproduced. The fix that works is
on the LENS side: the shrink-wrap in rear_lamps4/front_kit now takes an
OUTWARD ENVELOPE of the local body relief instead of the low-pass mean,
so the lens rides on top of the bumps and nothing can poke through by
construction. File kept as evidence so the next agent does not rebuild it.

Run: python3 lamp_recess.py <car.glb> <rear_kit.npz> <front_kit.npz> <out.glb>
"""
import sys
import numpy as np
import trimesh
from scipy.spatial import cKDTree

CAR, REAR, FRONT, OUT = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
LAT = 0.007          # lateral reach of the footprint around a grid point
CLEAR = 0.004        # body target: this far below the lens WRAP surface
# grid shapes by kit tag (outer skin = first half of each solid's vertices)
SHAPES = {"ro": (34, 12), "rh": (20, 10), "lo": (34, 12), "lh": (20, 10),
          "Head_Lens_R": (26, 10), "Head_Lens_L": (26, 10)}
# stand-off + thickness per kit family (rear_lamps4 / front_kit constants)
DEPTH = {"ro": 0.005 + 0.016, "rh": 0.005 + 0.016,
         "lo": 0.005 + 0.016, "lh": 0.005 + 0.016,
         "Head_Lens_R": 0.005 + 0.015, "Head_Lens_L": 0.005 + 0.015}

sc = trimesh.load(CAR, force="scene")
cp_name = [n for n in sc.geometry if "carpaint" in n][0]
cp = sc.geometry[cp_name]
V = cp.vertices.copy()
moved_total = 0

lenses = []
rz = np.load(REAR)
for tag in ("ro", "rh", "lo", "lh"):
    lenses.append((tag, rz[f"{tag}_v"], rz[f"{tag}_f"]))
import json
fz = np.load(FRONT)
for p in json.loads(bytes(fz["manifest"]).decode()):
    if p["name"] in SHAPES:
        lenses.append((p["name"], fz[p["v"]], fz[p["f"]]))

for tag, LV, LF in lenses:
    ny, nx = SHAPES[tag]
    n2 = ny * nx
    m = trimesh.Trimesh(vertices=LV, faces=LF, process=False)
    ov = LV[:n2].reshape(ny, nx, 3)
    on = m.vertex_normals[:n2].reshape(ny, nx, 3)
    # interior grid points only — the rim ring stays untouched so the
    # recess cannot escape the lens silhouette
    P = ov[1:-1, 1:-1].reshape(-1, 3)
    N = on[1:-1, 1:-1].reshape(-1, 3)
    t = cKDTree(P)
    d, idx = t.query(V, k=1)
    cand = d < 0.06
    disp = V[cand] - P[idx[cand]]
    n = N[idx[cand]]
    proj = (disp * n).sum(1)
    lat = np.linalg.norm(disp - proj[:, None] * n, axis=1)
    # target: CLEAR below the wrap surface, which sits DEPTH below outer skin
    target = -(DEPTH[tag] + CLEAR)
    sel = (lat < LAT) & (proj > target)
    if not sel.any():
        print(f"{tag}: nothing to recess")
        continue
    pull = (proj[sel] - target)
    ci = np.where(cand)[0][sel]
    V[ci] -= n[sel] * pull[:, None]
    moved_total += len(ci)
    print(f"{tag}: recessed {len(ci)} body verts, "
          f"median pull {np.median(pull)*1000:.0f}mm max {pull.max()*1000:.0f}mm")

cp.vertices = V
out = trimesh.Scene()
for n_, g in sc.geometry.items():
    out.add_geometry(g, node_name=n_, geom_name=n_)
out.export(OUT)
import os
print(f"total recessed verts {moved_total} -> {OUT} ({os.path.getsize(OUT)} bytes)")
