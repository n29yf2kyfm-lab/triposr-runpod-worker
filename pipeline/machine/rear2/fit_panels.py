#!/usr/bin/env python3
"""fit_panels.py — measure + fit the rear patches, with a DEGREE SWEEP.

PARAMETERISATION, chosen by measurement not by taste:
  * bumper     -> RADIAL r(theta,y) about the section's own pivot. It has to
                  be: the bumper wraps to both flank tangents (z -0.894/+0.757
                  against a tail half-width of 0.88/0.76), where x stops being
                  a function of (y,z).
  * hatch      -> DIRECT x(y,z). Inside the tailgate outline the surface is
                  rear-facing everywhere (|z| <= 0.72 against a half-width of
                  0.89), so x is single-valued. v1 of this file used the radial
                  form here too and it DEGENERATED on the upper tailgate --
                  theta ran to +-91 deg with the pivot drifting forward to
                  xc = 1.00, and the fit residual was 18.5 mm rms / 45 mm max.
                  Recorded because the number looked like a bad panel and was
                  actually a bad coordinate system.

TWO PATCHES for the tailgate, split at the backlight sill: one high-degree fit
across that knuckle ROUNDS IT OFF, which is the opposite of Class A. They are
stitched on a shared vertex row later, so the crease is real and the door is
still one closed component.

THE DEGREE SWEEP is the honest way to choose: raising the degree lowers the
residual to the measured skin (fidelity) and raises the built surface's own
waviness (Class-A quality). Both are printed for every degree so the knee is
chosen from evidence, and so a reader can see the trade rather than take my
word for the setting.

Run: python3 fit_panels.py <glb> <out.json> [--sweep]
"""
import json, sys
import numpy as np, trimesh
sys.path.insert(0, __file__.rsplit("/", 1)[0])
import panel_fit as pf
from rear_zone import load_points, section_centre, polar, outer_radius

GLB, OUT = sys.argv[1], sys.argv[2]
SWEEP = "--sweep" in sys.argv
sc = trimesh.load(GLB, force="scene", process=False)
G = dict(sc.geometry)
P, O, names = load_points(sc)
Y_SILL = 0.965

# PHYSICAL-SPACE fit for the hatch (mode "cartphys"): the polynomial is a
# function of the real (y, z), not of the warped u that runs -1..1 across a
# NARROWING panel. Measured consequence of getting this wrong, recorded because
# the number was dramatic: with the warped fit the rebuilt surround's corners
# came out up to 650 mm forward of the real body (x 1.067 against a measured
# 1.71 at y=1.35). The measured surface itself is smooth and monotone --
# 2.02 at (0.97, 0) falling evenly to 1.76 at (1.30, 0) -- so the blow-up was
# the coordinate system, not the car. hatch_surr also stops at y=1.325, short
# of the roof turn where the +z D-pillar plunges forward 370 mm in 0.09 of
# height and no low-order surface can follow it honestly.
PATCH = {
 "bumper":     dict(ylo=0.230, yhi=0.560, src=("Rear_Bumper",),  mode="radial",   du=9, dv=4, dy=0.012),
 "hatch_low":  dict(ylo=0.560, yhi=Y_SILL, src=("Rear_Hatch",),  mode="cartphys", du=6, dv=5, dy=0.012,
                    zdom=(-0.53, 0.53)),
 "hatch_surr": dict(ylo=Y_SILL, yhi=1.325, src=("Rear_Hatch",),  mode="cartphys", du=6, dv=5, dy=0.012,
                    zdom=(-0.73, 0.60)),
}


def outer_x(P, y, dy, z_edges, min_pts=3, spike_mm=12.0):
    """OUTER-EXTREME x per z cell with a lone-spike guard (Gate 4's estimator)."""
    m = (np.abs(P[:, 1] - y) < dy) & (P[:, 0] > 1.20)
    zz, xx = P[m, 2], P[m, 0]
    out = np.full(len(z_edges) - 1, np.nan)
    idx = np.digitize(zz, z_edges) - 1
    for k in range(len(out)):
        v = np.sort(xx[idx == k])[::-1]
        if len(v) < min_pts: continue
        x0 = v[0]
        if len(v) >= 5 and (x0 - v[1:5].max()) > spike_mm / 1000.0: x0 = v[1]
        out[k] = x0
    return out


def smooth_curve(ys, vals, deg=3):
    """Fit a per-height curve (pivot, outline edge) as a low-order polynomial.

    FOUND BY MEASUREMENT, not assumed: the raw per-height pivot z jittered by
    ~10 mm between adjacent 12 mm bands, and in the RADIAL parameterisation the
    pivot enters BOTH built coordinates -- so that jitter was being injected
    straight into the rebuilt bumper and showed up as 1.4-1.9 mm grid waviness
    even at the smoothest polynomial degree. A 7-tap box filter did not remove
    it. The panel surface can only be as smooth as the frame it is built in.
    """
    good = np.isfinite(vals)
    v = np.interp(np.arange(len(vals)), np.flatnonzero(good), np.asarray(vals)[good])
    t = (ys - ys.mean()) / (0.5 * (ys.max() - ys.min()) + 1e-9)
    A = np.stack([t ** i for i in range(deg + 1)], 1)
    w = np.ones(len(v))
    for _ in range(5):
        W = np.sqrt(w)[:, None]
        c, *_ = np.linalg.lstsq(A * W, v * np.sqrt(w), rcond=None)
        r = v - A @ c
        sg = 1.4826 * np.median(np.abs(r - np.median(r))) + 1e-9
        w = (1 - np.clip(r / (2.5 * sg), -1, 1) ** 2) ** 2
    return A @ c, c


