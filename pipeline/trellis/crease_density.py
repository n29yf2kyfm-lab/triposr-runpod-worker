#!/usr/bin/env python3
"""crease_density.py — does a mesh actually CONTAIN shut lines and hard edges?

Written 2026-08-14 to test the premise the whole fine-tune plan rests on. The
plan says "fine-tune on our 1,026 audited cars so the model learns crisp panels
and shut lines". That is only possible if OUR CARS HAVE THEM. Training on soft
meshes teaches softness, and nobody had measured whether the catalogue carries
the signal at all — the exact "gate nobody tested" failure this project keeps
paying for.

METRIC. A shut line, a panel gap, a lamp recess edge — all are CREASES: pairs of
adjacent faces meeting at a real angle. A melted surface has none; its adjacent
faces are nearly coplanar. So:

    crease_density = (total length of edges whose dihedral angle is in
                      [MIN_DEG, MAX_DEG]) / bounding-box diagonal

Dividing by the diagonal makes it scale-free, so a 4 m car and a unit-normalised
generated mesh compare directly. The upper bound excludes near-180-degree
degenerate pairs (zero-area slivers) which are noise, not detail.

WHAT IT CANNOT DO, stated up front so it is not over-read: it counts sharp
geometry, not GOOD geometry. A noisy scan scores high for the wrong reason
(which is exactly what it shows for Hi3DGen). Read it alongside the render,
never instead of it — same rule as every other numeric gate here.

HOW BADLY? MEASURED 2026-08-21, so this stops being a warning to be remembered
and becomes a number to reckon with. Same 25/150 band, synthetic controls:

    smooth icosphere (20k faces)         crease/diag =   0.0
    + gaussian vertex noise amp 0.001    crease/diag =   0.0
    + gaussian vertex noise amp 0.003    crease/diag =   7.1
    + gaussian vertex noise amp 0.010    crease/diag = 201.3
    cube — twelve GENUINE sharp creases  crease/diag =   6.9

PURE NOISE ON A SPHERE SCORES 201.3 — about 29x a cube's twelve real edges, and
in the same range as a real catalogue car (the Sportage NQ5 measures 270.7). So a
HIGH crease density is NOT evidence of panel features; it is equally consistent
with a surface that is merely rough and has none. This is the documented
43 -> 132 "3x gain" on a melted blob, quantified.

PRACTICAL READING: a LOW score is informative (nothing sharp is there). A HIGH
score is nearly uninformative on its own. The render decides. Density also
depends on tessellation, so treat these as order-of-magnitude controls, not a
conversion table.

Usage:
  crease_density.py a.glb b.glb ...
"""
import sys

import numpy as np
import trimesh

MIN_DEG, MAX_DEG = 25.0, 150.0


def measure(path):
    sc = trimesh.load(path, process=False, force="scene")
    geoms = list(sc.geometry.values()) if hasattr(sc, "geometry") else [sc]
    tot_crease = 0.0
    tot_area = 0.0
    tot_faces = 0
    lo = np.full(3, np.inf)
    hi = np.full(3, -np.inf)
    for g in geoms:
        if not hasattr(g, "faces") or len(g.faces) == 0:
            continue
        V = np.asarray(g.vertices)
        if not np.any(V):          # Draco placeholder zeros — never measure them
            return None
        lo = np.minimum(lo, V.min(0)); hi = np.maximum(hi, V.max(0))
        tot_faces += len(g.faces)
        tot_area += float(g.area)
        try:
            ang = np.degrees(np.abs(g.face_adjacency_angles))
            edges = g.face_adjacency_edges
        except Exception:
            continue
        m = (ang >= MIN_DEG) & (ang <= MAX_DEG)
        if m.sum():
            e = V[edges[m]]
            tot_crease += float(np.linalg.norm(e[:, 0] - e[:, 1], axis=1).sum())
    diag = float(np.linalg.norm(hi - lo))
    if diag <= 0:
        return None
    return {"crease_per_diag": tot_crease / diag, "faces": tot_faces,
            "area_per_diag2": tot_area / (diag * diag), "diag": diag}


if __name__ == "__main__":
    print(f"{'mesh':28s} {'CREASE/diag':>12s} {'faces':>10s} {'diag':>8s}")
    for p in sys.argv[1:]:
        try:
            r = measure(p)
        except Exception as e:
            print(f"  {p.split('/')[-1][:26]:26s} ERROR {type(e).__name__}")
            continue
        if r is None:
            print(f"  {p.split('/')[-1][:26]:26s} UNREADABLE (draco/zero verts)")
            continue
        print(f"  {p.split('/')[-1][:26]:26s} {r['crease_per_diag']:12.1f} "
              f"{r['faces']:10d} {r['diag']:8.2f}")
