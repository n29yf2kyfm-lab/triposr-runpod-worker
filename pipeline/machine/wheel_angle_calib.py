#!/usr/bin/env python3
"""wheel_angle_calib.py — how much of a REAL angle does the instrument see?

Gate 6 asks for toe and camber inside +-0.1 degrees. A number that tight is
worthless without knowing what the instrument does to a known input, and this
project has been burned by exactly that: `geom_audit` was tested as a function
and never as an integration, and the WRONG_CLASS regex "verified against the
exact failing titles" had never matched anything.

METHOD — INJECT, DON'T ARGUE
----------------------------
Take the real car. Rotate ONE wheel's geometry, rigidly, about the vehicle's
length axis (pure camber) or up axis (pure toe), by a known angle. Write the
file. Run the ordinary measurement CLI path on it. Regress measured against
injected: the SLOPE is the fraction of a real angle the instrument sees, the
SCATTER about that line is the achievable precision, and the intercept is the
value the estimator reports for whatever the wheel's true angle happens to be.

An instrument that reports 0.10 deg when the wheel moved 1.00 deg is not
precise-but-biased, it is BLIND, and no amount of repair verified against it
means anything.

Run:
    python3 wheel_angle_calib.py CAR.GLB --corner FL --axis camber \
        --spec specs/vw_golf_mk8.json --json calib.json
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys

import numpy as np

import wheel_metrology as WM

LADDER = (-4.0, -2.0, -1.0, -0.5, 0.0, 0.5, 1.0, 2.0, 4.0)


def _rot(axis_idx, ang):
    c, s = math.cos(ang), math.sin(ang)
    M = np.eye(3)
    a, b = [i for i in range(3) if i != axis_idx]
    M[a, a] = c; M[a, b] = -s; M[b, a] = s; M[b, b] = c
    return M


def run(glb, corner, which, spec, ladder=LADDER, tmpdir=None):
    import trimesh
    spec_d = WM.load_spec(spec)
    base = WM.measure(glb, spec=spec_d, bootstrap=False, canonicalise=False)
    row = {r["corner"]: r for r in base["wheels"]}[corner]
    li, ti, ui = (base["axes"]["length"], base["axes"]["lateral"],
                  base["axes"]["up"])
    c = np.array(row["centre"]); a = np.array(row["axis"])
    R, W = row["radius_m"], row["width_m"]
    # camber is a rotation about the LENGTH axis, toe about the UP axis; both
    # are exact rigid rotations of the wheel about its own hub, so the true
    # change in the wheel's axis IS the injected angle, by construction.
    rot_idx = li if which == "camber" else ui
    tmpdir = tmpdir or os.path.dirname(os.path.abspath(glb))
    out = []
    for deg in ladder:
        M = _rot(rot_idx, math.radians(deg))
        sc = trimesh.load(glb, force="scene", process=False)
        n_moved = 0
        for node in sc.graph.nodes_geometry:
            g = sc.geometry[sc.graph[node][1]]
            V = np.asarray(g.vertices, float)
            d = V - c
            lat = d @ a
            rad = np.linalg.norm(d - np.outer(lat, a), axis=1)
            sel = (rad < 1.03 * R) & (np.abs(lat) < 0.80 * W)
            if sel.any():
                V[sel] = (V[sel] - c) @ M.T + c
                g.vertices = V
                n_moved += int(sel.sum())
        p = os.path.join(tmpdir, f"_calib_{which}_{deg:+.2f}.glb")
        sc.export(p)
        m = WM.measure(p, spec=spec_d, bootstrap=False, canonicalise=False)
        # match the same corner by hub position, never by list order
        best = min(m["wheels"],
                   key=lambda r: abs(r["hub_length"] - row["hub_length"]) +
                   abs(r["hub_lat"] - row["hub_lat"]))
        out.append(dict(injected_deg=deg, moved_vertices=n_moved,
                        measured_toe=best["toe_deg"],
                        measured_camber=best["camber_deg"],
                        measured_R=best["radius_m"]))
        os.remove(p)
        print(f"  injected {which} {deg:+.2f} deg on {n_moved} verts -> "
              f"toe {best['toe_deg']:+.4f}  camber {best['camber_deg']:+.4f}",
              file=sys.stderr)

    x = np.array([o["injected_deg"] for o in out])
    y = np.array([o["measured_" + which] for o in out])
    A = np.column_stack([x, np.ones(len(x))])
    sol, *_ = np.linalg.lstsq(A, y, rcond=None)
    resid = y - (sol[0] * x + sol[1])
    return dict(
        file=os.path.abspath(glb), corner=corner, quantity=which,
        points=out,
        response_slope=float(sol[0]),
        reported_at_zero_deg=float(sol[1]),
        residual_rms_deg=float(np.sqrt(np.mean(resid ** 2))),
        residual_max_deg=float(np.abs(resid).max()),
        true_angle_uncertainty_deg=float(
            np.sqrt(np.mean(resid ** 2)) / max(abs(sol[0]), 1e-6)),
        interpretation=(
            "slope 1.0 = the instrument sees a real angle one for one. The "
            "uncertainty on a TRUE angle is the residual scatter divided by "
            "the slope, because a measured value must be divided by the slope "
            "to be read as a real one."))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("glb")
    ap.add_argument("--corner", default="FL")
    ap.add_argument("--axis", choices=["camber", "toe"], default="camber")
    ap.add_argument("--spec", default=None)
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    r = run(a.glb, a.corner, a.axis, a.spec)
    txt = json.dumps(r, indent=1, default=float)
    if a.json:
        open(a.json, "w").write(txt)
        print("wrote", a.json)
    print(f"RESPONSE SLOPE {r['response_slope']:.3f}  "
          f"residual rms {r['residual_rms_deg']:.4f} deg  "
          f"=> true-angle uncertainty {r['true_angle_uncertainty_deg']:.4f} deg")


if __name__ == "__main__":
    main()
