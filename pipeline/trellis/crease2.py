#!/usr/bin/env python3
"""crease2.py — crease density at SEVERAL dihedral floors, not just 25 degrees.

WHY THIS EXISTS. `crease_density.py` bands adjacent-face dihedrals in
[25, 150] degrees and divides the summed edge length by the bbox diagonal. That
is scale-free but it is NOT tessellation-free, and the sharpness experiment
compares meshes with very different triangle sizes:

  * a curved but SMOOTH panel tessellated COARSELY has adjacent-face angles
    above 25 degrees and scores as "crease" — it is curvature, not a shut line;
  * the same panel tessellated FINELY has angles below 25 degrees and scores
    as nothing.

So a reconstruction that emits many more, much smaller triangles can lose
crease density purely by getting smoother tessellation, and a coarse or
staircased one can gain it purely by being coarse. Reading one number would
attribute a tessellation change to a sharpness change.

A real shut line, lamp recess or grille slat is a DEEP crease — it stays above
60 degrees no matter how finely the surface around it is sampled, because the
angle is a property of the feature, not of the sampling. Reporting the same
quantity at 25 / 45 / 60 / 90 degree floors makes the two effects separable:
detail lost at every floor is detail genuinely gone; detail lost only at the
25 degree floor is a tessellation difference.

This is EVIDENCE, exactly like crease_density.py, and for the same reason: it
counts sharp geometry, not GOOD geometry. This project has a recorded case of
crease density tripling on a mesh that was a melted blob. The render arbitrates.

Usage:  crease2.py a.obj b.glb ...
"""
import sys

import numpy as np
import trimesh

FLOORS = (25.0, 45.0, 60.0, 90.0)
CEIL = 179.0


def measure(path):
    sc = trimesh.load(path, process=False, force="scene")
    geoms = [g for g in sc.geometry.values()
             if hasattr(g, "faces") and len(g.faces)]
    lo = np.full(3, np.inf)
    hi = np.full(3, -np.inf)
    faces = 0
    area = 0.0
    lengths = {f: 0.0 for f in FLOORS}
    edge_len_all = []
    for g in geoms:
        V = np.asarray(g.vertices)
        if not np.any(V):
            return None                      # Draco placeholder zeros
        lo = np.minimum(lo, V.min(0))
        hi = np.maximum(hi, V.max(0))
        faces += len(g.faces)
        area += float(g.area)
        try:
            ang = np.degrees(np.abs(g.face_adjacency_angles))
            edges = g.face_adjacency_edges
        except Exception:
            continue
        e = V[edges]
        L = np.linalg.norm(e[:, 0] - e[:, 1], axis=1)
        edge_len_all.append(L)
        for f in FLOORS:
            m = (ang >= f) & (ang <= CEIL)
            lengths[f] += float(L[m].sum())
    diag = float(np.linalg.norm(hi - lo))
    if diag <= 0:
        return None
    allL = np.concatenate(edge_len_all) if edge_len_all else np.array([0.0])
    return {"diag": diag, "faces": faces,
            "crease": {f: lengths[f] / diag for f in FLOORS},
            "median_edge_per_diag": float(np.median(allL)) / diag,
            "area_per_diag2": area / (diag * diag)}


if __name__ == "__main__":
    hdr = "  ".join(f"c>={int(f)}d" for f in FLOORS)
    print(f"{'mesh':34s} {hdr}   {'faces':>9s} {'med_edge/diag':>13s}")
    for p in sys.argv[1:]:
        try:
            r = measure(p)
        except Exception as e:
            print(f"  {p.split('/')[-1][:32]:32s} ERROR {type(e).__name__}: {e}")
            continue
        if r is None:
            print(f"  {p.split('/')[-1][:32]:32s} UNREADABLE")
            continue
        cs = "  ".join(f"{r['crease'][f]:7.1f}" for f in FLOORS)
        print(f"  {p.split('/')[-1][:32]:32s} {cs}   {r['faces']:9d} "
              f"{r['median_edge_per_diag']:13.6f}")
