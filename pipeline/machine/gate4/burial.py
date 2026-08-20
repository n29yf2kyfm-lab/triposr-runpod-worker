#!/usr/bin/env python3
"""burial.py — is each lens solid PROUD of the body, or buried inside it?

HYPOTHESIS: the lens solids are buried in the body, and asymmetrically,
because they were built on the +z side and mirrored onto a -z side that is
measurably wider.

WHAT WOULD FALSIFY IT (written before building the probe): burial near zero on
both sides. That would mean the lenses are proud and the near-invisibility in
the matID has some other cause -- z-fighting, a wrong material assignment, or
the camera. The probe reports a signed clearance per lens, so either outcome
is visible.

Clearance is measured as (lens |z| or lens x) minus the BODY's outer surface at
the same place, using a local (x,y) neighbourhood of body skin points. No face
normals are used (46% are flipped in this band) and no material name selects
the body (the rear bumper lives in `interior`).

Run: python3 burial.py <car.glb> <lamps.npz>
"""
import sys
import numpy as np
import trimesh
from scipy.spatial import cKDTree

CAR, KIT = sys.argv[1], sys.argv[2]
sc = trimesh.load(CAR, force="scene")
allv = np.vstack([g.vertices for g in sc.geometry.values()])
XMAX = float(allv[:, 0].max()); XMIN = float(allv[:, 0].min()); L = XMAX - XMIN

skin = []
for n in ("carpaint", "interior"):
    g = sc.geometry[n]; c = g.triangles_center
    skin.append(c[c[:, 0] > XMAX - 0.42 * L])
SK = np.vstack(skin)

# ---- L/R body asymmetry in the lamp band, matched at the same (x, y) ----
band = SK[(SK[:, 1] > 0.75) & (SK[:, 1] < 0.96)]
print("BODY HALF-WIDTH by side in the lamp band (p99 of |z| per x-slice):")
print("   x      +z      -z     diff")
asym = []
for x0 in np.arange(1.45, 2.10, 0.05):
    m = (band[:, 0] >= x0) & (band[:, 0] < x0 + 0.05)
    p = band[m & (band[:, 2] > 0), 2]
    q = -band[m & (band[:, 2] < 0), 2]
    if len(p) > 30 and len(q) > 30:
        a, b = np.percentile(p, 99), np.percentile(q, 99)
        asym.append(b - a)
        print(f"  {x0:.2f}   {a:.3f}   {b:.3f}   {b-a:+.3f}")
print(f"  mean -z minus +z = {np.mean(asym):+.3f} m  "
      f"({100*np.mean(asym)/L:.2f}% of car length)")

# ---- clearance per lens ----
kit = np.load(KIT)
tree = cKDTree(SK[:, :2])          # (x, y)


def clearance(V):
    """Signed distance outward from the body's outer surface, per vertex."""
    d, idx = tree.query(V[:, :2], k=140, distance_upper_bound=0.10)
    out = np.full(len(V), np.nan)
    for k in range(len(V)):
        ii = idx[k][np.isfinite(d[k])]
        if len(ii) < 12:
            continue
        nb = SK[ii]
        same = nb[np.sign(nb[:, 2]) == np.sign(V[k, 2])]
        if len(same) < 8:
            same = nb
        # outer surface here = the point of largest radius in (x,|z|) from the
        # car's rear-zone axis; compare radii so a corner is handled correctly
        r_body = np.percentile(np.hypot(same[:, 0] - (XMAX - 0.55),
                                        np.abs(same[:, 2]) - 0.35), 97)
        r_lens = np.hypot(V[k, 0] - (XMAX - 0.55), np.abs(V[k, 2]) - 0.35)
        out[k] = r_lens - r_body
    return out


print("\nLENS CLEARANCE (positive = proud of the body, negative = buried):")
for tag, nm in (("ro", "R outer"), ("rh", "R hatch"),
                ("lo", "L outer"), ("lh", "L hatch")):
    V = kit[f"{tag}_v"]
    cl = clearance(V)
    ok = np.isfinite(cl)
    print(f"  {nm:8s}: n={int(ok.sum()):4d}  median {1000*np.median(cl[ok]):+6.0f}mm  "
          f"p10 {1000*np.percentile(cl[ok],10):+6.0f}mm  p90 {1000*np.percentile(cl[ok],90):+6.0f}mm"
          f"   BURIED {100*np.mean(cl[ok] < 0):.0f}% of verts")