def polyval_curve(c, y, ys):
    t = (y - ys.mean()) / (0.5 * (ys.max() - ys.min()) + 1e-9)
    return sum(c[i] * t ** i for i in range(len(c)))


def outline(src, ys, dy, C, mode):
    lo, hi = [], []
    for j, y in enumerate(ys):
        m = np.abs(src[:, 1] - y) < dy
        if m.sum() < 25: lo.append(np.nan); hi.append(np.nan); continue
        if mode == "radial":
            _, q = polar(src[m], C[j, 0], C[j, 1])
        else:
            q = src[m, 2]
        lo.append(np.percentile(q, 0.5)); hi.append(np.percentile(q, 99.5))
    a, ca = smooth_curve(ys, np.array(lo)); b, cb = smooth_curve(ys, np.array(hi))
    return a, b, ca, cb


rep = {"Y_SILL": Y_SILL}
for name, cfg in PATCH.items():
    ys = np.arange(cfg["ylo"] + cfg["dy"] / 2, cfg["yhi"], cfg["dy"])
    C = section_centre(P, ys)
    cx, c_cx = smooth_curve(ys, C[:, 0]); cz, c_cz = smooth_curve(ys, C[:, 1])
    C = np.stack([cx, cz], 1)
    src = np.vstack([G[s].triangles_center for s in cfg["src"]])
    lo, hi, c_lo, c_hi = outline(src, ys, cfg["dy"], C, cfg["mode"])
    U, V, R = [], [], []
    for j, y in enumerate(ys):
        if not np.isfinite(lo[j]): continue
        edges = np.linspace(lo[j], hi[j], 49)
        if cfg["mode"] == "radial":
            r = outer_radius(P, C[j, 0], C[j, 1], y, cfg["dy"], edges)
        else:
            r = outer_x(P, y, cfg["dy"], edges)
        mid = 0.5 * (edges[1:] + edges[:-1]); ok = np.isfinite(r)
        if cfg["mode"] == "cartphys":
            z0, z1 = cfg["zdom"]
            U.extend(((mid[ok] - 0.5 * (z0 + z1)) / (0.5 * (z1 - z0))).tolist())
        else:
            U.extend(((mid[ok] - 0.5 * (lo[j] + hi[j])) / (0.5 * (hi[j] - lo[j]))).tolist())
        V.extend([(y - cfg["ylo"]) / (cfg["yhi"] - cfg["ylo"]) * 2 - 1] * int(ok.sum()))
        R.extend(r[ok].tolist())
    U, V, R = np.array(U), np.array(V), np.array(R)

    def build_and_score(du, dv):
        coef, res, w = pf.robust_fit(U, V, R, du, dv)
        gu, gv = np.meshgrid(np.linspace(-1, 1, 60), np.linspace(-1, 1, 60), indexing="ij")
        rr = pf.evaluate(coef, gu.ravel(), gv.ravel(), du, dv)
        yv = cfg["ylo"] + (gv.ravel() + 1) / 2 * (cfg["yhi"] - cfg["ylo"])
        jj = np.clip(((yv - ys[0]) / cfg["dy"]).astype(int), 0, len(ys) - 1)
        q = 0.5 * (lo[jj] + hi[jj]) + gu.ravel() * 0.5 * (hi[jj] - lo[jj])
        if cfg["mode"] == "cartphys":
            z0, z1 = cfg["zdom"]
            un = (q - 0.5 * (z0 + z1)) / (0.5 * (z1 - z0))
            rr = pf.evaluate(coef, un, gv.ravel(), du, dv)
        if cfg["mode"] == "radial":
            pts = np.stack([C[jj, 0] + rr * np.cos(np.radians(q)), yv,
                            C[jj, 1] + rr * np.sin(np.radians(q))], 1)
        else:
            pts = np.stack([rr, yv, q], 1)
        return coef, res, w, pf.grid_waviness(pts)

    if SWEEP:
        print(f"--- {name} degree sweep (n={len(R)}) ---")
        print(f"{'du':>3s} {'dv':>3s} {'res_rms_mm':>11s} {'res_p95_mm':>11s} {'outl%':>6s} {'grid_wav_rms_mm':>16s}")
        for du in (5, 7, 9, 11):
            for dv in (3, 5):
                coef, res, w, gw = build_and_score(du, dv)
                r0 = pf.fit_report(res, w, name)
                print(f"{du:3d} {dv:3d} {r0['res_rms_mm']:11.3f} {r0['res_p95_mm']:11.3f} "
                      f"{r0['outlier_pct']:6.2f} {gw['wav_rms_mm']:16.4f}")
    coef, res, w, gw = build_and_score(cfg["du"], cfg["dv"])
    rp = pf.fit_report(res, w, name); rp["grid_waviness"] = gw
    rp["mode"] = cfg["mode"]; rp["du"], rp["dv"] = cfg["du"], cfg["dv"]
    rep[name] = rp
    np.savez(f"measurements/fit_{name}.npz", coef=coef, ys=ys, C=C, lo=lo, hi=hi,
             du=cfg["du"], dv=cfg["dv"], ylo=cfg["ylo"], yhi=cfg["yhi"], mode=cfg["mode"],
             c_lo=c_lo, c_hi=c_hi, c_cx=c_cx, c_cz=c_cz,
             zdom=np.array(cfg.get("zdom", (-1.0, 1.0))))
json.dump(rep, open(OUT, "w"), indent=1)
for k in ("bumper", "hatch_low", "hatch_surr"):
    print(k, json.dumps({kk: rep[k][kk] for kk in ("res_rms_mm","res_p95_mm","res_max_mm","outlier_pct","grid_waviness")}))
