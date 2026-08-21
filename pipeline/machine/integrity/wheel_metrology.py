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
            # KEEP ONLY POSITIONS A TRIANGLE ACTUALLY REFERENCES.
            # 1,297,156 of this file's 1,899,971 declared positions (68.3%) are
            # referenced by no triangle in their own primitive. They are not
            # drawn by any viewer, and including them poisons every geometric
            # statistic -- a p95 tread radius computed over dead points is not
            # a radius of anything. Blender's importer keeps exactly the
            # referenced 602,815, which is why the Blender-side scan was clean
            # and this file-side reader was not.
            if "indices" in p:
                ref = np.unique(np.array(
                    [t[0] for t in read_accessor(g, bin_, p["indices"])]))
                v = v[ref]
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


def _basis(a):
    """Two unit vectors spanning the plane perpendicular to `a`."""
    t = np.array([1.0, 0.0, 0.0])
    if abs(a @ t) > 0.9:
        t = np.array([0.0, 0.0, 1.0])
    e1 = np.cross(a, t)
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(a, e1)
    return e1, e2 / np.linalg.norm(e2)


def _circle_fit(u, v):
    """Kasa algebraic circle fit. Returns (u0, v0, R).

    THE CENTRE MUST COME FROM A CIRCLE FIT, NOT A CENTROID. A tyre on this car
    is a TORN, PARTIAL annulus, and the centroid of a partial arc lies inside
    the circle, not at its centre. Using the band mean walked the assumed centre
    0.13 m off in one iteration and the axis fit then returned toe = -73 deg and
    a "width" of 0.64 m (which is the DIAMETER) on a wheel 0.29 m wide. The
    centroid was reading back the shape of the tear.
    """
    A = np.column_stack([u, v, np.ones_like(u)])
    b = u ** 2 + v ** 2
    sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    u0, v0 = sol[0] / 2.0, sol[1] / 2.0
    R = math.sqrt(max(0.0, sol[2] + u0 ** 2 + v0 ** 2))
    return u0, v0, R


