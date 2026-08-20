#!/usr/bin/env python3
"""surface_calib.py — calibrate sigma_theta against surfaces of KNOWN quality.

THE PROBLEM THIS FIXES. surface_metric.py was first calibrated against 14
audited catalogue cars, and the result was that the generated Golf scored a
LOWER sigma_theta than every real car (3.7 deg against 9-32 deg). That is not
evidence the Golf is smoother; it is evidence the comparison is confounded, in
two ways that both run the same direction:

  * TESSELLATION. sigma_theta is measured in a PHYSICAL radius. The Golf's
    median edge is 14 mm, so a 25 mm ball holds a real neighbourhood. A 19,200
    face catalogue car has edges of 60 mm and up, so the same ball holds almost
    nothing, the quadric fit is under-determined, and the number it returns is
    about the sampling rather than about the surface.
  * REAL DETAIL. A real car's normal field departs from a local quadric through
    deliberate hard-surface detail — fillets, swages, trim steps. Those are
    features, and they raise sigma.

So the catalogue band answers "does this look like a catalogue car", which is
NOT the question this gate asks. The gate asks whether the panel is Class-A.
That needs a reference of known quality at THIS car's sampling density, and the
only way to get one is to build it.

WHAT THIS BUILDS. A doubly-curved panel with the crown radii of a real car roof
(2.0 m across, 8.0 m along), triangulated IRREGULARLY at a chosen edge length,
then displaced by band-limited noise of a stated RMS amplitude in millimetres.
Measuring sigma_theta on that family gives two things the catalogue cannot:

  * A FLOOR: sigma on the zero-noise panel, which is what a perfect surface
    scores at this tessellation. Anything at or near the floor is as good as
    the sampling permits.
  * A SCALE: sigma against noise amplitude, which converts a bare number of
    degrees into "this surface behaves like a perfect panel with N mm of
    roughness on it" — a quantity a person can actually judge.

The irregular triangulation matters. A regular grid has a systematically
different facet-angle distribution from a generated mesh, so a floor measured
on a grid would be optimistic. Vertices are jittered and the triangulation is
Delaunay over the jittered points.

Run:
  python3 surface_calib.py [--edge-mm 14] [--noise-mm 0,0.1,0.25,0.5,1,2,4]
        [--radii 0.025,0.080] [--size 1.6] [--seed 0] [--json out.json]
"""
import argparse
import json
import math
import os
import sys

import numpy as np
import trimesh
from scipy.spatial import Delaunay

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import surface_metric as sm            # noqa: E402


def build_panel(size, edge, noise_rms, seed=0, r_across=2.0, r_along=8.0,
                noise_wavelength=0.030):
    """A doubly-curved panel, irregularly triangulated, with band-limited noise.

    The noise is a sum of sinusoids near `noise_wavelength`, not white noise per
    vertex. White per-vertex noise is not what a generated surface does: a voxel
    grid produces CORRELATED error at roughly the voxel pitch, and white noise
    would be far easier for a quadric fit to reject, which would make the floor
    look better than it is.
    """
    rng = np.random.default_rng(seed)
    n = max(4, int(size / edge))
    xs = np.linspace(-size / 2, size / 2, n + 1)
    gx, gy = np.meshgrid(xs, xs)
    P = np.stack([gx.ravel(), gy.ravel()], axis=1)
    interior = (np.abs(P[:, 0]) < size / 2 - 1e-9) & \
               (np.abs(P[:, 1]) < size / 2 - 1e-9)
    P[interior] += rng.normal(0, edge * 0.32, size=(interior.sum(), 2))
    tri = Delaunay(P)
    # height: a quadric crown. This is EXACTLY in the metric's fit space, so a
    # noiseless panel must score ~0 — which is what makes it a valid floor.
    z = -(P[:, 0] ** 2 / (2 * r_across) + P[:, 1] ** 2 / (2 * r_along))
    if noise_rms > 0:
        k = 2 * math.pi / noise_wavelength
        acc = np.zeros(len(P))
        for _ in range(6):
            th = rng.uniform(0, math.pi)
            ph = rng.uniform(0, 2 * math.pi)
            kk = k * rng.uniform(0.7, 1.4)
            acc += np.sin(kk * (P[:, 0] * math.cos(th) + P[:, 1] * math.sin(th))
                          + ph)
        acc *= noise_rms / max(acc.std(), 1e-12)
        z = z + acc
    V = np.stack([P[:, 0], P[:, 1], z], axis=1)
    return trimesh.Trimesh(vertices=V, faces=tri.simplices, process=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--edge-mm", type=float, default=14.0)
    ap.add_argument("--noise-mm", default="0,0.05,0.1,0.25,0.5,1.0,2.0,4.0")
    ap.add_argument("--radii", default="0.025,0.080")
    ap.add_argument("--size", type=float, default=1.6)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    radii = [float(x) for x in a.radii.split(",")]
    noises = [float(x) for x in a.noise_mm.split(",")]

    print(f"synthetic panel: {a.size} m square, crown radii 2.0 x 8.0 m, "
          f"target edge {a.edge_mm} mm, band-limited noise at 30 mm")
    print(f"{'noise_mm':>9s} {'faces':>7s} {'edge_mm':>8s} " +
          " ".join(f"{'s'+str(int(R*1000)):>8s} {'C'+str(int(R*1000)):>7s}"
                   for R in radii))
    rows = []
    for nm in noises:
        m = build_panel(a.size, a.edge_mm / 1000.0, nm / 1000.0, seed=a.seed)
        # trim the border: faces at the rim have one-sided neighbourhoods and
        # their fits are legitimately worse, which would contaminate the floor.
        C = m.vertices[m.faces].mean(axis=1)
        keep = (np.abs(C[:, 0]) < a.size / 2 - 0.12) & \
               (np.abs(C[:, 1]) < a.size / 2 - 0.12)
        el = float(np.median(m.edges_unique_length)) * 1000
        row = dict(noise_mm=nm, faces=int(keep.sum()), edge_mm=round(el, 2))
        cells = []
        for R in radii:
            s = sm.slope_error(m, R, mask=keep, max_faces=200000)
            row[f"s{int(R*1000)}"] = s.get("rms")
            row[f"C{int(R*1000)}"] = s.get("coherence")
            cells.append(f"{s.get('rms', float('nan')):8.3f} "
                         f"{s.get('coherence') if s.get('coherence') is not None else float('nan'):7.3f}")
        print(f"{nm:9.2f} {row['faces']:7d} {el:8.2f} " + " ".join(cells))
        rows.append(row)

    # ---- the inverse map: degrees -> millimetres of equivalent roughness
    print("\n=== READING A MEASURED sigma AS AN AMPLITUDE ===")
    for R in radii:
        k = f"s{int(R*1000)}"
        xs = [r["noise_mm"] for r in rows if r[k] is not None]
        ys = [r[k] for r in rows if r[k] is not None]
        floor = ys[0]
        print(f"  radius {int(R*1000)}mm: floor (perfect panel, "
              f"{a.edge_mm:.0f}mm edges) = {floor:.3f} deg")
        for target in (1.0, 2.0, 3.0, 5.0):
            amp = np.interp(target, ys, xs)
            print(f"    sigma {target:.1f} deg  ~  {amp:.2f} mm of "
                  f"30mm-wavelength surface noise")

    if a.json:
        with open(a.json, "w") as fh:
            json.dump(dict(edge_mm=a.edge_mm, size=a.size, rows=rows), fh,
                      indent=1)
        print("wrote", a.json)


if __name__ == "__main__":
    main()
