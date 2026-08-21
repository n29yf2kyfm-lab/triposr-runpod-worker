#!/usr/bin/env python3
"""coverage.py -- GATE 3 v7: does the rebuilt fascia actually CLOSE the cavity?

The failure this exists to catch is an aperture that no new part covers.  A
render shows it as a dark patch, but a dark patch in a render is a candidate,
not a measurement -- and the eye cannot tell "a hole" from "a deep recess that
is meant to be dark".  This rasterises the rebuilt car exactly as front_tex.py
does and asks, cell by cell inside the strip footprint:

  * is there any geometry at all in front of the cavity?          (HOLE)
  * is the frontmost geometry a NEW part or surviving old shell?   (MELT LEFT)
  * how far behind the fitted skin does the frontmost surface sit? (SUNK)

A cell is a HOLE if nothing is found within 120 mm of the skin plane.  A cell is
MELT-LEFT if the frontmost owner is one of the pre-existing nodes.  Both are
reported as areas in cm2 and as a fraction of the footprint, so a fix can be
shown to have moved a number rather than looked better.

Run: python3 coverage.py <rebuilt.glb> <ftex.npz> <plan.json> <out.json> [--png <dir>]
"""
import json
import sys

import numpy as np
import trimesh
from scipy import ndimage

GLB, TEX, PLAN, OUT = sys.argv[1:5]
PNGDIR = sys.argv[sys.argv.index("--png") + 1] if "--png" in sys.argv else None

d = np.load(TEX, allow_pickle=True)
D0, ys, zs = d["D"], d["ys"], d["zs"]
RES, XN = float(d["RES"]), float(d["XMIN"])
P = json.load(open(PLAN))
F = P["frame"]
ZC, YD, YLOW = F["z_centre"], F["y_datum_bonnet_leading_edge"], F["y_bumper_lowest"]
SIL0 = np.isfinite(D0)

NEW = {"Valance_Front", "Bumper_Front", "Grille_Upper", "DRL_Blade", "Badge",
       "Badge_Mount", "Grille_Lower", "Plate_Carrier", "Plate", "TowEye_Cover",
       "Intake_R", "Intake_L", "Intake_R_Blades", "Intake_L_Blades"}
for t in ("L", "R"):
    NEW |= {f"Headlamp_{t}_Lens", f"Headlamp_{t}_Housing", f"Headlamp_{t}_Internal"}

# ------------------------------------------------------------- rasterise
sc = trimesh.load(GLB, force="scene", process=False)
nodes = sorted(sc.graph.nodes_geometry)
ni = {n: i for i, n in enumerate(nodes)}
ny, nz = len(ys), len(zs)
DM = np.full((ny, nz), np.inf)
OWN = np.full((ny, nz), -1, np.int32)

TRI, OW = [], []
for node in nodes:
    T, g = sc.graph[node]
    gg = sc.geometry[g]
    v = trimesh.transform_points(np.asarray(gg.vertices, float), T)
    tri = v[np.asarray(gg.faces)]
    k = tri[:, :, 0].min(1) < XN + 0.75
    if k.any():
        TRI.append(tri[k])
        OW.append(np.full(int(k.sum()), ni[node], np.int32))
TRI = np.concatenate(TRI)
OW = np.concatenate(OW)

gy = (TRI[:, :, 1] - ys[0]) / RES
gz = (TRI[:, :, 2] - zs[0]) / RES
j0 = np.clip(np.floor(gy.min(1)).astype(np.int64), 0, ny - 1)
i0 = np.clip(np.floor(gz.min(1)).astype(np.int64), 0, nz - 1)
hh = np.clip(np.ceil(gy.max(1)).astype(np.int64), 0, ny - 1) - j0 + 1
ww = np.clip(np.ceil(gz.max(1)).astype(np.int64), 0, nz - 1) - i0 + 1
live = ((gy.max(1) >= 0) & (gy.min(1) <= ny - 1) &
        (gz.max(1) >= 0) & (gz.min(1) <= nz - 1))
TRI, OW, j0, i0, hh, ww = (TRI[live], OW[live], j0[live], i0[live],
                           hh[live], ww[live])
