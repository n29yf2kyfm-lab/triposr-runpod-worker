#!/usr/bin/env python3
"""panel_symmetry.py — "consistent left/right manufactured curvature", measured.

One of Gate 5's acceptance criteria is that the two sides of the car carry the
same curvature. Nothing else in this toolchain tests it, and it is the one
criterion where a RENDER is a weak witness: this project's own rig has a
one-sided key light, and CLAUDE.md records a MAJORITY of catalogue cars showing
a 2-vs-2 brightness split by side that is pure lighting and nothing else. Three
wrong diagnoses were filed against that artefact before the real one.

(The rig used for this gate was separately proven symmetric — on a numerically
exact mirror-symmetric object the left and right renders measured 145.55 vs
145.55, rel_diff 0.000000 — so a left/right difference in THESE renders is the
car. This file measures it in geometry anyway, because a number is auditable
and an eye is not.)

TWO INDEPENDENT MEASUREMENTS, because they fail differently:

  1. MIRROR DISTANCE. Reflect the exterior panel surface through the car's own
     mid-plane and measure, for a sample of panel points, the distance to the
     reflected SURFACE — point-to-triangle, not point-to-vertex. Vertex-to-
     vertex nearest-neighbour would report several millimetres on a perfectly
     symmetric shape whose two sides are merely tessellated differently, which
     is a property of the mesh and not of the car.

     The mid-plane is SOLVED, not assumed: the bbox centre is wrong whenever a
     mirror, an aerial or a single-side artefact drags one extreme, so the
     offset is chosen by minimising the median mirror distance over a scan.

  2. PER-SIDE SURFACE QUALITY. sigma_theta computed separately on the left and
     right flanks. Two sides can be geometrically symmetric to within a
     millimetre and still differ in surface QUALITY if one flank carries more
     chatter, and the mirror distance alone would call that symmetric.

Run:
  python3 panel_symmetry.py <car.glb> --select sel.npz [--sample 20000]
        [--json out.json]
"""
import argparse
import json
import os
import sys

import numpy as np
import trimesh

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import body_surface as bs             # noqa: E402
import surface_metric as sm           # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("glbs", nargs="+")
    ap.add_argument("--select", required=True)
    ap.add_argument("--sample", type=int, default=20000)
    ap.add_argument("--json", default=None)
    a = ap.parse_args()

    base = bs.Car(a.glbs[0])
    sel = np.load(a.select, allow_pickle=True)
    panel = sel["panel"]
    if str(sel.get("fingerprint")) != base.fingerprint:
        raise SystemExit("REFUSED: selection fingerprint does not match")
    feat0 = sm.feature_mask(base.mesh)
    il, iw, iu = sm.car_axes(base.mesh)
    print(f"  axes: length={il} width={iw} up={iu}")

    out = []
    for p in a.glbs:
        car = base if p == a.glbs[0] else bs.Car(p)
        Vw = base.Vw if p == a.glbs[0] else car.rewelded_like(base)
        panel_mesh = trimesh.Trimesh(vertices=Vw, faces=base.Fw[panel],
                                     process=False)
        C = panel_mesh.vertices[panel_mesh.faces].mean(axis=1)
        rng = np.random.default_rng(0)
        idx = rng.choice(len(C), min(a.sample, len(C)), replace=False)
        pts = C[idx]

        # ---- solve the mid-plane rather than assume the bbox centre
        lo, hi = Vw[:, iw].min(), Vw[:, iw].max()
        best, best_off = None, None
        pq = trimesh.proximity.ProximityQuery(panel_mesh)
        for off in np.linspace((lo + hi) / 2 - 0.03, (lo + hi) / 2 + 0.03, 13):
            q = pts.copy()
            q[:, iw] = 2 * off - q[:, iw]
            d = np.abs(pq.signed_distance(q[:2000]))
            med = float(np.median(d))
            if best is None or med < best:
                best, best_off = med, off
        q = pts.copy()
        q[:, iw] = 2 * best_off - q[:, iw]
        d = np.abs(pq.signed_distance(q))

        # ---- per-side surface quality
        flank = sm.region_mask(base.mesh, "flank") & panel & ~feat0
        side = C[:, iw] if False else None
        Cf = base.mesh.vertices[base.Fw].mean(axis=1)
        left = flank & (Cf[:, iw] > best_off)
        right = flank & (Cf[:, iw] < best_off)
        m = trimesh.Trimesh(vertices=Vw, faces=base.Fw, process=False)
        sl = sm.slope_error(m, 0.025, mask=left, max_faces=40000)
        sr = sm.slope_error(m, 0.025, mask=right, max_faces=40000)

        row = dict(file=os.path.basename(p),
                   mid_plane=round(float(best_off), 5),
                   mirror_mm=dict(
                       median=round(float(np.median(d)) * 1000, 3),
                       p90=round(float(np.percentile(d, 90)) * 1000, 3),
                       p99=round(float(np.percentile(d, 99)) * 1000, 3),
                       max=round(float(d.max()) * 1000, 2),
                       frac_over_2mm=round(float((d > 0.002).mean()), 4)),
                   left_s25=sl.get("rms"), right_s25=sr.get("rms"),
                   left_n=sl.get("n"), right_n=sr.get("n"))
        rel = abs(row["left_s25"] - row["right_s25"]) / \
            max(0.5 * (row["left_s25"] + row["right_s25"]), 1e-9)
        row["side_s25_rel_diff"] = round(float(rel), 4)
        out.append(row)
        print(f"\n{row['file']}  mid-plane {best_off:+.4f} m")
        print(f"  mirror distance: median {row['mirror_mm']['median']:.2f}mm  "
              f"p90 {row['mirror_mm']['p90']:.2f}mm  "
              f"p99 {row['mirror_mm']['p99']:.2f}mm  "
              f"max {row['mirror_mm']['max']:.1f}mm  "
              f">2mm {row['mirror_mm']['frac_over_2mm']*100:.1f}%")
        print(f"  flank sigma25: left {row['left_s25']:.3f} deg "
              f"(n={row['left_n']})  right {row['right_s25']:.3f} deg "
              f"(n={row['right_n']})  rel diff {rel*100:.1f}%")

    if a.json:
        with open(a.json, "w") as fh:
            json.dump(out, fh, indent=1)
        print("wrote", a.json)


if __name__ == "__main__":
    main()
