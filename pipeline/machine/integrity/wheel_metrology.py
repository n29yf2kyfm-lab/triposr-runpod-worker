#!/usr/bin/env python3
"""wheel_metrology.py — measure each corner's wheel axis, radius, width and hub,
and CALIBRATE the angle estimator by injecting known rotations.

Run:
  python3 wheel_metrology.py MEASURE  IN.glb  OUT.json
  python3 wheel_metrology.py CALIBRATE IN.glb OUT.json [--corner FR]

WHY THE CALIBRATION IS NOT OPTIONAL. A previous wheel gate in this project
reported toe and camber for weeks off an estimator that selected its tread band
"within 3% of R of the ASSUMED axis". Injecting a known 2.000 deg moved its
reading by 0.69 deg -- RESPONSE SLOPE 0.35. Every angle it ever reported was
about three times too small and biased toward zero, and the repair that rotated
by the reported error under-corrected by the same factor. A unit test on the
fitter would have passed, because the fitter was never the problem: the SAMPLE
SELECTION was. So the calibration injects into the real car and re-runs the
whole CLI path, and the slope is reported with the angles, every time.

The fix that restores the slope is to re-select the band about the EVOLVING
axis rather than the assumed one, iterating to convergence.

HONESTY ABOUT PRECISION. Two different quantities get confused:
  * repeatability of a CHANGE under one fixed band definition -- tight;
  * ABSOLUTE accuracy across equally defensible band definitions -- on melt
    tyres this project measured +-0.18 to +-0.86 deg, because a generated tyre
    is not round to better than ~4.5 mm rms.
This tool reports BOTH, and where the spread exceeds the tolerance it says the
angle is NOT MEASURABLE at that tolerance rather than certifying it. Saying so
is the correct answer, not a failure.

No Blender: reads the GLB directly so the importer is not in the loop.
"""
import json
import math
import sys

import numpy as np

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from gltf_facts import load_glb, read_accessor, trs_to_mat, mat_mul  # noqa: E402

CORNERS = ("FL", "FR", "RL", "RR")


# ------------------------------------------------------------------ geometry
def node_world_vertices(g, bin_, want_names):
    """{node_name: (n,3) WORLD vertices}. Measured from TRANSFORMED vertices --
    never from a node translation, which downstream stages bake to zero."""
    nodes = g["nodes"]
    parent = {}
    for i, n in enumerate(nodes):
        for c in n.get("children", []):
            parent[c] = i
    cache = {}

    def wmat(i):
        if i in cache:
            return cache[i]
        m = trs_to_mat(nodes[i])
        if i in parent:
            m = mat_mul(wmat(parent[i]), m)
        cache[i] = m
        return m

    out = {}
    for i, n in enumerate(nodes):
        nm = n.get("name")
        if nm not in want_names or n.get("mesh") is None:
            continue
        M = np.array(wmat(i), dtype=np.float64)
        chunks = []
        for p in g["meshes"][n["mesh"]]["primitives"]:
            v = np.array(read_accessor(g, bin_, p["attributes"]["POSITION"]),
                         dtype=np.float64)
            chunks.append(v)
        V = np.vstack(chunks)
        # Transform IN glTF SPACE, then convert axes ONCE at the very end.
        # An earlier version conjugated the matrix by the axis swap with
        # hand-written indices and got it wrong -- it put the FL tyre centre at
        # z=0.497 on a wheel of radius 0.32 sitting on the ground, which is
        # impossible, and the axis fit then returned toe=-73 deg. Doing the
        # swap once, on the finished world points, removes the whole class.
        W = V @ M[:3, :3].T + np.array([M[0][3], M[1][3], M[2][3]])
        # glTF Y-up -> this gate's Z-up frame, exactly as Blender's importer:
        # gltf(x, y, z) -> (x, -z, y)
        out[nm] = np.column_stack([W[:, 0], -W[:, 2], W[:, 1]])
    return out


