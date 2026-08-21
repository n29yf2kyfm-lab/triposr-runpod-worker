#!/usr/bin/env python3
"""merge_calib.py — how much of an injected wheel angle does the probe report?

WHY THIS EXISTS. Gate 6's toe/camber instrument had a measured RESPONSE SLOPE
OF 0.35: a wheel rotated by a known 2.000 deg re-measured as 0.69 deg, because
the tread band was selected about the ASSUMED axis and the assumption survived
into the answer. Every angle this project reported for weeks was ~3x too small
and biased toward zero, and a repair that rotated by the reported error
under-corrected by the same factor. The fix (iterating the band selection about
the evolving axis) is inside `wheel_metrology.iterate_axis`, which
`wheel_probe` calls — but a slope measured on somebody else's call stack is not
a measurement of mine. This runs the ladder through THIS package's own path.

FOUR EXPERIMENTS, and the last two are the ones that decided the operator:

  ladder     rotate one corner's geometry by a known angle, write a real GLB,
             re-run the full probe, and regress reported change on injected
             angle. Slope 1.0 = faithful; 0.35 = the old bug; >1 = overshoot.
  null       apply a change that CANNOT alter the axis (a pure radial scale,
             which is a similarity in the plane perpendicular to the axis) and
             re-measure. Anything the probe reports here is pure irreproducibility
             and is a floor under its error.
  estimators four independent axis estimators of the SAME wheel — the tread
             cylinder fit, the brake disc's vertex PCA, the brake disc's
             area-weighted face-normal PCA, and the rim's vertex PCA. Their
             spread is the honest instrument error, and on melt geometry it is
             very much larger than the ladder's own repeatability.
  patch      the contact patch's principal direction, which is a completely
             different physical route to the same axis.

WHAT IT FOUND ON THIS CAR (CALIB_<corner>.json; the conclusion line in each is
COMPUTED from those numbers, not written in advance — the first draft of this
docstring said "the ladder is faithful" and the data said otherwise):

  corner FL   toe slope 0.77   camber slope 0.73   estimator spread 9.2 deg
  corner RR   toe slope -0.40  camber slope -0.46  estimator spread 2.9 deg

FL is ATTENUATED — a correction rotating by the reported error under-corrects
by about a quarter, which is Gate 6's own failure in a milder form. RR IS
WORSE THAN ATTENUATED: THE SLOPE IS NEGATIVE. The probe reports an injected
rotation as a rotation the other way, so squaring that wheel by the reported
error drives it further from square. That is not a subtle bias; it is the
instrument being unusable on that corner, and it explains the closed-loop
result exactly — when the axes WERE squared, RR's toe went from +1.97 to
-1.13 deg, i.e. it overshot and changed sign.

Add the four independent estimators disagreeing by up to 9.2 deg on the same
wheel, and a null operation (a pure radial scale, which cannot rotate an axis)
moving the reading by up to 0.38 deg, and the verdict is unambiguous:
`merge_op` does NOT square the wheel axes by default, and reports measured
toe/camber as NOT MEASURABLE rather than as numbers.

Run:
    python3 merge_calib.py CAR.glb --corner FL --report CALIB.json
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import wheel_probe as WP                      # noqa: E402
from glb_io import GLB                        # noqa: E402
from merge_op import frame_of                 # noqa: E402

LADDER = (-2.0, -1.0, -0.5, -0.25, 0.0, 0.25, 0.5, 1.0, 2.0)


def _rot(axis, deg):
    a = np.asarray(axis, float)
    a = a / np.linalg.norm(a)
    th = math.radians(deg)
    K = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    return np.eye(3) + math.sin(th) * K + (1 - math.cos(th)) * K @ K


def _write_variant(src, corner, L, pivot, out):
    """Apply linear map L about `pivot` to one corner's nodes; real GLB out."""
    g = GLB(src)
    for name, W, mi, pi, p in g.prims():
        if not name.startswith(f"Wheel_{corner}_"):
            continue
        V = g.world_positions(W, p)
        g.write_accessor(p["attributes"]["POSITION"],
                         (V - pivot) @ L.T + pivot)
        N = g.accessor(p["attributes"]["NORMAL"]).astype(np.float64)
        NL = np.linalg.inv(L).T
        N = N @ NL.T
        n = np.linalg.norm(N, axis=1)
        ok = n > 1e-8
        N[ok] /= n[ok][:, None]
        g.write_accessor(p["attributes"]["NORMAL"], N)
        nd = g.g["nodes"][[i for i, x in enumerate(g.g["nodes"])
                           if x.get("name") == name][0]]
        for k in ("translation", "rotation", "scale", "matrix"):
            nd.pop(k, None)
    g.save(out)
    return out


