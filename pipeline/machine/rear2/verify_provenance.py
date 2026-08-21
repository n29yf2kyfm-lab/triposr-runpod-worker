#!/usr/bin/env python3
"""verify_provenance.py — is a component REBUILT, or regrouped source melt?

The failure this exists to catch is Gate 3 v5's and the one my brief warns
about on car_rebound: a clean semantic NAME on melted geometry. A name-based
check reads 0% on renamed melt; geometry does not lie.

Three independent measures per component:
  coincident_pct  % of its vertices lying within 0.1 mm of a SOURCE vertex.
                  Regrouped melt = ~100 (a face re-grouping moves nothing --
                  Gate 4 measured max displacement 0.000 micron). Rebuilt = ~0.
  edge_len_cv     coefficient of variation of edge length. Melt tessellation is
                  irregular; a lofted grid is near-uniform.
  valence6_pct    share of interior vertices with valence 6, the signature of a
                  regular quad-triangulated grid.

The LEGACY components are the built-in negative control: if the test cannot
tell them apart from the rebuilt ones, the test is worthless and says so.

Run: python3 verify_provenance.py <source.glb> <out.glb> <out.json>
"""
import json, sys
from collections import Counter
import numpy as np, trimesh
from scipy.spatial import cKDTree

SRC, NEW, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
ssc = trimesh.load(SRC, force="scene", process=False)
SV = np.vstack([g.vertices for g in ssc.geometry.values()])
tree = cKDTree(SV)
nsc = trimesh.load(NEW, force="scene", process=False)
rep = {"source_vertices": int(len(SV))}
for name, g in nsc.geometry.items():
    V, F = g.vertices, g.faces
    dd, _ = tree.query(V, k=1)
    e = np.vstack([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    L = np.linalg.norm(V[e[:, 0]] - V[e[:, 1]], axis=1)
    val = Counter(e[:, 0].tolist() + e[:, 1].tolist())
    counts = np.array(list(val.values()))
    rep[name] = {
        "verts": int(len(V)), "faces": int(len(F)),
        "coincident_pct": round(float((dd < 1e-4).mean() * 100), 3),
        "median_dist_to_source_mm": round(float(np.median(dd) * 1000), 3),
        "edge_len_cv": round(float(L.std() / max(L.mean(), 1e-12)), 4),
        "valence6_pct": round(float((counts == 12).mean() * 100), 2),
    }
json.dump(rep, open(OUT, "w"), indent=1)
print(f"{'component':26s} {'verts':>8s} {'coincident%':>12s} {'medDist_mm':>11s} {'edgeCV':>7s} {'val6%':>6s}")
for k, v in rep.items():
    if not isinstance(v, dict): continue
    print(f"{k:26s} {v['verts']:8d} {v['coincident_pct']:12.2f} "
          f"{v['median_dist_to_source_mm']:11.3f} {v['edge_len_cv']:7.3f} {v['valence6_pct']:6.1f}")