def fit_axis(P, band_lo=0.97, band_hi=1.03, iters=12, seed=None):
    """Iteratively fit a wheel axis to tread points.

    THE ITERATION IS THE WHOLE POINT: the tread band is re-selected about the
    axis found on the previous pass, so the answer stops being a restatement of
    the seed. Selecting once about an assumed axis is what produced slope 0.35.
    """
    c = P.mean(axis=0)
    a = np.array(seed if seed is not None else [0.0, 1.0, 0.0], dtype=float)
    a /= np.linalg.norm(a)
    hist = []
    for _ in range(iters):
        d = P - c
        axial = d @ a
        radial = d - np.outer(axial, a)
        r = np.linalg.norm(radial, axis=1)
        R = np.percentile(r, 95)
        m = (r >= band_lo * R) & (r <= band_hi * R)
        if m.sum() < 50:
            break
        B = P[m]
        Bc = B.mean(axis=0)
        # smallest-variance direction of the tread annulus IS its axis:
        # the band spans ~2R across the wheel plane and only the tyre width
        # along the axis, and R > half-width holds for every road wheel.
        u, s, vt = np.linalg.svd(B - Bc, full_matrices=False)
        a_new = vt[2] / np.linalg.norm(vt[2])
        if a_new @ a < 0:
            a_new = -a_new
        # centre: mean of the band, projected to remove axial bias
        c_new = Bc
        hist.append(float(math.degrees(math.acos(
            max(-1.0, min(1.0, abs(a_new @ a)))))))
        a, c = a_new, c_new
        if hist[-1] < 1e-6:
            break
    d = P - c
    axial = d @ a
    radial = d - np.outer(axial, a)
    r = np.linalg.norm(radial, axis=1)
    R = float(np.percentile(r, 95))
    m = (r >= band_lo * R) & (r <= band_hi * R)
    return {
        "axis": a, "centre": c, "radius_p95": R,
        "width": float(axial.max() - axial.min()),
        "tread_points": int(m.sum()),
        "roundness_rms_mm": float(np.std(r[m]) * 1000.0),
        "converge_deg": hist[-1] if hist else None,
    }


def angles(axis, side):
    """toe   = rotation about the VERTICAL axis (Z) — axis swing in plan view.
    camber = tilt of the wheel plane from vertical = tilt of the axis from
    horizontal. Sign is reported per-side with outboard taken as positive."""
    a = np.array(axis, dtype=float)
    a = a / np.linalg.norm(a)
    if (side == "L" and a[1] < 0) or (side == "R" and a[1] > 0):
        a = -a                      # orient OUTBOARD
    toe = math.degrees(math.atan2(a[0], abs(a[1])))
    camber = math.degrees(math.asin(max(-1.0, min(1.0, a[2]))))
    if side == "R":                 # mirror sign so L/R are comparable
        toe = -toe
    return {"toe_deg": round(toe, 4), "camber_deg": round(camber, 4),
            "axis_outboard": [round(float(v), 6) for v in a]}


def measure_corner(vt, corner, band=(0.97, 1.03)):
    tyre = vt.get(f"Wheel_{corner}_Tyre")
    if tyre is None:
        return None
    f = fit_axis(tyre, band[0], band[1])
    side = "L" if corner[1] == "L" else "R"
    row = {"corner": corner,
           "centre": [round(float(v), 6) for v in f["centre"]],
           "radius_m": round(f["radius_p95"], 6),
           "diameter_m": round(f["radius_p95"] * 2, 6),
           "width_m": round(f["width"], 6),
           "tread_points": f["tread_points"],
           "roundness_rms_mm": round(f["roundness_rms_mm"], 3),
           "tyre_bottom_z_m": round(float(tyre[:, 2].min()), 6),
           "tyre_bottom_mm": round(float(tyre[:, 2].min()) * 1000, 3)}
    row.update(angles(f["axis"], side))
    for part in ("Rim", "Disc"):
        P = vt.get(f"Wheel_{corner}_{part}")
        if P is not None:
            row[f"{part.lower()}_centre"] = [round(float(v), 6)
                                             for v in P.mean(axis=0)]
            row[f"{part.lower()}_verts"] = int(len(P))
    return row


def load_wheels(path):
    g, bin_ = load_glb(path)
    want = {f"Wheel_{c}_{p}" for c in CORNERS
            for p in ("Tyre", "Rim", "Disc")}
    return g, bin_, node_world_vertices(g, bin_, want)


