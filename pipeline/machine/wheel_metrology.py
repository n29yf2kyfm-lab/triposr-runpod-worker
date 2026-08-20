#!/usr/bin/env python3
"""wheel_metrology.py — GATE 6 measuring instrument: wheels, tyres, grounding.

This module MEASURES and DECIDES NOTHING ELSE. It repairs nothing (see
`wheel_ground_op.py` for the repair operator) and it renders nothing (see
`wheel_evidence.py`). Its only job is to turn a GLB into defensible numbers
with a stated method and a stated uncertainty, so a human can accept or
reject each of the owner's Gate-6 acceptance criteria on evidence.

WHY IT IS GEOMETRIC AND NOT NAME-BASED
--------------------------------------
CLAUDE.md records, repeatedly, that material NAMES are not a witness: the
render worker repaints tyres heuristically, `paintMaterialNames` is Blender's
name space rather than the glTF's, and a glTF tyre probe scored 0/8 recall
against ground truth. On this car the binding is measurably wrong in the
other direction too: `Rim_Alloy` covers most of the tyre while `Tyre_Rubber`
is a thin outer ring, and BOTH also carry the front bumper's lower grille.

So names are used ONLY to seed a search. Every number below is measured from
geometry, from ALL scene meshes inside the fitted cylinder, and the seed is
discarded once the fit converges. If the name seed finds nothing usable the
detector falls back to a radius-band symmetry vote that uses no names at all.

THE ONE DISCRIMINATOR THAT MAKES THIS WORK: ANGULAR COVERAGE
------------------------------------------------------------
A wheel arch, a liner, a brake caliper and a melt sheet all produce dense
bands of points at a roughly constant distance from the axle, so "the densest
radius band" finds the arch as happily as the tyre. A TYRE is the only thing
in a wheel well that wraps the axle through a full 360 degrees. Every radius
band considered here must therefore cover >= `min_coverage` of the angular
bins around the axle before it can be called the tread. That single test is
what keeps the arch lip, the liner and the fender out of the radius fit.

WHAT "NOT MEASURABLE" MEANS HERE
--------------------------------
Toe and camber are angles of the wheel's axis of revolution. They exist only
if the wheel IS a body of revolution that can be separated from the body
shell. On a fused or melted mesh it is not, and the honest report is
NOT MEASURABLE WITHOUT SEPARATION, not a fabricated 0.0 degrees. Every angle
this module reports carries a bootstrap standard error, and the verdict is
downgraded to `not_measurable` when that standard error is worse than the
tolerance being tested against. A number tighter than its own instrument is
not evidence.

FRAME
-----
Axes are resolved, never assumed (CLAUDE.md trap: "a confidently wrong front
is worse than an honest undetermined"). `up` is the axis whose minimum sits
on the ground plane and whose extent is smallest of the two non-length axes;
`length` is the largest extent; `lateral` is the remaining one. Nose sign is
taken from the spec, from an explicit flag, or from the bonnet test (the nose
end of a car carries a long, low, thin skin panel; the tail carries a tall
one). Corner labels FL/FR/RL/RR are only emitted when the nose is resolved;
otherwise the corners are labelled neutrally A/B/C/D and the report says so.

Run:
    python3 wheel_metrology.py <car.glb> [--spec specs/vw_golf_mk8.json]
                               [--json out.json] [--nose +|-|auto]
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys

import numpy as np

try:                                            # optional: spec loader
    from carspec import CarSpec                 # noqa: F401
except Exception:                               # pragma: no cover
    CarSpec = None

# ------------------------------------------------------------------ tunables
DEFAULTS = dict(
    # Fraction of the angular bins around the axle a radius band must occupy
    # before it can be called the tread. 0.85 passes a real tyre (which is
    # 1.00 minus sampling gaps) and rejects an arch lip (~0.5 at best).
    min_coverage=0.85,
    n_theta=72,                 # angular bins for the coverage test
    band_rel=0.030,             # tread band half-width, as a fraction of R
    seed_names=("tyre", "tire", "rim", "wheel", "rubber", "alloy",
                "hub", "disc", "caliper"),
    # A seed cluster is only disc-like if its extents in the length/up plane
    # agree with each other and dominate its lateral extent. The front bumper
    # grille that shares the tyre material fails this by a factor of ten.
    disc_ratio_max=1.60,        # max(ext_len, ext_up) / min(ext_len, ext_up)
    disc_lat_max=1.05,          # ext_lat / min(ext_len, ext_up)
    boot_n=64,                  # bootstrap resamples for angle uncertainty
    boot_frac=0.60,
)

# Acceptance thresholds — the owner's Gate-6 numbers. Data, not logic.
TOL = dict(
    radius_spread_m=0.0010,     # "identical wheel radius across all four"
    width_spread_m=0.0020,      # "identical wheel width across all four"
    hub_symmetry_m=0.0020,      # "hub symmetry <= 2 mm"
    toe_deg=0.10,               # "toe within +-0.1 degrees"
    camber_deg=0.10,            # "camber within +-0.1 degrees"
    ground_m=0.0010,            # "tyre bottom at ground +-1 mm"
    fender_out_max_m=0.0050,    # "no more than 5 mm outside the fender"
    fender_in_pref_m=(0.0050, 0.0100),   # "preferably 5-10 mm INSIDE"
    track_m=0.0100,             # vs published track, when a spec supplies it
)


# ------------------------------------------------------------------- loading
def load_points(path):
    """Return {mesh_name: (V_world, F)} with node transforms applied.

    trimesh's `scene.geometry` is in LOCAL coordinates. Every node in this
    car happens to be identity, but a sibling gate may re-parent the wheels,
    so the transform is applied rather than assumed away.
    """
    import trimesh
    sc = trimesh.load(path, force="scene")
    out = {}
    for node in sc.graph.nodes_geometry:
        T, gname = sc.graph[node]
        g = sc.geometry[gname]
        V = np.asarray(g.vertices, float)
        if not np.allclose(T, np.eye(4)):
            V = V @ np.asarray(T)[:3, :3].T + np.asarray(T)[:3, 3]
        out[node] = (V, np.asarray(g.faces))
    return out, sc


# --------------------------------------------------------------------- frame
def resolve_frame(meshes, nose="auto", spec=None):
    """Resolve (length, lateral, up) axis indices and the nose sign.

    Returns dict with keys li, ti, ui (axis indices), nose (+1/-1/0) and the
    evidence for each choice. nose == 0 means undetermined; corner labels are
    then neutral.
    """
    V = np.vstack([v for v, _ in meshes.values()])
    lo, hi = V.min(0), V.max(0)
    ext = hi - lo
    li = int(np.argmax(ext))
    rest = [i for i in range(3) if i != li]
    # The up axis is the one whose minimum sits on the ground: a car standing
    # on a ground plane has min(up) ~ 0 relative to its own extent, while the
    # lateral axis straddles zero. Tie-break on smaller extent (cars are wider
    # than they are tall).
    def ground_score(i):
        return abs(lo[i]) / max(ext[i], 1e-9)
    ui = min(rest, key=lambda i: (round(ground_score(i), 3), ext[i]))
    ti = [i for i in rest if i != ui][0]

    ev = dict(extents=[float(e) for e in ext],
              ground_score={str(i): float(ground_score(i)) for i in rest})

    ns, ns_ev = 0, "spec/flag"
    if nose in ("+", "-"):
        ns = 1 if nose == "+" else -1
    elif spec and spec.get("nose_sign") in (1, -1):
        ns = int(spec["nose_sign"])
    else:
        # Bonnet test: slice the centreline skin into the two end thirds and
        # compare the vertical THICKNESS of the outer skin. A bonnet is a
        # thin, low panel; a tailgate spans roof to bumper.
        c = (lo + hi) / 2
        near = np.abs(V[:, ti] - c[ti]) < 0.25 * ext[ti]
        span = []
        for sgn in (+1, -1):
            m = near & (np.sign(V[:, li] - c[li]) == sgn) & \
                (np.abs(V[:, li] - c[li]) > 0.34 * ext[li])
            span.append(float(np.ptp(V[m, ui])) if m.sum() > 50 else np.nan)
        pos, neg = span
        if np.isfinite(pos) and np.isfinite(neg) and \
                abs(pos - neg) > 0.12 * ext[ui]:
            ns = -1 if pos > neg else 1     # the TALL end is the tail
            ns_ev = f"bonnet test: end-skin vertical span +={pos:.3f} -={neg:.3f}"
        else:
            ns_ev = f"bonnet test inconclusive: +={pos:.3f} -={neg:.3f}"
    ev["nose_evidence"] = ns_ev
    return dict(li=li, ti=ti, ui=ui, nose=ns, ground=float(lo[ui]),
                lo=[float(x) for x in lo], hi=[float(x) for x in hi],
                evidence=ev)


# ------------------------------------------------------------------ seeding
def _clusters_1d(x, gap):
    """Split sorted-able 1-D values into runs separated by more than `gap`."""
    o = np.argsort(x)
    xs = x[o]
    cuts = np.where(np.diff(xs) > gap)[0]
    groups, start = [], 0
    for c in list(cuts) + [len(xs) - 1]:
        groups.append(o[start:c + 1])
        start = c + 1
    return groups


def seed_corners(meshes, fr, cfg):
    """Four wheel seeds as (length, up, lateral) centres.

    Strategy A (names): union the meshes whose name looks wheel-ish, split by
    lateral sign, then cluster along the length axis and keep clusters that
    pass the disc-likeness test. Strategy B (no names): a radius-band
    symmetry vote over a coarse grid of candidate axles.
    """
    li, ti, ui = fr["li"], fr["ti"], fr["ui"]
    V = np.vstack([v for v, _ in meshes.values()])
    H = fr["hi"][ui] - fr["lo"][ui]

    named = [v for n, (v, _) in meshes.items()
             if any(k in n.lower() for k in cfg["seed_names"])]
    seeds, how = [], "names+disc-likeness"
    if named:
        P = np.vstack(named)
        P = P[P[:, ui] < fr["lo"][ui] + 0.60 * H]
        for sgn in (+1, -1):
            S = P[np.sign(P[:, ti] - 0.0) == sgn]
            if len(S) < 200:
                continue
            for idx in _clusters_1d(S[:, li], gap=0.15):
                if len(idx) < 200:
                    continue
                C = S[idx]
                e = C.max(0) - C.min(0)
                a, b = e[li], e[ui]
                lo_, hi_ = min(a, b), max(a, b)
                if lo_ < 1e-6:
                    continue
                if hi_ / lo_ > cfg["disc_ratio_max"]:
                    continue
                if e[ti] / lo_ > cfg["disc_lat_max"]:
                    continue
                seeds.append(dict(l=float(C[:, li].mean()),
                                  u=float((C[:, ui].min() + C[:, ui].max()) / 2),
                                  t=float(np.median(C[:, ti])),
                                  r0=float(hi_ / 2), n=int(len(C))))
    if len(seeds) < 4:
        seeds, how = vote_corners(V, fr, cfg), "radius-band symmetry vote"
    # keep the four strongest, one per (length-cluster x lateral-sign)
    seeds.sort(key=lambda s: -s["n"])
    keep = []
    for s in seeds:
        if all(abs(s["l"] - k["l"]) > 0.40 or np.sign(s["t"]) != np.sign(k["t"])
               for k in keep):
            keep.append(s)
        if len(keep) == 4:
            break
    return keep, how


def vote_corners(V, fr, cfg):
    """Name-free fallback: score candidate axles by tread-band angular coverage."""
    li, ti, ui = fr["li"], fr["ti"], fr["ui"]
    H = fr["hi"][ui] - fr["lo"][ui]
    L = fr["hi"][li] - fr["lo"][li]
    out = []
    for sgn in (+1, -1):
        S = V[(np.sign(V[:, ti]) == sgn) &
              (np.abs(V[:, ti]) > 0.45 * max(abs(fr["lo"][ti]), fr["hi"][ti])) &
              (V[:, ui] < fr["lo"][ui] + 0.60 * H)]
        if len(S) < 500:
            continue
        best = []
        ls = np.arange(fr["lo"][li] + 0.10 * L, fr["hi"][li] - 0.10 * L, 0.03)
        us = np.arange(fr["lo"][ui] + 0.10 * H, fr["lo"][ui] + 0.45 * H, 0.03)
        for lc in ls:
            for uc in us:
                dl, du = S[:, li] - lc, S[:, ui] - uc
                r = np.hypot(dl, du)
                near = r < 0.45 * H
                if near.sum() < 200:
                    continue
                R, cov, _ = tread_radius(r[near],
                                         np.arctan2(du[near], dl[near]), cfg)
                if R is None:
                    continue
                best.append((cov * near.sum(), lc, uc, R, int(near.sum())))
        best.sort(reverse=True)
        picked = []
        for sc_, lc, uc, R, n in best:
            if all(abs(lc - p[1]) > 0.60 for p in picked):
                picked.append((sc_, lc, uc, R, n))
            if len(picked) == 2:
                break
        for sc_, lc, uc, R, n in picked:
            out.append(dict(l=float(lc), u=float(uc),
                            t=float(np.median(S[:, ti])), r0=float(R), n=n))
    return out


# ------------------------------------------------------------- tread finding
def tread_radius(r, th, cfg):
    """Largest radius band that wraps the axle. Returns (R, coverage, mask).

    Walks candidate radii downward from the outside. The first band whose
    angular coverage clears `min_coverage` is the tyre tread: nothing else in
    a wheel well goes all the way round.
    """
    if len(r) < 100:
        return None, 0.0, None
    nth = cfg["n_theta"]
    tb = ((th + np.pi) / (2 * np.pi) * nth).astype(int) % nth
    hi = float(np.percentile(r, 99.9))
    lo = 0.35 * hi
    best = (None, 0.0, None)
    for R in np.arange(hi, lo, -0.002):
        half = cfg["band_rel"] * R
        m = np.abs(r - R) <= half
        if m.sum() < 60:
            continue
        cov = len(np.unique(tb[m])) / nth
        if cov >= cfg["min_coverage"]:
            return float(R), float(cov), m
        if cov > best[1]:
            best = (float(R), float(cov), m)
    return best


# --------------------------------------------------------------- cylinder fit
def _axis_from_angles(base, a, b):
    """Perturb a unit `base` axis by two small angles in its own null space."""
    n = base / np.linalg.norm(base)
    tmp = np.array([1.0, 0, 0]) if abs(n[0]) < 0.9 else np.array([0, 1.0, 0])
    e1 = np.cross(n, tmp); e1 /= np.linalg.norm(e1)
    e2 = np.cross(n, e1)
    v = n + a * e1 + b * e2
    return v / np.linalg.norm(v)


def fit_cylinder(P, c0, a0, R0, iters=4, cfg=DEFAULTS):
    """Least-squares axis+radius of the tread band, re-selecting the band
    each iteration so the fit is not anchored to the seed.

    Returns dict(centre, axis, R, band_mask, rms, n).
    """
    from scipy.optimize import least_squares
    c, a, R = np.asarray(c0, float), np.asarray(a0, float), float(R0)
    a = a / np.linalg.norm(a)
    mask = None
    for _ in range(iters):
        d = P - c
        proj = d - np.outer(d @ a, a)
        r = np.linalg.norm(proj, axis=1)
        # angle within the plane perpendicular to the axis
        tmp = np.array([1.0, 0, 0]) if abs(a[0]) < 0.9 else np.array([0, 1.0, 0])
        e1 = np.cross(a, tmp); e1 /= np.linalg.norm(e1)
        e2 = np.cross(a, e1)
        th = np.arctan2(proj @ e2, proj @ e1)
        Rn, cov, m = tread_radius(r, th, cfg)
        if Rn is None:
            break
        R, mask = Rn, m
        Q = P[m]

        def res(p):
            ax = _axis_from_angles(a, p[0], p[1])
            cc = c + p[2] * e1 + p[3] * e2
            dd = Q - cc
            rr = np.linalg.norm(dd - np.outer(dd @ ax, ax), axis=1)
            return rr - p[4]

        s = least_squares(res, [0.0, 0.0, 0.0, 0.0, R], method="lm",
                          max_nfev=4000)
        a = _axis_from_angles(a, s.x[0], s.x[1])
        c = c + s.x[2] * e1 + s.x[3] * e2
        R = float(s.x[4])
        rms = float(np.sqrt(np.mean(s.fun ** 2)))
    if mask is None:
        return None
    d = P - c
    lat = d @ a
    return dict(centre=c, axis=a, R=R, mask=mask, rms=rms,
                n=int(mask.sum()), lat=lat, coverage=cov)


def bootstrap_axis(P, fit, cfg):
    """Standard error of the fitted axis direction, in degrees.

    The tolerance being tested (0.1 deg) is tighter than most generated
    wheels are round, so the instrument has to state its own precision.
    """
    from scipy.optimize import least_squares
    Q = P[fit["mask"]]
    a0, c0 = fit["axis"], fit["centre"]
    tmp = np.array([1.0, 0, 0]) if abs(a0[0]) < 0.9 else np.array([0, 1.0, 0])
    e1 = np.cross(a0, tmp); e1 /= np.linalg.norm(e1)
    e2 = np.cross(a0, e1)
    rng = np.random.default_rng(0)
    k = max(200, int(cfg["boot_frac"] * len(Q)))
    axes = []
    for _ in range(cfg["boot_n"]):
        S = Q[rng.choice(len(Q), size=min(k, len(Q)), replace=True)]

        def res(p):
            ax = _axis_from_angles(a0, p[0], p[1])
            cc = c0 + p[2] * e1 + p[3] * e2
            dd = S - cc
            rr = np.linalg.norm(dd - np.outer(dd @ ax, ax), axis=1)
            return rr - p[4]

        s = least_squares(res, [0.0, 0.0, 0.0, 0.0, fit["R"]], method="lm",
                          max_nfev=800)
        axes.append(_axis_from_angles(a0, s.x[0], s.x[1]))
    A = np.array(axes)
    A *= np.sign(A @ a0)[:, None]
    mean = A.mean(0); mean /= np.linalg.norm(mean)
    ang = np.degrees(np.arccos(np.clip(A @ mean, -1, 1)))
    return float(np.sqrt(np.mean(ang ** 2)))


# ---------------------------------------------------------------- the measure
def measure(path, spec=None, nose="auto", cfg=None, bootstrap=True):
    cfg = dict(DEFAULTS, **(cfg or {}))
    meshes, sc = load_points(path)
    fr = resolve_frame(meshes, nose=nose, spec=spec)
    li, ti, ui = fr["li"], fr["ti"], fr["ui"]
    V = np.vstack([v for v, _ in meshes.values()])

    seeds, how = seed_corners(meshes, fr, cfg)
    wheels = []
    for s in seeds:
        c0 = np.zeros(3)
        c0[li], c0[ui], c0[ti] = s["l"], s["u"], s["t"]
        a0 = np.zeros(3); a0[ti] = 1.0
        # Draw from EVERY mesh inside a generous cylinder — the fit must not
        # inherit the material binding it was seeded from.
        rad = np.hypot(V[:, li] - c0[li], V[:, ui] - c0[ui])
        box = (rad < 1.55 * s["r0"]) & (np.abs(V[:, ti] - c0[ti]) < 1.10 * s["r0"])
        P = V[box]
        if len(P) < 300:
            continue
        f = fit_cylinder(P, c0, a0, s["r0"], cfg=cfg)
        if f is None:
            continue
        f["seed"] = s
        f["points"] = P
        wheels.append(f)

    # ---- corner labels
    for w in wheels:
        c = w["centre"]
        w["side"] = "+" if c[ti] > 0 else "-"
    if len(wheels) == 4:
        order = sorted(range(4), key=lambda i: wheels[i]["centre"][li])
        lo_idx = set(order[:2])          # the two smallest length coords
        for i, w in enumerate(wheels):
            w["axle"] = "lo" if i in lo_idx else "hi"
    for w in wheels:
        if fr["nose"] == 0:
            w["corner"] = ("A" if w.get("axle") == "lo" else "C") + w["side"]
        else:
            front = (w.get("axle") == "lo") == (fr["nose"] < 0)
            # +lateral is the car's LEFT when looking along the nose direction
            left = (w["centre"][ti] > 0) == (fr["nose"] < 0)
            w["corner"] = ("F" if front else "R") + ("L" if left else "R")

    # ---- per-wheel numbers
    up = np.zeros(3); up[ui] = 1.0
    lenv = np.zeros(3); lenv[li] = 1.0
    latv = np.zeros(3); latv[ti] = 1.0
    ground = 0.0 if abs(fr["ground"]) < 5e-3 else fr["ground"]

    rows = []
    for w in wheels:
        a = w["axis"] * (1 if w["axis"][ti] > 0 else -1)
        c = w["centre"]
        tread = w["points"][w["mask"]]
        lat = (tread - c) @ a
        # tyre width = full lateral span of the tread band, trimmed
        wlo, whi = np.percentile(lat, [0.5, 99.5])
        width = float(whi - wlo)
        # outer sidewall: widest |lateral| anywhere on the tyre carcass
        d = w["points"] - c
        rr = np.linalg.norm(d - np.outer(d @ a, a), axis=1)
        car = w["points"][(rr > 0.62 * w["R"]) & (rr < 1.02 * w["R"])]
        out_lat = float(np.percentile(np.abs(car[:, ti]), 99.0))

        # toe: axis rotated about UP, measured against the pure lateral axis
        toe = math.degrees(math.atan2(a[li], abs(a[ti])))
        # camber: NEGATIVE camber leans the wheel top inboard. Sign is taken
        # relative to the car's outboard direction for this corner.
        outw = 1.0 if c[ti] > 0 else -1.0
        camber = math.degrees(math.asin(np.clip(a[ui] * outw *
                                                (1 if a[ti] * outw > 0 else -1),
                                                -1, 1)))
        se = bootstrap_axis(w["points"], w, cfg) if bootstrap else float("nan")

        rows.append(dict(
            corner=w["corner"], side=w["side"], axle=w.get("axle"),
            centre=[float(x) for x in c],
            hub_length=float(c[li]), hub_up=float(c[ui]), hub_lat=float(c[ti]),
            axis=[float(x) for x in a],
            radius_m=float(w["R"]), width_m=width,
            tread_points=int(w["n"]), tread_coverage=float(w["coverage"]),
            fit_rms_m=float(w["rms"]),
            bottom_m=float(c[ui] - w["R"] - ground),
            toe_deg=float(toe), camber_deg=float(camber),
            axis_se_deg=float(se),
            outer_sidewall_lat=out_lat,
        ))
    rows.sort(key=lambda r: (r["corner"]))

    out = dict(file=os.path.abspath(path), frame=fr, seed_method=how,
               n_wheels=len(rows), wheels=rows,
               ground_plane=float(ground),
               axes=dict(length=li, lateral=ti, up=ui))
    _derive(out, V, fr, spec, cfg)
    return out


def _derive(out, V, fr, spec, cfg):
    """Axle-level and body-relative numbers."""
    li, ti, ui = fr["li"], fr["ti"], fr["ui"]
    rows = out["wheels"]
    by = {r["corner"]: r for r in rows}
    out["axles"] = {}
    for pre in ("F", "R", "A", "C"):
        L, Rt = by.get(pre + "L"), by.get(pre + "R")
        if pre in ("A", "C"):
            L, Rt = by.get(pre + "+"), by.get(pre + "-")
        if not (L and Rt):
            continue
        out["axles"][pre] = dict(
            track_m=float(abs(L["hub_lat"] - Rt["hub_lat"])),
            hub_lat_asym_m=float(abs(abs(L["hub_lat"]) - abs(Rt["hub_lat"]))),
            hub_long_asym_m=float(abs(L["hub_length"] - Rt["hub_length"])),
            hub_up_asym_m=float(abs(L["hub_up"] - Rt["hub_up"])),
            radius_diff_m=float(abs(L["radius_m"] - Rt["radius_m"])),
            total_toe_deg=float(L["toe_deg"] - Rt["toe_deg"]),
        )
    if len(rows) == 4:
        rr = [r["radius_m"] for r in rows]
        ww = [r["width_m"] for r in rows]
        out["spread"] = dict(radius_m=float(max(rr) - min(rr)),
                             width_m=float(max(ww) - min(ww)),
                             radius_mean_m=float(np.mean(rr)),
                             width_mean_m=float(np.mean(ww)))
        fl = [r for r in rows if r["corner"][0] in "FA"]
        rl = [r for r in rows if r["corner"][0] in "RC"]
        if fl and rl:
            out["wheelbase_m"] = float(abs(np.mean([r["hub_length"] for r in fl])
                                           - np.mean([r["hub_length"] for r in rl])))
            # rigid pitch implied by the hub line
            dl = np.mean([r["hub_length"] for r in fl]) - \
                np.mean([r["hub_length"] for r in rl])
            du = np.mean([r["hub_up"] for r in fl]) - \
                np.mean([r["hub_up"] for r in rl])
            out["hub_line_pitch_deg"] = float(math.degrees(math.atan2(du, dl)))

    # ---- fender relationship + arch intersection, per wheel
    body = None
    for name, (v, _) in out.get("_meshes", {}).items():        # pragma: no cover
        pass
    out["fender"] = {}
    return out


def fender_and_arch(path, m, cfg=None):
    """Second pass: fender lip position and arch intersection, per wheel.

    Kept separate because it needs the SKIN meshes distinguished from the
    wheel, which the fit does not need. The lip is the outermost lateral
    point of the body skin in the annulus just outside the tyre, in the upper
    half of the arch; a percentile is used so one stray vertex cannot move it.
    """
    cfg = dict(DEFAULTS, **(cfg or {}))
    meshes, _ = load_points(path)
    li, ti, ui = m["axes"]["length"], m["axes"]["lateral"], m["axes"]["up"]
    skin = {n: v for n, (v, _) in meshes.items()
            if not any(k in n.lower() for k in cfg["seed_names"])}
    if not skin:
        return m
    S = np.vstack(list(skin.values()))
    for r in m["wheels"]:
        c = np.array(r["centre"]); a = np.array(r["axis"]); R = r["radius_m"]
        d = S - c
        rad = np.linalg.norm(d - np.outer(d @ a, a), axis=1)
        lat = d @ a
        outw = 1.0 if r["hub_lat"] > 0 else -1.0
        up_half = (S[:, ui] - c[ui]) > -0.15 * R
        lip = (rad > 1.00 * R) & (rad < 1.30 * R) & up_half & \
              (np.abs(lat) < 1.20 * r["width_m"])
        if lip.sum() > 30:
            lip_lat = float(np.percentile(np.abs(S[lip][:, ti]), 98.0))
        else:
            lip_lat = float("nan")
        r["fender_lip_lat"] = lip_lat
        # positive = tyre proud of the fender, negative = tucked inside
        r["sidewall_vs_fender_m"] = float(r["outer_sidewall_lat"] - lip_lat)
        r["fender_lip_points"] = int(lip.sum())
        # arch intersection: skin inside the tyre swept volume
        inside = (rad < 0.985 * R) & (np.abs(lat) < 0.48 * r["width_m"])
        r["arch_intersect_points"] = int(inside.sum())
        if inside.sum():
            r["arch_intersect_depth_m"] = float(R - rad[inside].min())
        else:
            r["arch_intersect_depth_m"] = 0.0
        # contact patch: tyre geometry within 2 mm of the ground plane
        W = np.vstack([v for n, (v, _) in meshes.items()
                       if any(k in n.lower() for k in cfg["seed_names"])]) \
            if any(any(k in n.lower() for k in cfg["seed_names"]) for n in meshes) \
            else None
        r["contact_patch"] = _contact(W if W is not None else S, c, a, R,
                                      r["width_m"], m["ground_plane"], li, ti, ui)
    return m


def _contact(P, c, a, R, W, ground, li, ti, ui):
    d = P - c
    rad = np.linalg.norm(d - np.outer(d @ a, a), axis=1)
    lat = d @ a
    near = (rad > 0.90 * R) & (np.abs(lat) < 0.60 * W) & \
           (P[:, ui] < ground + 0.004)
    if near.sum() < 3:
        return dict(points=int(near.sum()), note="no geometry within 4 mm of ground")
    Q = P[near]
    return dict(points=int(near.sum()),
                length_span_m=float(np.ptp(Q[:, li])),
                lat_span_m=float(np.ptp(Q[:, ti])),
                centre_offset_long_m=float(Q[:, li].mean() - c[li]),
                centre_offset_lat_m=float(Q[:, ti].mean() - c[ti]))


# ------------------------------------------------------------------- verdicts
def _v(ok, measured, thr, method, note=""):
    return dict(verdict=("PASS" if ok else "FAIL"), measured=measured,
                threshold=thr, method=method, note=note)


def grade(m, spec=None):
    """Turn measurements into PASS / FAIL / NOT MEASURABLE per criterion."""
    g = {}
    rows = m["wheels"]
    n = len(rows)
    if n != 4:
        g["wheels_found"] = dict(verdict="BLOCKED", measured=n, threshold=4,
                                 method="geometric cylinder fit",
                                 note="fewer than four separable wheels")
        return g
    sp = m.get("spread", {})
    g["radius_identical"] = _v(
        sp.get("radius_m", 9) <= TOL["radius_spread_m"],
        round(sp.get("radius_m", float("nan")), 6), TOL["radius_spread_m"],
        "max-min of the four fitted tread radii (cylinder LSQ, 360-deg band)")
    g["width_identical"] = _v(
        sp.get("width_m", 9) <= TOL["width_spread_m"],
        round(sp.get("width_m", float("nan")), 6), TOL["width_spread_m"],
        "max-min of the lateral span of the tread band (0.5-99.5 pct)")

    for pre, ax in m["axles"].items():
        g[f"track_{pre}"] = dict(verdict="MEASURED", measured=round(ax["track_m"], 5),
                                 threshold=None,
                                 method="lateral distance between the two fitted hub centres of this axle, measured independently of the other axle")
        if spec:
            key = "track_front_m" if pre in ("F", "A") else "track_rear_m"
            pub = (spec.get("dimensions", {}).get(key) or {}).get("value")
            if pub:
                g[f"track_{pre}"].update(
                    verdict=("PASS" if abs(ax["track_m"] - pub) <= TOL["track_m"]
                             else "FAIL"),
                    threshold=f"{pub} +-{TOL['track_m']}", published=pub)
        g[f"hub_symmetry_{pre}"] = _v(
            max(ax["hub_lat_asym_m"], ax["hub_long_asym_m"],
                ax["hub_up_asym_m"]) <= TOL["hub_symmetry_m"],
            dict(lateral=round(ax["hub_lat_asym_m"], 5),
                 longitudinal=round(ax["hub_long_asym_m"], 5),
                 vertical=round(ax["hub_up_asym_m"], 5)),
            TOL["hub_symmetry_m"],
            "left/right hub centre mismatch on this axle, in all three axes")

    for r in rows:
        cn = r["corner"]
        se = r["axis_se_deg"]
        for key, tol in (("toe", TOL["toe_deg"]), ("camber", TOL["camber_deg"])):
            val = r[f"{key}_deg"]
            if not np.isfinite(se) or se > tol:
                g[f"{key}_{cn}"] = dict(
                    verdict="NOT MEASURABLE", measured=round(val, 4),
                    threshold=f"+-{tol}",
                    method="axis of revolution from a least-squares cylinder fit to the tread band",
                    note=f"bootstrap SE of the fitted axis is {se:.3f} deg, "
                         f"which is larger than the {tol} deg tolerance: the "
                         f"mesh is not round enough to defend a number this tight")
            else:
                g[f"{key}_{cn}"] = _v(abs(val) <= tol, round(val, 4), f"+-{tol}",
                                      "cylinder-fit axis of revolution",
                                      f"axis SE {se:.3f} deg")
        g[f"ground_{cn}"] = _v(
            abs(r["bottom_m"]) <= TOL["ground_m"], round(r["bottom_m"], 5),
            f"+-{TOL['ground_m']}",
            "fitted hub height minus fitted tread radius, minus the ground plane")
        d = r.get("sidewall_vs_fender_m")
        if d is None or not np.isfinite(d):
            g[f"fender_{cn}"] = dict(verdict="NOT MEASURABLE", measured=None,
                                     threshold=None,
                                     method="body skin in the annulus just outside the tread",
                                     note="no body skin found at this arch")
        else:
            ok = d <= TOL["fender_out_max_m"]
            pref = -TOL["fender_in_pref_m"][1] <= d <= -TOL["fender_in_pref_m"][0]
            g[f"fender_{cn}"] = _v(
                ok, round(d, 5),
                f"<= +{TOL['fender_out_max_m']} (preferred -0.010..-0.005)",
                "98th-pct lateral of the outer tyre carcass minus 98th-pct lateral of the body skin at the arch lip",
                "within preferred band" if pref else "outside preferred band")
        g[f"arch_clear_{cn}"] = _v(
            r.get("arch_intersect_points", 0) == 0,
            dict(points=r.get("arch_intersect_points"),
                 depth_m=round(r.get("arch_intersect_depth_m", 0), 5)),
            0, "body-skin vertices inside the tyre swept volume")
        cp = r.get("contact_patch", {})
        g[f"contact_{cn}"] = dict(
            verdict=("PASS" if cp.get("points", 0) >= 3 and
                     abs(cp.get("centre_offset_long_m", 9)) <= 0.01 else "FAIL"),
            measured=cp, threshold=">=3 tyre vertices within 4 mm of ground, centred under the hub within 10 mm",
            method="tyre carcass vertices within 4 mm of the ground plane")

    g["rim_design_trim"] = dict(
        verdict="NOT TESTED", measured=None, threshold=None,
        method="none available",
        note="the owner did not state a year or trim for this Golf Mk8, so "
             "there is no trim-specific rim design to compare against. This "
             "project's accuracy rule forbids inventing a trim to test one.")
    return g


# ------------------------------------------------------------------------ CLI
def load_spec(p):
    if not p or p == "-":
        return None
    with open(p) as f:
        return json.load(f)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("glb")
    ap.add_argument("--spec", default=None)
    ap.add_argument("--json", default=None)
    ap.add_argument("--nose", choices=["+", "-", "auto"], default="auto")
    ap.add_argument("--no-bootstrap", action="store_true")
    a = ap.parse_args()
    spec = load_spec(a.spec)
    m = measure(a.glb, spec=spec, nose=a.nose, bootstrap=not a.no_bootstrap)
    m = fender_and_arch(a.glb, m)
    m["gate6"] = grade(m, spec)
    m.pop("_meshes", None)
    txt = json.dumps(m, indent=1, default=float)
    if a.json:
        with open(a.json, "w") as f:
            f.write(txt)
        print("wrote", a.json)
    else:
        print(txt)
    bad = [k for k, v in m["gate6"].items() if v["verdict"] == "FAIL"]
    print("GATE6 FAIL:", len(bad), sorted(bad), file=sys.stderr)


if __name__ == "__main__":
    main()