def measure(path, corner):
    g = GLB(path)
    cs, nose, _ = WP.corners(g)
    m = WP.measure_corner(cs[corner]["P"])
    toe, cam = WP.angles(m["axis"], m["centre"], nose)
    return dict(toe=toe, camber=cam, R=m["R"], width=m["width"],
                rms=m["rms"], centre=m["centre"], axis=m["axis"])


def estimators(path, corner):
    g = GLB(path)
    cs, nose, _ = WP.corners(g)
    node = {n: (g.world_positions(M, p), g.faces(p))
            for n, M, mi, pi, p in g.prims()}
    m = WP.measure_corner(cs[corner]["P"])
    a = m["axis"]

    def pca(P):
        d = P - P.mean(0)
        w, v = np.linalg.eigh(d.T @ d)
        return v[:, 0] / np.linalg.norm(v[:, 0])

    def facen(P, F):
        A = P[F[:, 0]]
        n = np.cross(P[F[:, 1]] - A, P[F[:, 2]] - A)
        mag = np.linalg.norm(n, axis=1)
        ok = mag > 1e-12
        u = n[ok] / mag[ok, None]
        C = (u * mag[ok, None]).T @ u
        w, v = np.linalg.eigh(C)
        return v[:, -1] / np.linalg.norm(v[:, -1])

    def deg(x, y):
        return math.degrees(math.acos(min(1.0, abs(float(
            x / np.linalg.norm(x) @ (y / np.linalg.norm(y)))))))

    dP, dF = node[f"Wheel_{corner}_Disc"]
    rP, _ = node[f"Wheel_{corner}_Rim"]
    tP, _ = node[f"Wheel_{corner}_Tyre"]
    est = dict(tread_cylinder=[float(x) for x in a],
               disc_pca=[float(x) for x in pca(dP)],
               disc_face_normals=[float(x) for x in facen(dP, dF)],
               rim_pca=[float(x) for x in pca(rP)])
    names = list(est)
    pair = {}
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            pair[f"{names[i]} vs {names[j]}"] = round(
                deg(np.array(est[names[i]]), np.array(est[names[j]])), 4)
    # contact-patch principal direction: a completely different physical route
    patch = {}
    for h in (0.004, 0.008, 0.015, 0.025):
        s = tP[:, 1] < h
        if s.sum() < 30:
            patch[f"{int(h * 1000)}mm"] = None
            continue
        Q = tP[s][:, [0, 2]]
        d = Q - Q.mean(0)
        w, v = np.linalg.eigh(d.T @ d)
        ax = v[:, -1]
        patch[f"{int(h * 1000)}mm"] = dict(
            n=int(s.sum()),
            long_axis_deg_from_X=round(math.degrees(math.atan2(ax[1], ax[0])), 3))
    return dict(axes=est, pairwise_angle_deg=pair,
                max_pairwise_deg=max(pair.values()),
                contact_patch=patch)


def _conclude(out, nd, nc):
    """State what the numbers say, not what was expected before the run."""
    ts = out["ladder"]["toe"]["slope"]
    cs_ = out["ladder"]["camber"]["slope"]
    sp = out["estimators"]["max_pairwise_deg"]
    bits = []
    for nm, sl, rms in (("toe", ts, out["ladder"]["toe"]["residual_rms_deg"]),
                        ("camber", cs_,
                         out["ladder"]["camber"]["residual_rms_deg"])):
        if sl <= 0.0:
            bits.append(f"{nm} response has the WRONG SIGN (slope {sl:.2f}): "
                        f"the probe reports an injected rotation as a rotation "
                        f"the other way, so a correction using it makes the "
                        f"wheel worse, not better")
        elif sl > 0.95:
            bits.append(f"{nm} response is faithful (slope {sl:.2f})")
        elif sl > 0.5:
            bits.append(f"{nm} is ATTENUATED (slope {sl:.2f}: a correction "
                        f"rotating by the reported error under-corrects by "
                        f"{100 * (1 - sl):.0f}%), ladder rms {rms:.2f} deg")
        else:
            bits.append(f"{nm} is SEVERELY attenuated (slope {sl:.2f}) — the "
                        f"Gate 6 pre-fix failure mode")
    usable = ts > 0.95 and cs_ > 0.95 and sp < 1.0
    bits.append(f"four independent estimators of the same axis disagree by up "
                f"to {sp:.1f} deg")
    bits.append(f"a null operation (pure radial scale, which cannot rotate an "
                f"axis) moves the reading by up to {max(nd, nc):.2f} deg")
    bits.append("VERDICT: absolute toe/camber are "
                + ("MEASURABLE" if usable else "NOT MEASURABLE")
                + " on this geometry; merge_op does not square the axes by "
                  "default")
    return "; ".join(bits)