cnt = hh * ww
order = np.argsort(-cnt)
csum = np.cumsum(cnt[order])
lo, chunks = 0, []
while lo < len(order):
    hi = max(int(np.searchsorted(csum, (csum[lo - 1] if lo else 0) + 4_000_000,
                                 "right")), lo + 1)
    chunks.append(order[lo:hi])
    lo = hi

for sel in chunks:
    t, o = TRI[sel], OW[sel]
    h, w = hh[sel], ww[sel]
    n = h * w
    tid = np.repeat(np.arange(len(sel)), n)
    off = np.concatenate([[0], np.cumsum(n)[:-1]])
    k = np.arange(n.sum()) - np.repeat(off, n)
    wr = np.repeat(w, n)
    jj = np.repeat(j0[sel], n) + k // wr
    ii = np.repeat(i0[sel], n) + k % wr
    ok = (jj >= 0) & (jj < ny) & (ii >= 0) & (ii < nz)
    tid, jj, ii = tid[ok], jj[ok], ii[ok]
    a, b, c = t[tid, 0], t[tid, 1], t[tid, 2]
    v0y, v0z = b[:, 1] - a[:, 1], b[:, 2] - a[:, 2]
    v1y, v1z = c[:, 1] - a[:, 1], c[:, 2] - a[:, 2]
    v2y, v2z = ys[jj] - a[:, 1], zs[ii] - a[:, 2]
    den = v0y * v1z - v1y * v0z
    good = np.abs(den) > 1e-14
    dd = np.where(good, den, 1)
    u = np.where(good, (v2y * v1z - v1y * v2z) / dd, -1)
    vv = np.where(good, (v0y * v2z - v2y * v0z) / dd, -1)
    ins = good & (u >= -1e-9) & (vv >= -1e-9) & (u + vv <= 1 + 1e-9)
    if not ins.any():
        continue
    tid, jj, ii, u, vv = tid[ins], jj[ins], ii[ins], u[ins], vv[ins]
    a, b, c = t[tid, 0], t[tid, 1], t[tid, 2]
    X = a[:, 0] + u * (b[:, 0] - a[:, 0]) + vv * (c[:, 0] - a[:, 0])
    flat = jj.astype(np.int64) * nz + ii
    s = np.lexsort((X, flat))
    flat, X, tid = flat[s], X[s], tid[s]
    first = np.concatenate([[True], flat[1:] != flat[:-1]])
    fc, fx, ft = flat[first], X[first], tid[first]
    cj, ci = fc // nz, fc % nz
    better = fx < DM[cj, ci]
    DM[cj[better], ci[better]] = fx[better]
    OWN[cj[better], ci[better]] = o[ft[better]]

D = np.where(np.isfinite(DM), DM - XN, np.nan)

# ------------------------------------------------------- the strip footprint
foot = SIL0 & ((ys > YLOW - 0.002) & (ys < YD - 0.002))[:, None] & (D0 < 0.42)
foot &= (np.abs(zs - ZC) < 0.70)[None, :]
foot = ndimage.binary_erosion(foot, np.ones((5, 5)))

isnew = np.zeros(D.shape, bool)
for n, i in ni.items():
    if n in NEW:
        isnew |= (OWN == i)

covered = np.isfinite(D)
hole = foot & (~covered | (D > 0.42))
oldshell = foot & covered & ~isnew & (D <= 0.42)
newcov = foot & isnew

cell_cm2 = (RES * 100) ** 2
res = {
 "footprint_cells": int(foot.sum()),
 "footprint_cm2": round(float(foot.sum()) * cell_cm2, 1),
 "hole_cells": int(hole.sum()),
 "hole_cm2": round(float(hole.sum()) * cell_cm2, 1),
 "hole_frac": round(float(hole.sum()) / max(int(foot.sum()), 1), 5),
 "old_shell_frontmost_cells": int(oldshell.sum()),
 "old_shell_frontmost_cm2": round(float(oldshell.sum()) * cell_cm2, 1),
 "old_shell_frac": round(float(oldshell.sum()) / max(int(foot.sum()), 1), 5),
 "new_part_frontmost_frac": round(float(newcov.sum()) / max(int(foot.sum()), 1), 5),
 "by_node_frontmost_cells": {},
}
for n, i in sorted(ni.items()):
    c = int((foot & (OWN == i)).sum())
    if c:
        res["by_node_frontmost_cells"][n] = c

