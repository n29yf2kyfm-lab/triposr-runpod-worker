#!/usr/bin/env python3
"""verify_lamps.py — are Gate 4's lamp solids still PROUD of the REBUILT skin?

Gate 4 replaced this gate's surface, so its own 0%-buried result had to be
re-established against the NEW skin.

A PROBE I BUILT AND THEN DISCARDED, recorded because it cost a wrong verdict:
v1 measured every unit along +x against a 97th-percentile of nearby body face
centres. Run as a CONTROL on Gate 4's untouched file it reported the OUTER
units 66.8% and 76.2% BURIED -- on a file Gate 4 measured at 0%. That is
exactly the artefact Gate 4 documents ("the wrong parameterisation manufactures
a false verdict"): a corner-WRAP unit's outward direction is lateral, not +x,
so at |z| = 0.85 the body at matched (y,z) is legitimately far behind it. The
control is the only reason this was caught rather than reported.

What is measured now:
  HATCH units (LH/RH) -- inboard, tail-facing, and they sit on the REBUILT
      panel. Clearance = lens x minus the panel's OWN fitted surface at that
      (y, z), read from the same coverage raster the strip used. Exact, not a
      percentile of scattered melt points.
  OUTER units (LO/RO) -- they sit on the rear QUARTERS, which this gate does
      not rebuild. Their seating is unchanged BY CONSTRUCTION and that is
      asserted from geometry, not assumed: both the lens and the quarter
      vertices must still be 100% coincident with the source.

Run: python3 verify_lamps.py <source.glb> <out.glb> <out.json>
"""
import json, sys
import numpy as np, trimesh
from scipy.spatial import cKDTree

SRC, NEW, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
d = np.load("build/panels.npz")
NV, NU = int(d["NV"]), int(d["NU"])
HVo = d["HVo"]
tree = cKDTree(HVo[..., 1:3].reshape(-1, 2))
XP = HVo[..., 0].ravel()

ssc = trimesh.load(SRC, force="scene", process=False)
nsc = trimesh.load(NEW, force="scene", process=False)
SV = np.vstack([g.vertices for g in ssc.geometry.values()])
stree = cKDTree(SV)
rep = {}
for u in ("Tail_Lens_LH", "Tail_Lens_RH"):
    V = nsc.geometry[u].vertices
    dd, ii = tree.query(V[:, 1:3], k=4)
    w = 1.0 / np.maximum(dd, 1e-6); w /= w.sum(1, keepdims=True)
    xs = (XP[ii] * w).sum(1)
    near = dd[:, 0] < 0.020
    cl = (V[:, 0] - xs)[near]
    rep[u] = {"n": int(len(V)), "on_panel": int(near.sum()),
              "buried_pct": round(float((cl < 0).mean() * 100), 2),
              "clear_p05_mm": round(float(np.percentile(cl, 5) * 1000), 2),
              "clear_median_mm": round(float(np.median(cl) * 1000), 2),
              "clear_min_mm": round(float(cl.min() * 1000), 2)}
    print(u, rep[u])
for u in ("Tail_Lens_LO", "Tail_Lens_RO", "Rear_Quarter_L", "Rear_Quarter_R"):
    V = nsc.geometry[u].vertices
    dd, _ = stree.query(V, k=1)
    rep[u] = {"verts": int(len(V)),
              "coincident_with_source_pct": round(float((dd < 1e-4).mean() * 100), 3),
              "max_displacement_micron": round(float(dd.max() * 1e6), 3)}
    print(u, rep[u])
json.dump(rep, open(OUT, "w"), indent=1)
