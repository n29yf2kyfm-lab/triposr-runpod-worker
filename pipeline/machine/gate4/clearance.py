#!/usr/bin/env python3
"""clearance.py — is every lens vertex PROUD of its own side's body surface?

Each unit is measured in the parameterisation it was BUILT in, because a
mismatched parameterisation manufactures a false verdict: v1's radial metric
reported the R hatch "76% buried" and the correct along-+x metric reported it
0% buried at +28 mm median. Recorded so it is not re-paid.

  outer units -> radius about the corner pivot, per side
  hatch units -> x at matched (y, z)

Run: python3 clearance.py <car.glb> <lamps.npz> [out.json]
"""
import json
import sys
import numpy as np
import trimesh
from scipy.spatial import cKDTree

CAR, KIT = sys.argv[1], sys.argv[2]
OUTJ = sys.argv[3] if len(sys.argv) > 3 else None
sc = trimesh.load(CAR, force="scene")
allv = np.vstack([g.vertices for g in sc.geometry.values()])
XMIN, XMAX = float(allv[:, 0].min()), float(allv[:, 0].max())
L = XMAX - XMIN
PIV = np.array([XMAX - 0.55, 0.35])

skin = []
for n in ("carpaint", "interior"):
    g = sc.geometry[n]; c = g.triangles_center
    skin.append(c[c[:, 0] > XMAX - 0.42 * L])
SK = np.vstack(skin)
kit = np.load(KIT)
res = {}

for side in ("R", "L"):
    s = 1.0 if side == "R" else -1.0
    P = SK[SK[:, 2] * s > 0].copy(); P[:, 2] *= s        # that side, mirrored to +z
    ang = np.degrees(np.arctan2(P[:, 2] - PIV[1], P[:, 0] - PIV[0]))
    rad = np.hypot(P[:, 0] - PIV[0], P[:, 2] - PIV[1])
    tree_yz = cKDTree(P[:, 1:3])

    V = kit[f"{side}O_v"].copy(); V[:, 2] *= s
    va = np.degrees(np.arctan2(V[:, 2] - PIV[1], V[:, 0] - PIV[0]))
    vr = np.hypot(V[:, 0] - PIV[0], V[:, 2] - PIV[1])
    cl = []
    for k in range(len(V)):
        m = (np.abs(ang - va[k]) < 2.5) & (np.abs(P[:, 1] - V[k, 1]) < 0.020)
        if m.sum() >= 8:
            cl.append(vr[k] - np.percentile(rad[m], 99))
    cl = np.array(cl)
    res[f"{side}O"] = dict(n=len(cl), median_mm=float(1000 * np.median(cl)),
                           p05_mm=float(1000 * np.percentile(cl, 5)),
                           buried_pct=float(100 * np.mean(cl < 0)))

    Vh = kit[f"{side}H_v"].copy(); Vh[:, 2] *= s
    d, idx = tree_yz.query(Vh[:, 1:3], k=60, distance_upper_bound=0.05)
    ch = []
    for k in range(len(Vh)):
        ii = idx[k][np.isfinite(d[k])]
        if len(ii) >= 10:
            ch.append(Vh[k, 0] - np.percentile(P[ii, 0], 99))
    ch = np.array(ch)
    res[f"{side}H"] = dict(n=len(ch), median_mm=float(1000 * np.median(ch)),
                           p05_mm=float(1000 * np.percentile(ch, 5)),
                           buried_pct=float(100 * np.mean(ch < 0)))

print("LENS CLEARANCE vs its own side's surface (+ = proud):")
worst = 0.0
for k in ("RO", "RH", "LO", "LH"):
    v = res[k]
    print(f"  {k}: n={v['n']:4d}  median {v['median_mm']:+6.0f}mm  "
          f"p05 {v['p05_mm']:+6.0f}mm  buried {v['buried_pct']:.0f}%")
    worst = max(worst, v["buried_pct"])
res["worst_buried_pct"] = worst
if OUTJ:
    json.dump(res, open(OUTJ, "w"), indent=1)
print(f"worst buried fraction: {worst:.0f}%")