def run(args):
    base = measure(args.glb, args.corner)
    up = np.array([0.0, 1.0, 0.0])
    fwd = np.array([-1.0, 0.0, 0.0])          # nose at -X on this family
    out = dict(file=os.path.abspath(args.glb), corner=args.corner,
               baseline=dict(toe_deg=base["toe"], camber_deg=base["camber"],
                             R_m=base["R"], width_m=base["width"],
                             fit_rms_m=base["rms"]),
               ladder={}, null={}, estimators=estimators(args.glb, args.corner))
    pivot = base["centre"]
    with tempfile.TemporaryDirectory() as td:
        for axis_name, axis, key in (("toe", up, "toe"),
                                     ("camber", fwd, "camber")):
            rows = []
            for inj in LADDER:
                p = os.path.join(td, f"{axis_name}_{inj}.glb")
                _write_variant(args.glb, args.corner, _rot(axis, inj), pivot, p)
                m = measure(p, args.corner)
                rows.append(dict(injected_deg=inj,
                                 reported_toe_deg=m["toe"],
                                 reported_camber_deg=m["camber"],
                                 delta_deg=m[key] - base[key]))
                os.remove(p)
            x = np.array([r["injected_deg"] for r in rows])
            y = np.array([r["delta_deg"] for r in rows])
            k, c = np.polyfit(x, y, 1)
            res = y - (k * x + c)
            out["ladder"][axis_name] = dict(
                rows=rows, slope=float(k), intercept_deg=float(c),
                residual_rms_deg=float(np.sqrt((res ** 2).mean())),
                note=("slope 1.0 = the probe reports the whole of an injected "
                      "angle; Gate 6's pre-fix instrument measured 0.35"))
        # null control: a pure radial scale cannot rotate the axis
        for s in (0.98, 1.02):
            F = frame_of(base["axis"])
            L = F @ np.diag([s, s, 1.0]) @ F.T
            p = os.path.join(td, f"null_{s}.glb")
            _write_variant(args.glb, args.corner, L, pivot, p)
            m = measure(p, args.corner)
            out["null"][f"radial_scale_{s}"] = dict(
                d_toe_deg=m["toe"] - base["toe"],
                d_camber_deg=m["camber"] - base["camber"],
                note="must be 0; whatever it is, is irreproducibility")
            os.remove(p)
    nd = max(abs(v["d_toe_deg"]) for v in out["null"].values())
    nc = max(abs(v["d_camber_deg"]) for v in out["null"].values())
    out["verdict"] = dict(
        toe_slope=out["ladder"]["toe"]["slope"],
        camber_slope=out["ladder"]["camber"]["slope"],
        null_drift_toe_deg=nd, null_drift_camber_deg=nc,
        estimator_spread_deg=out["estimators"]["max_pairwise_deg"],
        conclusion=_conclude(out, nd, nc))
    print(json.dumps(out["verdict"], indent=1))
    for k in ("toe", "camber"):
        print(f"\n{k} ladder (slope {out['ladder'][k]['slope']:.4f}, "
              f"rms {out['ladder'][k]['residual_rms_deg']:.4f} deg)")
        for r in out["ladder"][k]["rows"]:
            print(f"   injected {r['injected_deg']:+.2f}  ->  reported change "
                  f"{r['delta_deg']:+.4f}")
    print("\nindependent estimators of the same axis:")
    for k, v in out["estimators"]["pairwise_angle_deg"].items():
        print(f"   {k:44s} {v:7.3f} deg apart")
    if args.report:
        json.dump(out, open(args.report, "w"), indent=1, default=float)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("glb")
    ap.add_argument("--corner", default="FL", choices=WP.CORNERS)
    ap.add_argument("--report")
    run(ap.parse_args())


if __name__ == "__main__":
    main()