def fit_axis(P, band_lo=0.97, band_hi=1.03, iters=25, seed=None, tol=1e-7):
    """Iteratively fit a wheel axis, centre and radius to tyre points.

    THE ITERATION IS THE WHOLE POINT: the tread band is re-selected about the
    axis found on the previous pass, so the answer stops being a restatement of
    the seed. Selecting once about an assumed axis is what produced a response
    slope of 0.35 in an earlier wheel gate here -- every angle three times too
    small and biased toward zero. Calibration is in cmd_calibrate.
    """
    a = np.array(seed if seed is not None else [0.0, 1.0, 0.0], dtype=float)
    a /= np.linalg.norm(a)
    c = P.mean(axis=0)
    hist = []

    def residual(axis, pts):
        """rms of |radius - best-fit radius| for `pts` about `axis`. The TRUE
        wheel axis is the one that makes the tread most nearly circular."""
        e1, e2 = _basis(axis)
        d = pts - pts.mean(axis=0)
        u, v = d @ e1, d @ e2
        u0, v0, R = _circle_fit(u, v)
        r = np.hypot(u - u0, v - v0)
        return float(np.sqrt(((r - R) ** 2).mean())), (u0, v0, R, e1, e2)

    # DIRECT CYLINDER FIT, not an SVD of the band.
    # The smallest-variance direction of a tread band is the axis only while
    # the band is a wide arc. Measured on the synthetic controls: for a 120 deg
    # torn arc the arc-DEPTH direction has variance 0.0022 against the axis's
    # 0.0040, so SVD picks the wrong one and returns an 88 deg axis error --
    # and this car's left-hand tyres ARE torn arcs. Instead, search the axis
    # over two small angles about the seed and take the axis that minimises
    # tread-circularity residual, re-selecting the band each outer pass.
    for _ in range(iters):
        e1, e2 = _basis(a)
        d = P - c
        u, v = d @ e1, d @ e2
        r = np.hypot(u, v)
        R = np.percentile(r, 95)
        m = (r >= band_lo * R) & (r <= band_hi * R)
        if m.sum() < 50:
            break
        B = P[m]
        best = a
        span, step_deg = 6.0, 1.0
        for _lvl in range(5):
            cand, bestres = None, None
            g = np.arange(-span, span + 1e-9, step_deg)
            for d1 in g:
                for d2 in g:
                    ax = best + math.radians(d1) * e1 + math.radians(d2) * e2
                    ax = ax / np.linalg.norm(ax)
                    res, _ = residual(ax, B)
                    if bestres is None or res < bestres:
                        bestres, cand = res, ax
            best = cand
            span, step_deg = step_deg, step_deg / 5.0
        a_new = best if best @ a >= 0 else -best
        _, (u0, v0, Rc, e1b, e2b) = residual(a_new, B)
        Bm = B.mean(axis=0)
        c_new = Bm + u0 * e1b + v0 * e2b
        step = float(math.degrees(math.acos(
            max(-1.0, min(1.0, abs(float(a_new @ a)))))))
        shift = float(np.linalg.norm(c_new - c))
        hist.append(step)
        a, c = a_new, c_new
        if step < 1e-4 and shift < 1e-6:
            break

    e1, e2 = _basis(a)
    d = P - c
    axial = d @ a
    r = np.hypot(d @ e1, d @ e2)
    Rsel = float(np.percentile(r, 95))
    m = (r >= band_lo * Rsel) & (r <= band_hi * Rsel)
    # RADIUS COMES FROM THE CIRCLE FIT, NOT FROM p95.
    # p95 of a noisy radius is biased HIGH by ~1.645*sigma; on a tyre with the
    # 4.5 mm rms out-of-roundness this project measures, that is +7.4 mm -- and
    # the synthetic control reproduced exactly +7.44 mm. p95 is fine for
    # SELECTING the tread band and wrong for REPORTING the radius.
    if m.any():
        u0, v0, Rfit = _circle_fit((d @ e1)[m], (d @ e2)[m])
    else:
        Rfit = Rsel
    R = float(Rfit)
    return {
        "axis": a, "centre": c, "radius_p95": R, "radius_select_p95": Rsel,
        "width": float(axial[m].max() - axial[m].min()) if m.any() else 0.0,
        "tread_points": int(m.sum()),
        "roundness_rms_mm": float(np.std(r[m]) * 1000.0) if m.any() else None,
        "converge_deg": hist[-1] if hist else None,
        "iterations": len(hist),
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
        # SIGN IS A CONVENTION, MAGNITUDE IS THE INSTRUMENT.
        # A rotation about +Z moves this estimator's reported toe NEGATIVE for
        # both sides (and camber's sign differs by side, as camber conventionally
        # does), so a slope of -1 is a faithful instrument with an opposite
        # label, NOT a blind one. What would indicate blindness is |slope| well
        # below 1 -- the 0.35 that this project's previous wheel gate scored.
        # Both are reported so neither can be mistaken for the other.
        near = np.abs(x) <= 1.0
        sl_near, ic_near = np.polyfit(x[near], y[near], 1)
        rs_near = y[near] - (sl_near * x[near] + ic_near)
        mag = abs(float(slope))
        res["axes"][kind] = {
            "sign_convention": "rotation about +axis reports NEGATIVE here",
            "measured_delta_deg": [round(float(v), 4) for v in y],
            "response_slope": round(float(slope), 4),
            "response_slope_magnitude": round(mag, 4),
            "intercept_deg": round(float(icept), 5),
            "residual_rms_deg": round(float(np.sqrt((resid ** 2).mean())), 5),
            "linear_range_slope_magnitude": round(abs(float(sl_near)), 4),
            "linear_range_residual_rms_deg": round(
                float(np.sqrt((rs_near ** 2).mean())), 5),
            "VERDICT": ("FAITHFUL" if 0.90 <= mag <= 1.10 else
                        f"DEGRADED — understates by {1/mag:.2f}x over the full "
                        f"ladder" if mag > 0.05 else "BLIND"),
        }
        print(f"{kind:7} slope={slope:+.4f} |slope|={mag:.4f} rms={np.sqrt((resid**2).mean()):.5f} "
              f"| linear-range |slope|={abs(sl_near):.4f} rms={np.sqrt((rs_near**2).mean()):.5f} "
              f"-> {res['axes'][kind]['VERDICT']}")
    json.dump(res, open(out, "w"), indent=1)
    return res


def cmd_selftest(out):
    """Synthetic wheels with KNOWN truth. The fitter must recover the axis,
    centre and radius of each -- INCLUDING a torn partial arc, because that is
    the case that broke it: the band CENTROID of a partial arc sits inside the
    circle, walked the assumed centre 0.13 m off in one iteration, and produced
    toe = -73 deg on a real wheel."""
    rng = np.random.default_rng(7)
    rows, ok = [], True

    def make(axis, centre, R, W, arc_deg, n=6000, noise=0.0):
        a = np.array(axis, float)
        a /= np.linalg.norm(a)
        e1, e2 = _basis(a)
        th = rng.uniform(-math.radians(arc_deg) / 2,
                         math.radians(arc_deg) / 2, n)
        ax = rng.uniform(-W / 2, W / 2, n)
        rr = R + rng.normal(0, noise, n)
        return (np.array(centre)
                + (rr * np.cos(th))[:, None] * e1
                + (rr * np.sin(th))[:, None] * e2
                + ax[:, None] * a)

    cases = [
        ("full_annulus", [0, 1, 0], [-1.3, -0.68, 0.32], 0.32, 0.22, 360, 0.0),
        ("torn_180deg", [0, 1, 0], [1.2, 0.70, 0.31], 0.31, 0.22, 180, 0.0),
        ("torn_120deg", [0, 1, 0], [1.2, 0.70, 0.31], 0.31, 0.22, 120, 0.0),
        ("toed_2deg", [math.sin(math.radians(2)), math.cos(math.radians(2)), 0],
         [-1.3, -0.68, 0.32], 0.32, 0.22, 360, 0.0),
        ("cambered_2deg", [0, math.cos(math.radians(2)),
                           math.sin(math.radians(2))],
         [-1.3, -0.68, 0.32], 0.32, 0.22, 360, 0.0),
        ("noisy_4p5mm", [0, 1, 0], [-1.3, -0.68, 0.32], 0.32, 0.22, 360, 0.0045),
    ]
    for name, ax, c, R, W, arc, nz in cases:
        P = make(ax, c, R, W, arc, noise=nz)
        f = fit_axis(P)
        at = np.array(ax, float)
        at /= np.linalg.norm(at)
        fa = f["axis"] * (1 if f["axis"] @ at > 0 else -1)
        ang = math.degrees(math.acos(max(-1, min(1, float(fa @ at)))))
        cerr = float(np.linalg.norm(f["centre"] - np.array(c))) * 1000
        rerr = (f["radius_p95"] - R) * 1000
        # The noisy case is the NOISE FLOOR, not a correctness case: a tyre
        # that is 4.5 mm rms out of round cannot pin its own axis to 0.1 deg,
        # and saying so is the correct answer rather than certifying it.
        noise_case = name.startswith("noisy")
        lim_ang = 0.40 if noise_case else 0.05
        lim_rad = 3.0 if noise_case else 2.0
        good = ang < lim_ang and cerr < 3.0 and abs(rerr) < lim_rad
        ok &= good
        rows.append({"case": name, "role": ("NOISE FLOOR" if noise_case
                                            else "correctness"),
                     "axis_err_deg": round(ang, 4),
                     "centre_err_mm": round(cerr, 3),
                     "radius_err_mm": round(rerr, 3),
                     "width_fit": round(f["width"], 4), "width_true": W,
                     "iters": f["iterations"], "PASS": good})
        print(f"{'PASS' if good else 'FAIL':4} {name:16} axis_err={ang:.4f}deg "
              f"centre_err={cerr:.2f}mm radius_err={rerr:+.2f}mm "
              f"W={f['width']:.3f}/{W}")
    json.dump({"cases": rows, "ALL_PASS": bool(ok)}, open(out, "w"), indent=1)
    print("METROLOGY_SELFTEST", "ALL_PASS" if ok else "FAILURES")
    return ok


if __name__ == "__main__":
    mode = sys.argv[1].upper()
    if mode == "SELFTEST":
        cmd_selftest(sys.argv[2])
    elif mode == "MEASURE":
        cmd_measure(sys.argv[2], sys.argv[3])
    elif mode == "CALIBRATE":
        cn = sys.argv[sys.argv.index("--corner") + 1] \
            if "--corner" in sys.argv else "FR"
        cmd_calibrate(sys.argv[2], sys.argv[3], cn)
    else:
        raise SystemExit("MEASURE | CALIBRATE")