def cmd_measure(path, out):
    g, bin_, vt = load_wheels(path)
    rows = [r for r in (measure_corner(vt, c) for c in CORNERS) if r]
    # BAND SENSITIVITY = the honest absolute-accuracy figure. Eight equally
    # defensible band definitions; the SPREAD is the uncertainty, and if it
    # exceeds the tolerance the angle is NOT MEASURABLE at that tolerance.
    bands = [(0.95, 1.05), (0.96, 1.04), (0.97, 1.03), (0.98, 1.02),
             (0.99, 1.01), (0.93, 1.07), (0.90, 1.10), (0.985, 1.015)]
    sens = {}
    for c in CORNERS:
        toes, cams = [], []
        for b in bands:
            r = measure_corner(vt, c, b)
            if r:
                toes.append(r["toe_deg"])
                cams.append(r["camber_deg"])
        if toes:
            sens[c] = {
                "toe_spread_deg": round(max(toes) - min(toes), 4),
                "camber_spread_deg": round(max(cams) - min(cams), 4),
                "toe_values": toes, "camber_values": cams,
                "toe_measurable_at_0p1": bool(max(toes) - min(toes) <= 0.1),
                "camber_measurable_at_0p1": bool(max(cams) - min(cams) <= 0.1),
            }
    doc = {"source": path, "corners": rows, "band_sensitivity": sens,
           "note": ("toe/camber ABSOLUTE accuracy is the band spread above, not "
                    "the repeatability of a change. Where spread > 0.1 deg the "
                    "angle is NOT MEASURABLE at +-0.1 and is reported as such.")}
    json.dump(doc, open(out, "w"), indent=1)
    for r in rows:
        s = sens.get(r["corner"], {})
        print(f"{r['corner']}  R={r['radius_m']:.4f} W={r['width_m']:.4f} "
              f"c=({r['centre'][0]:+.4f},{r['centre'][1]:+.4f},{r['centre'][2]:+.4f}) "
              f"toe={r['toe_deg']:+.3f} camber={r['camber_deg']:+.3f} "
              f"bottom={r['tyre_bottom_mm']:+.2f}mm rms={r['roundness_rms_mm']:.2f}mm "
              f"spread(toe={s.get('toe_spread_deg')},cam={s.get('camber_spread_deg')})")
    return doc


def cmd_calibrate(path, out, corner="FR"):
    """INJECTION LADDER. Rotate the real tyre by a known angle, re-run the whole
    measurement path, and regress measured-vs-injected. Slope 1.0 = faithful."""
    g, bin_, vt = load_wheels(path)
    P0 = vt[f"Wheel_{corner}_Tyre"]
    side = "L" if corner[1] == "L" else "R"
    c0 = P0.mean(axis=0)
    ladder = [-2.0, -1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5, 2.0]
    res = {"corner": corner, "ladder_deg": ladder, "axes": {}}

    for kind, axis_vec in (("toe", np.array([0.0, 0.0, 1.0])),
                           ("camber", np.array([1.0, 0.0, 0.0]))):
        meas = []
        for inj in ladder:
            th = math.radians(inj)
            k = axis_vec / np.linalg.norm(axis_vec)
            K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
            Rm = np.eye(3) + math.sin(th) * K + (1 - math.cos(th)) * (K @ K)
            Pr = (P0 - c0) @ Rm.T + c0
            f = fit_axis(Pr)
            a = angles(f["axis"], side)
            meas.append(a["toe_deg"] if kind == "toe" else a["camber_deg"])
        x = np.array(ladder)
        y = np.array(meas) - meas[ladder.index(0.0)]
        slope, icept = np.polyfit(x, y, 1)
        resid = y - (slope * x + icept)
        res["axes"][kind] = {
            "measured_delta_deg": [round(float(v), 4) for v in y],
            "response_slope": round(float(slope), 4),
            "intercept_deg": round(float(icept), 5),
            "residual_rms_deg": round(float(np.sqrt((resid ** 2).mean())), 5),
            "VERDICT": ("FAITHFUL" if 0.90 <= slope <= 1.10 else
                        "BLIND — estimator understates by "
                        f"{1/slope:.2f}x" if slope > 0 else "BROKEN"),
        }
        print(f"{kind:7} slope={slope:.4f} rms={np.sqrt((resid**2).mean()):.5f} "
              f"-> {res['axes'][kind]['VERDICT']}")
    json.dump(res, open(out, "w"), indent=1)
    return res


if __name__ == "__main__":
    mode = sys.argv[1].upper()
    if mode == "MEASURE":
        cmd_measure(sys.argv[2], sys.argv[3])
    elif mode == "CALIBRATE":
        cn = sys.argv[sys.argv.index("--corner") + 1] \
            if "--corner" in sys.argv else "FR"
        cmd_calibrate(sys.argv[2], sys.argv[3], cn)
    else:
        raise SystemExit("MEASURE | CALIBRATE")