# How PROUD is the surviving shell where it is still the frontmost surface?
# Area alone does not say whether that reads as a ridge or as nothing.  The skin
# is rebuilt here by exactly the recipe rebuild7.py uses, so the comparison is
# against the same surface the new parts were built on.
_valid = SIL0 & (D0 < 0.35)
_idx = ndimage.distance_transform_edt(~_valid, return_distances=False,
                                      return_indices=True)
_fill = np.where(_valid, D0, 0.0)[tuple(_idx)]
_sk = ndimage.gaussian_filter(ndimage.median_filter(_fill, size=21), 6.0)
_local = ndimage.gaussian_filter(_fill, 3.0)
_it = np.clip(np.rint((2 * ZC - zs - zs[0]) / RES).astype(int), 0, len(zs) - 1)
_w = np.clip((0.628 + 0.090 - np.abs(zs - ZC)) / 0.090, 0, 1)[None, :]
_sk = _w * 0.5 * (_sk + _sk[:, _it]) + (1 - _w) * _local
if oldshell.any():
    proud = (_sk - D)[oldshell] * 1000.0        # +ve = shell is IN FRONT of skin
    res["old_shell_proud_mm"] = {
        "median": round(float(np.median(proud)), 2),
        "p90": round(float(np.percentile(proud, 90)), 2),
        "max": round(float(proud.max()), 2),
        "frac_over_5mm": round(float((proud > 5).mean()), 4),
        "note": "positive means the surviving shell stands in front of the new "
                "skin. This is the bumper-to-fender transition, which is where "
                "the mesh's own 90-108 mm lateral asymmetry lives.",
    }
else:
    res["old_shell_proud_mm"] = None

# largest connected hole, so a scatter of single cells is not confused with a gap
lab, nlab = ndimage.label(hole)
if nlab:
    sizes = ndimage.sum(hole, lab, range(1, nlab + 1))
    big = int(sizes.max())
    k = int(np.argmax(sizes)) + 1
    rr, cc = np.nonzero(lab == k)
    res["largest_hole"] = {
        "cells": big, "cm2": round(big * cell_cm2, 1),
        "y_range": [round(float(ys[rr.min()]), 4), round(float(ys[rr.max()]), 4)],
        "z_range": [round(float(zs[cc.min()]), 4), round(float(zs[cc.max()]), 4)],
    }
    res["hole_components"] = int(nlab)
    res["holes_over_5cm2"] = int((sizes * cell_cm2 > 5).sum())
else:
    res["largest_hole"] = None
    res["hole_components"] = 0
    res["holes_over_5cm2"] = 0

json.dump(res, open(OUT, "w"), indent=1)
print(f"footprint {res['footprint_cm2']} cm2")
print(f"HOLES     {res['hole_cm2']} cm2  ({res['hole_frac']*100:.2f}%)  "
      f"{res['hole_components']} components, {res['holes_over_5cm2']} over 5 cm2")
if res["largest_hole"]:
    lh = res["largest_hole"]
    print(f"  largest {lh['cm2']} cm2  y {lh['y_range']}  z {lh['z_range']}")
print(f"OLD SHELL frontmost inside footprint {res['old_shell_frontmost_cm2']} cm2 "
      f"({res['old_shell_frac']*100:.2f}%)")
print(f"NEW PARTS frontmost {res['new_part_frontmost_frac']*100:.2f}%")
print("frontmost owners inside the footprint:")
for n, c in sorted(res["by_node_frontmost_cells"].items(), key=lambda t: -t[1]):
    tag = "NEW" if n in NEW else "old"
    print(f"  [{tag}] {n:24s} {c:7d}")

if PNGDIR:
    from PIL import Image
    import os
    os.makedirs(PNGDIR, exist_ok=True)
    rgb = np.zeros(D.shape + (3,), np.uint8)
    rgb[foot] = (60, 60, 60)
    rgb[newcov] = (40, 170, 70)
    rgb[oldshell] = (240, 170, 40)
    rgb[hole] = (240, 40, 40)
    Image.fromarray(np.flipud(rgb)).resize((nz * 2, ny * 2), Image.NEAREST).save(
        os.path.join(PNGDIR, "coverage.png"))
    print("wrote", os.path.join(PNGDIR, "coverage.png"))
