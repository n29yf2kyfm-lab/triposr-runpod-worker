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
    # before it can be called the tread. A real tyre scores 1.00 here; the
    # wrong local optima this detector must reject score 0.76-0.85, which is
    # why the bar sits at 0.88 and not lower.
    min_coverage=0.88,
    n_theta=72,                 # angular bins for the coverage test
    band_rel=0.030,             # tread band half-width, as a fraction of R
    # --- vote
    r_lo=0.18, r_hi=0.45, r_step=0.006,     # plausible car-tyre radius range
    r_seed=0.31,                # multi-start radius seed (refit immediately)
    vote_step=0.04, vote_pts=9000,
    out_slab_m=0.28,            # depth of the OUTBOARD slab the wheel lives in
    axle_min_sep_m=1.00,        # two axles are never closer than this
    # --- refine
    refine_iters=14, refine_band0=0.12, refine_band1=0.012,
    refine_decay=0.82, trim_pct=78,
    multistart_l=(-0.06, 0.0, 0.06), multistart_u=(-0.04, 0.0, 0.04),
    # --- slab scan
    slab_min_pts=200, width_pct=1.0,
    # --- uncertainty
    boot_n=48,                  # bootstrap resamples for angle uncertainty
    boot_frac=0.60,
    # names are used for NOTHING except splitting skin from wheel in the
    # fender pass, and even there only as a hint that is checked.
    seed_names=("tyre", "tire", "rim", "wheel", "rubber", "alloy",
                "hub", "disc", "caliper"),
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


# ------------------------------------------------------------------ detector
# The detector is deliberately NAME-FREE. It runs in three steps, each of
# which is checked before the next is trusted:
#
#   1. VOTE      a coarse scan for axle candidates, scored by "is there a
#                radius band here that wraps 360 degrees AND has emptiness
#                just outside it". A door panel scores zero on the second
#                half of that test even though it aces the first; that pair
#                is what separates a tyre from any flat dense sheet.
#   2. REFINE    a robust circle fit that sees ONLY the arc BELOW the axle.
#                Nothing but the tyre lives under the hub outboard of the
#                sill, so the fender, the arch lip and the liner cannot bias
#                the centre. Multi-start, because the loose basin around a
#                wheel has more than one local optimum and the wrong ones are
#                measurably worse (coverage 0.83 against 1.00).
#   3. SLAB      a scan across lateral slabs asking which of them still carry
#                a 360-degree band at the fitted radius. That run of slabs IS
#                the tyre, and its extent IS the section width. This is the
#                step that makes the wrong Rim_Alloy/Tyre_Rubber binding
#                irrelevant: the tread is found by where it is, not by what
#                it is called.


def _circfit(x, y):
    """Algebraic (Kasa) circle fit — the initialiser for the robust loop."""
    A = np.column_stack([x, y, np.ones(len(x))])
    b = x ** 2 + y ** 2
    c, *_ = np.linalg.lstsq(A, b, rcond=None)
    cx, cy = c[0] / 2, c[1] / 2
    return float(cx), float(cy), float(np.sqrt(max(c[2] + cx ** 2 + cy ** 2, 1e-9)))


def _coverage(theta, nth):
    if len(theta) == 0:
        return 0.0
    b = ((theta + np.pi) / (2 * np.pi) * nth).astype(int) % nth
    return len(np.unique(b)) / nth


def vote_axles(V, fr, cfg):
    """Coarse, name-free axle candidates. Returns up to 2 per lateral side."""
    li, ti, ui = fr["li"], fr["ti"], fr["ui"]
    H = fr["hi"][ui] - fr["lo"][ui]
    g0 = fr["lo"][ui]
    halfw = max(abs(fr["lo"][ti]), fr["hi"][ti])
    rlo, rhi, dr = cfg["r_lo"], cfg["r_hi"], cfg["r_step"]
    nth = cfg["n_theta"]
    nb = int((rhi - rlo) / dr) + 6
    rng = np.random.default_rng(0)
    out = []
    for sgn in (+1, -1):
        S = V[(np.sign(V[:, ti]) == sgn) &
              (np.abs(V[:, ti]) > halfw - cfg["out_slab_m"]) &
              (V[:, ui] < g0 + 0.60 * H)]
        if len(S) < 800:
            continue
        if len(S) > cfg["vote_pts"]:
            S = S[rng.choice(len(S), cfg["vote_pts"], replace=False)]
        res = []
        for lc in np.arange(fr["lo"][li] + 0.25, fr["hi"][li] - 0.25, cfg["vote_step"]):
            dl = S[:, li] - lc
            for uc in np.arange(g0 + 0.12, g0 + 0.52, cfg["vote_step"]):
                du = S[:, ui] - uc
                r = np.hypot(dl, du)
                m = (r >= rlo) & (r < rhi + 4 * dr)
                if m.sum() < 200:
                    continue
                ri = np.clip(((r[m] - rlo) / dr).astype(int), 0, nb - 1)
                tb = ((np.arctan2(du[m], dl[m]) + np.pi) / (2 * np.pi) *
                      nth).astype(int) % nth
                acc = np.zeros((nb, nth), bool)
                acc[ri, tb] = True
                cov = acc.sum(1) / nth
                for k in range(2, nb - 5):
                    ci = cov[k - 1:k + 1].mean()
                    co = cov[k + 2:k + 5].mean()
                    res.append((ci - co, ci, co, float(lc), float(uc),
                                float(rlo + k * dr)))
        res.sort(reverse=True)
        picked = []
        for sc_, ci, co, lc, uc, R in res:
            if all(abs(lc - p["l"]) > cfg["axle_min_sep_m"] for p in picked):
                picked.append(dict(l=lc, u=uc, r0=R, side=sgn, score=float(sc_),
                                   cov_in=float(ci), cov_out=float(co)))
            if len(picked) == 2:
                break
        out += picked
    return out


def refine_circle(V, fr, seed, cfg):
    """Robust circle fit on the BELOW-AXLE arc only. Returns None if it fails."""
    li, ti, ui = fr["li"], fr["ti"], fr["ui"]
    sgn = seed["side"]
    Vs = V[np.sign(V[:, ti]) == sgn]
    lat = np.abs(Vs[:, ti])
    lc, uc, R = seed["l"], seed["u"], seed["r0"]
    tout = np.nan
    for it in range(cfg["refine_iters"]):
        d = np.hypot(Vs[:, li] - lc, Vs[:, ui] - uc)
        inb = d < 1.25 * R
        if inb.sum() < 200:
            return None
        tout = float(np.percentile(lat[inb], 99.8))
        band = max(cfg["refine_band0"] * R * (cfg["refine_decay"] ** it),
                   cfg["refine_band1"] * R)
        m = (np.abs(d - R) <= band) & (lat >= tout - cfg["out_slab_m"]) & \
            (Vs[:, ui] < uc + 0.08 * R)          # BELOW the axle only
        if m.sum() < 120:
            break
        P = Vs[m]
        cx, cy, Rn = lc, uc, R
        for _ in range(3):
            cx, cy, Rn = _circfit(P[:, li], P[:, ui])
            res = np.abs(np.hypot(P[:, li] - cx, P[:, ui] - cy) - Rn)
            keep = res <= np.percentile(res, cfg["trim_pct"])
            if keep.sum() < 80:
                break
            P = P[keep]
        lc, uc, R = cx, cy, Rn
        if not (cfg["r_lo"] * 0.8 < R < cfg["r_hi"] * 1.2):
            return None
    d = np.hypot(Vs[:, li] - lc, Vs[:, ui] - uc)
    th = np.arctan2(Vs[:, ui] - uc, Vs[:, li] - lc)
    m = (np.abs(d - R) <= cfg["band_rel"] * R) & (lat >= tout - cfg["out_slab_m"])
    cov = _coverage(th[m], cfg["n_theta"])
    rms = float(np.sqrt(np.mean((d[m] - R) ** 2))) if m.sum() else float("nan")
    return dict(l=float(lc), u=float(uc), R=float(R), side=sgn,
                coverage=float(cov), n=int(m.sum()), rms=rms, t_out=tout)


def find_wheels(V, fr, cfg):
    """Vote -> multi-start refine -> keep the best fit per corner."""
    li, ti, ui = fr["li"], fr["ti"], fr["ui"]
    cands = vote_axles(V, fr, cfg)
    fits = []
    for c in cands:
        best = None
        for dl in cfg["multistart_l"]:
            for du in cfg["multistart_u"]:
                s = dict(c, l=c["l"] + dl, u=c["u"] + du, r0=cfg["r_seed"])
                f = refine_circle(V, fr, s, cfg)
                if f is None or f["coverage"] < cfg["min_coverage"]:
                    continue
                key = (round(f["coverage"], 2), f["n"], -f["rms"])
                if best is None or key > best[0]:
                    best = (key, f)
        if best:
            fits.append(best[1])
    # de-duplicate: two seeds on the same side may converge to one wheel
    keep = []
    for f in sorted(fits, key=lambda f: (-round(f["coverage"], 2), -f["n"])):
        if all(not (abs(f["l"] - k["l"]) < cfg["axle_min_sep_m"] and
                    f["side"] == k["side"]) for k in keep):
            keep.append(f)
    return keep


def slab_tread(V, fr, fit, cfg):
    """The tyre's lateral band, and the tread point set the axis is fitted to.

    THE WIDTH IS MEASURED ON THE ARC BELOW THE AXLE, AND ONLY THERE. That is
    the one part of a wheel well where no body panel can reach: the fender,
    the arch lip, the liner and the sill are all at or above hub height, so a
    lateral histogram taken under the hub is the tyre and nothing else. The
    measured histograms are flat-topped blocks with sharp edges — a 1st/99th
    percentile pair reads the section width straight off them.

    An earlier version instead asked each 10 mm lateral slab to prove its own
    360-degree coverage. That was WRONG in a way worth recording: a slab that
    thin holds too few tread vertices to fill 72 angular bins, so genuine tyre
    slabs failed the test and the band was truncated to 10-40 mm. It reported
    wheel widths of 0.010 m and, because the hub's lateral position is taken
    from the band's mid-plane, it also moved three of the four hubs. A test
    that silently shrinks its own sample is worse than no test.
    """
    li, ti, ui = fr["li"], fr["ti"], fr["ui"]
    Vs = V[np.sign(V[:, ti]) == fit["side"]]
    d = np.hypot(Vs[:, li] - fit["l"], Vs[:, ui] - fit["u"])
    lat = np.abs(Vs[:, ti])
    near = d < 1.35 * fit["R"]
    if near.sum() < 300:
        return None
    tout = float(np.percentile(lat[near], 99.8))
    band = (np.abs(d - fit["R"]) <= cfg["band_rel"] * fit["R"]) & \
           (lat >= tout - cfg["out_slab_m"])
    low = band & (Vs[:, ui] < fit["u"] - 0.15 * fit["R"])     # below the axle
    if low.sum() < cfg["slab_min_pts"]:
        return None
    p = cfg["width_pct"]
    t_lo, t_hi = np.percentile(lat[low], [p, 100 - p])
    # Once the band is known from the safe arc, take the FULL 360 degrees of
    # tread inside it: the axis fit wants the whole circumference, and body
    # skin cannot be inside a band that was measured where body skin is not.
    m = band & (lat >= t_lo) & (lat <= t_hi)
    return dict(t_lo=float(t_lo), t_hi=float(t_hi), width=float(t_hi - t_lo),
                points=Vs[m], n=int(m.sum()), t_out=tout,
                n_lower_arc=int(low.sum()),
                width_method="1st-99th percentile of |lateral| over the tread "
                             "band on the arc below the axle")


# --------------------------------------------------------------------- pose
# WHY THIS EXISTS. Toe is the angle between a wheel's axis and the CAR's
# lateral axis. Camber is the angle between that axis and the CAR's ground
# plane. Neither is defined against the scene's axes, and on this car the two
# frames are measurably different: the body's lateral centreline drifts from
# +0.044 m at the nose to -0.077 m at the tail (a residual YAW of ~1.8 deg),
# and the two axles' hub heights differ by ~0.20 m over a 2.47 m wheelbase (a
# residual PITCH of ~4.5 deg). Measuring toe against the scene axis would
# have charged the whole yaw to the wheels — as toe-in on one flank and
# toe-out on the other — and reported four alignment faults that are really
# one placement fault.
#
# A yaw also inflates the axis-aligned bounding box, which matters beyond
# this gate: an AABB is only the car's dimensions when the car is square to
# the axes. See `pose_report` for the de-posed extents.


def _sym_plane(V, fr, frac=0.85, nslab=40):
    """Yaw and lateral offset of the car's symmetry plane.

    Estimated from the lateral MIDPOINT of the silhouette in each length
    slab: for a car square to the axes that midpoint is constant, and a yaw
    makes it a straight line with slope -tan(yaw). Robust because it uses the
    outermost points of each slab (the widest part of the body), not a
    centroid, so interior clutter and one-sided melt cannot drag it.
    """
    li, ti, ui = fr["li"], fr["ti"], fr["ui"]
    lo, hi = fr["lo"][li], fr["hi"][li]
    half = (hi - lo) / 2
    mid = (lo + hi) / 2
    edges = np.linspace(mid - frac * half, mid + frac * half, nslab + 1)
    xs, cs, ws = [], [], []
    for i in range(nslab):
        m = (V[:, li] >= edges[i]) & (V[:, li] < edges[i + 1]) & \
            (V[:, ui] > fr["lo"][ui] + 0.12 * (fr["hi"][ui] - fr["lo"][ui])) & \
            (V[:, ui] < fr["lo"][ui] + 0.65 * (fr["hi"][ui] - fr["lo"][ui]))
        if m.sum() < 200:
            continue
        S = V[m][:, ti]
        xs.append((edges[i] + edges[i + 1]) / 2)
        cs.append((np.percentile(S, 99.8) + np.percentile(S, 0.2)) / 2)
        ws.append(m.sum())
    if len(xs) < 8:
        return dict(yaw_deg=0.0, lat_offset_m=0.0, n_slabs=len(xs),
                    note="too few usable slabs; yaw not corrected")
    x = np.array(xs); c = np.array(cs); w = np.sqrt(np.array(ws, float))
    for _ in range(3):                       # trimmed, so a bumper cannot bend it
        A = np.column_stack([x, np.ones(len(x))]) * w[:, None]
        sol, *_ = np.linalg.lstsq(A, c * w, rcond=None)
        res = np.abs(c - (sol[0] * x + sol[1]))
        keep = res <= max(np.percentile(res, 80), 1e-6)
        if keep.sum() < 6:
            break
        x, c, w = x[keep], c[keep], w[keep]
    slope, intercept = float(sol[0]), float(sol[1])
    return dict(yaw_deg=float(math.degrees(math.atan(slope))),
                lat_offset_m=intercept, slope=slope, n_slabs=int(len(x)),
                rms_m=float(np.sqrt(np.mean((c - (slope * x + intercept)) ** 2))),
                method="lateral midpoint of the silhouette per length slab, "
                       "trimmed weighted least squares")


def _rot(axis_idx, ang):
    c, s = math.cos(ang), math.sin(ang)
    M = np.eye(3)
    a, b = [i for i in range(3) if i != axis_idx]
    M[a, a] = c; M[a, b] = -s; M[b, a] = s; M[b, b] = c
    return M


def solve_pose(V, fr, wheels):
    """The rigid transform that squares the car to the axes and grounds it.

    Three stages, each solved from the evidence that actually determines it:
      YAW + lateral offset   from the body's symmetry plane
      PITCH + ROLL + height  from the four tyre CONTACT points, least squares
    The pitch/roll fit is over-determined (4 contacts, 3 freedoms) ON PURPOSE:
    its residuals are the part of the grounding error that no rigid transform
    can remove, which is precisely the part that needs the wheels themselves
    changed. Reported as `contact_residual_m`.
    """
    from scipy.optimize import least_squares
    li, ti, ui = fr["li"], fr["ti"], fr["ui"]
    sym = _sym_plane(V, fr)
    yaw = math.radians(sym["yaw_deg"])
    Myaw = _rot(ui, -yaw if ui == 1 else yaw)
    # verify the sign empirically rather than reasoning about handedness
    def resid_yaw(M, off):
        W = (V - off) @ M.T
        s = _sym_plane(W, dict(fr, lo=list(W.min(0)), hi=list(W.max(0))))
        return abs(s["yaw_deg"])
    off = np.zeros(3); off[ti] = sym["lat_offset_m"]
    best = None
    for sgn in (+1, -1):
        M = _rot(ui, sgn * yaw)
        r = resid_yaw(M, off)
        if best is None or r < best[0]:
            best = (r, sgn, M)
    yaw_res, yaw_sgn, Myaw = best

    hubs = np.array([w["centre"] for w in wheels])
    radii = np.array([w["R"] for w in wheels])
    hubs_y = (hubs - off) @ Myaw.T

    def res(p):
        M = _rot(li, p[1]) @ _rot(ti, p[0])
        H = hubs_y @ M.T
        return H[:, ui] + p[2] - radii - fr["ground"] * 0

    s = least_squares(res, [0.0, 0.0, 0.0])
    pitch, roll, dz = float(s.x[0]), float(s.x[1]), float(s.x[2])
    M = _rot(li, roll) @ _rot(ti, pitch) @ Myaw
    t = -off @ M.T
    t[ui] += dz
    return dict(
        yaw_deg=float(math.degrees(yaw_sgn * yaw)),
        yaw_residual_deg=float(yaw_res),
        lat_offset_m=float(sym["lat_offset_m"]),
        pitch_deg=float(math.degrees(pitch)), roll_deg=float(math.degrees(roll)),
        vertical_offset_m=dz,
        contact_residual_m=[float(x) for x in s.fun],
        contact_residual_rms_m=float(np.sqrt(np.mean(s.fun ** 2))),
        matrix=[[float(x) for x in row] for row in M],
        translation=[float(x) for x in t],
        symmetry=sym,
        note="apply as  p' = M @ p + t  to EVERY vertex in the scene")


def pose_report(V, fr, pose):
    """Bounding box before and after de-posing.

    A yawed or pitched car reports an axis-aligned bounding box LARGER than
    itself in every axis it is rotated about, so 'the AABB matches published
    dimensions' is only a dimension check when the pose is square first.
    """
    M = np.array(pose["matrix"]); t = np.array(pose["translation"])
    W = V @ M.T + t
    return dict(aabb_before=[float(x) for x in (V.max(0) - V.min(0))],
                aabb_after=[float(x) for x in (W.max(0) - W.min(0))],
                min_after=[float(x) for x in W.min(0)])


# --------------------------------------------------------------- cylinder fit
def _axis_from_angles(base, a, b):
    """Perturb a unit `base` axis by two small angles in its own null space."""
    n = base / np.linalg.norm(base)
    tmp = np.array([1.0, 0, 0]) if abs(n[0]) < 0.9 else np.array([0, 1.0, 0])
    e1 = np.cross(n, tmp); e1 /= np.linalg.norm(e1)
    e2 = np.cross(n, e1)
    v = n + a * e1 + b * e2
    return v / np.linalg.norm(v)


def fit_cylinder(Q, c0, a0, R0):
    """Least-squares axis + centre + radius of an already-isolated tread band.

    `Q` must be the tread point set from `slab_tread`. Deliberately does NOT
    re-select its own points: the selection is the part that can go wrong, so
    it is done once, in the open, by a step that can be inspected.

    Five free parameters — two axis angles, two centre offsets in the plane
    perpendicular to the axis, and the radius. The centre's position ALONG
    the axis is not observable from a cylinder, so it is not fitted; the
    lateral hub position comes from the tread band's own mid-plane.
    """
    from scipy.optimize import least_squares
    c, a, R = np.asarray(c0, float), np.asarray(a0, float), float(R0)
    a = a / np.linalg.norm(a)
    tmp = np.array([1.0, 0, 0]) if abs(a[0]) < 0.9 else np.array([0, 1.0, 0])
    e1 = np.cross(a, tmp); e1 /= np.linalg.norm(e1)
    e2 = np.cross(a, e1)

    def res(p):
        ax = _axis_from_angles(a, p[0], p[1])
        cc = c + p[2] * e1 + p[3] * e2
        dd = Q - cc
        rr = np.linalg.norm(dd - np.outer(dd @ ax, ax), axis=1)
        return rr - p[4]

    s = least_squares(res, [0.0, 0.0, 0.0, 0.0, R], method="lm", max_nfev=6000)
    ax = _axis_from_angles(a, s.x[0], s.x[1])
    cc = c + s.x[2] * e1 + s.x[3] * e2
    d = Q - cc
    lat = d @ ax
    # put the reported centre on the tread band's mid-plane
    cc = cc + ax * float(np.median(lat))
    return dict(centre=cc, axis=ax, R=float(s.x[4]),
                rms=float(np.sqrt(np.mean(s.fun ** 2))), n=int(len(Q)),
                lat_span=(float(np.percentile(lat, 0.5)),
                          float(np.percentile(lat, 99.5))))


# Legitimate ways to draw the same tread band. None is more correct than the
# others; they differ only in how thick the band is and how hard the lateral
# percentiles are trimmed. See `selection_ensemble`.
SEL_VARIANTS = (
    dict(),
    dict(band_rel=0.024), dict(band_rel=0.036), dict(band_rel=0.042),
    dict(width_pct=0.5), dict(width_pct=2.0),
    dict(band_rel=0.024, width_pct=2.0), dict(band_rel=0.036, width_pct=0.5),
)


def selection_ensemble(V, fr, w, cfg):
    """Toe and camber over a family of equally defensible tread bands.

    WHY THIS IS THE UNCERTAINTY THAT MATTERS, AND THE BOOTSTRAP IS NOT
    -----------------------------------------------------------------
    `bootstrap_axis` resamples points WITHIN one band, so it measures how well
    that band's own points pin the axis: on this Golf it returns 0.17-0.22
    deg. That number is real and it is not the whole story. A controlled
    injection settled it: rotating one wheel's geometry by a known +2.000 deg
    and re-fitting THE SAME point set moves the answer by +2.000 deg (the
    estimator is exact), but re-running the full detector on the rotated file
    moves it by only +0.133 deg, because the re-selected band is a 10%
    different set of points and this tread is not round enough for the two
    subsets to agree.

    So the honest instrument error is dominated by WHICH points get called
    tread, not by noise within them. This function measures that directly by
    re-drawing the band eight ways and reporting the spread. The verdict
    machinery then combines the two in quadrature — and on a mesh like this
    one it lands far above the owner's 0.1 deg tolerance, which is the
    answer: the tolerance is not resolvable on this geometry, and saying so
    is worth more than a confident number that a re-run would contradict.
    """
    li, ti, ui = fr["li"], fr["ti"], fr["ui"]
    upv = np.zeros(3); upv[ui] = 1.0
    fwd = np.zeros(3); fwd[li] = float(fr["nose"]) if fr["nose"] else 1.0
    outw = np.zeros(3); outw[ti] = 1.0 if w["centre"][ti] > 0 else -1.0
    toes, cams, ns = [], [], []
    for var in SEL_VARIANTS:
        c2 = dict(cfg, **var)
        band = slab_tread(V, fr, w["circle"], c2)
        if band is None or band["n"] < 200:
            continue
        c0 = np.zeros(3)
        c0[li], c0[ui] = w["circle"]["l"], w["circle"]["u"]
        c0[ti] = w["circle"]["side"] * (band["t_lo"] + band["t_hi"]) / 2
        a0 = np.zeros(3); a0[ti] = 1.0
        near = np.linalg.norm(V - c0, axis=1) < 1.35 * w["circle"]["R"]
        f = iterate_axis(V[near], c0.copy(), a0.copy(), w["circle"]["R"],
                         band["width"], band_rel=c2["band_rel"],
                         lat_frac=0.55) or \
            fit_cylinder(band["points"], c0, a0, w["circle"]["R"])
        a = f["axis"] * (1.0 if float(f["axis"] @ outw) > 0 else -1.0)
        toes.append(math.degrees(math.asin(np.clip(float(a @ fwd), -1, 1))))
        cams.append(-math.degrees(math.asin(np.clip(float(a @ upv), -1, 1))))
        ns.append(band["n"])
    if not toes:
        return None
    return dict(toe_mean=float(np.mean(toes)), toe_sd=float(np.std(toes, ddof=1))
                if len(toes) > 1 else float("nan"),
                camber_mean=float(np.mean(cams)),
                camber_sd=float(np.std(cams, ddof=1)) if len(cams) > 1
                else float("nan"),
                n_variants=len(toes), band_sizes=[int(x) for x in ns],
                toe_range=[float(min(toes)), float(max(toes))],
                camber_range=[float(min(cams)), float(max(cams))])


def iterate_axis(Vr, c, a, R, W, band_rel=0.030, lat_frac=0.55, iters=8,
                 min_pts=300):
    """Re-select the tread about the CURRENT axis, refit, repeat.

    THE BIAS THIS REMOVES, MEASURED
    -------------------------------
    A tread band chosen as "points whose distance from the axis is within
    3% of R" is chosen ABOUT AN ASSUMED AXIS, and that assumption survives
    into the answer. Tilt a wheel by a known 2.000 deg and the band, still
    drawn about the old axis, keeps preferentially those points that still
    fit the old axis: measured on this Golf's front-left wheel, the fitted
    angle moved by only 0.69 deg — a 35% response. The estimator was
    attenuating every angle toward its own seed, which on this car is the
    pure lateral direction, i.e. toward zero toe and zero camber. Reported
    angles were therefore ~3x too small, and a repair that rotated by the
    reported error under-corrected by the same factor (observed: front camber
    "zeroed" from +0.87 to +0.96 deg).

    Iterating the selection about the evolving axis restores a 90% response
    on the same injection test, and the residual 10% is what the ensemble in
    `selection_ensemble` then measures rather than hides.
    """
    fit = None
    for _ in range(iters):
        d = Vr - c
        lat = d @ a
        rad = np.linalg.norm(d - np.outer(lat, a), axis=1)
        sel = (np.abs(rad - R) < band_rel * R) & (np.abs(lat) < lat_frac * W)
        if sel.sum() < min_pts:
            break
        prev = a.copy()
        fit = fit_cylinder(Vr[sel], c, a, R)
        c, a, R = np.asarray(fit["centre"]), np.asarray(fit["axis"]), fit["R"]
        if math.degrees(math.acos(min(1.0, abs(float(prev @ a))))) < 0.005:
            break
    if fit is None:
        return None
    fit = dict(fit)
    fit.update(centre=c, axis=a, R=float(R))
    return fit


def bootstrap_axis(Q, fit, cfg):
    """Standard error of the fitted axis direction, in degrees.

    The tolerance being tested (0.1 deg) is tighter than most generated
    wheels are round, so the instrument has to state its own precision. When
    this comes back larger than the tolerance, the number is not evidence and
    `grade()` downgrades the criterion to NOT MEASURABLE rather than guessing.
    """
    from scipy.optimize import least_squares
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
                          max_nfev=1200)
        axes.append(_axis_from_angles(a0, s.x[0], s.x[1]))
    A = np.array(axes)
    A *= np.sign(A @ a0)[:, None]
    mean = A.mean(0); mean /= np.linalg.norm(mean)
    ang = np.degrees(np.arccos(np.clip(A @ mean, -1, 1)))
    return float(np.sqrt(np.mean(ang ** 2)))


# ---------------------------------------------------------------- the measure
def _fit_all(V, fr, cfg, seeds=None):
    li, ti, ui = fr["li"], fr["ti"], fr["ui"]
    fits = find_wheels(V, fr, cfg) if seeds is None else \
        [f for f in (refine_circle(V, fr, s, cfg) for s in seeds) if f]
    wheels = []
    for f in fits:
        band = slab_tread(V, fr, f, cfg)
        if band is None or band["n"] < 200:
            continue
        c0 = np.zeros(3)
        c0[li], c0[ui] = f["l"], f["u"]
        c0[ti] = f["side"] * (band["t_lo"] + band["t_hi"]) / 2
        a0 = np.zeros(3); a0[ti] = 1.0
        # The axis comes from an ITERATED re-selection, not a single fit —
        # a one-shot fit is biased toward its own seed axis (see
        # `iterate_axis`). The region handed to it is everything within 1.35R
        # of the seed hub on that flank, so the iteration is free to move the
        # band as the axis moves.
        near = np.linalg.norm(V - c0, axis=1) < 1.35 * f["R"]
        cyl = iterate_axis(V[near], c0.copy(), a0.copy(), f["R"],
                           band["width"], band_rel=cfg["band_rel"]) or \
            fit_cylinder(band["points"], c0, a0, f["R"])
        cyl.update(circle=f, band=band, side=f["side"])
        wheels.append(cyl)
    return wheels


def measure(path, spec=None, nose="auto", cfg=None, bootstrap=True,
            canonicalise=True):
    """Measure Gate 6 in the CAR's own frame.

    Two passes. The first fits the wheels where they lie and hands the four
    hub centres to `solve_pose`, which recovers the rigid transform that
    squares the car to the axes and stands it on the ground. The second pass
    re-fits everything AFTER that transform, so toe, camber, hub symmetry and
    track are all expressed against the car, not against whatever pose the
    file happens to have been saved in. `canonicalise=False` reports the raw
    scene frame instead, which is only useful for showing what the pose cost.
    """
    cfg = dict(DEFAULTS, **(cfg or {}))
    if spec:
        r = _spec_tyre_radius(spec)
        if r:                       # search around the stated tyre
            cfg["r_lo"], cfg["r_hi"] = 0.75 * r, 1.30 * r
            cfg["r_seed"] = r
    meshes, _ = load_points(path)
    fr = resolve_frame(meshes, nose=nose, spec=spec)
    li, ti, ui = fr["li"], fr["ti"], fr["ui"]
    V = np.vstack([v for v, _ in meshes.values()])

    wheels = _fit_all(V, fr, cfg)
    pose = solve_pose(V, fr, wheels) if len(wheels) == 4 else None
    prep = pose_report(V, fr, pose) if pose else None
    if pose and canonicalise:
        M = np.array(pose["matrix"]); t = np.array(pose["translation"])
        V = V @ M.T + t
        meshes = {n: (v @ M.T + t, f) for n, (v, f) in meshes.items()}
        fr = resolve_frame(meshes, nose=("+" if fr["nose"] > 0 else "-"),
                           spec=spec)
        seeds = []
        for w in wheels:
            c = M @ w["centre"] + t
            seeds.append(dict(l=float(c[li]), u=float(c[ui]), r0=w["R"],
                              side=(1 if c[ti] > 0 else -1)))
        wheels = _fit_all(V, fr, cfg, seeds=seeds)
    return _finish(path, meshes, V, fr, wheels, cfg, spec, bootstrap, pose,
                   prep, canonicalise)


def _finish(path, meshes, V, fr, wheels, cfg, spec, bootstrap, pose, prep,
            canonicalise):
    li, ti, ui = fr["li"], fr["ti"], fr["ui"]
    # After canonicalisation the ground plane IS the axis origin by
    # construction. Before it, the lowest vertex is the only ground evidence
    # available and is used as such, with the assumption stated in the output.
    ground = 0.0 if canonicalise else (
        0.0 if abs(fr["ground"]) < 5e-3 else fr["ground"])

    # ---- corner labels
    for w in wheels:
        w["side_s"] = "+" if w["centre"][ti] > 0 else "-"
    if len(wheels) == 4:
        order = sorted(range(4), key=lambda i: wheels[i]["centre"][li])
        lo_idx = set(order[:2])
        for i, w in enumerate(wheels):
            w["axle"] = "lo" if i in lo_idx else "hi"
    for w in wheels:
        if fr["nose"] == 0 or len(wheels) != 4:
            w["corner"] = (w.get("axle", "?")[0].upper() + w["side_s"])
        else:
            front = (w["axle"] == "lo") == (fr["nose"] < 0)
            left = (w["centre"][ti] > 0) == (fr["nose"] < 0)
            w["corner"] = ("F" if front else "R") + ("L" if left else "R")

    # ---- unit vectors of the car frame
    upv = np.zeros(3); upv[ui] = 1.0
    fwd = np.zeros(3); fwd[li] = float(fr["nose"]) if fr["nose"] else 1.0

    rows = []
    for w in wheels:
        c, R = w["centre"], w["R"]
        outw = np.zeros(3); outw[ti] = 1.0 if c[ti] > 0 else -1.0
        a = w["axis"] * (1.0 if float(w["axis"] @ outw) > 0 else -1.0)  # outboard
        # toe-IN is positive: rotating the wheel's leading edge toward the
        # centreline swings the OUTBOARD axis toward the nose, so a . fwd > 0.
        toe = math.degrees(math.asin(np.clip(float(a @ fwd), -1, 1)))
        # negative camber leans the wheel TOP inboard, which tilts the
        # outboard axis UP, so a . up > 0 <=> negative camber.
        camber = -math.degrees(math.asin(np.clip(float(a @ upv), -1, 1)))
        se = bootstrap_axis(w["band"]["points"], w, cfg) if bootstrap \
            else float("nan")
        ens = selection_ensemble(V, fr, w, cfg)
        # The two error terms are independent: one is noise within a band, the
        # other is the choice of band. Quadrature, and the total is what every
        # angular verdict is tested against.
        sd_toe = ens["toe_sd"] if ens else float("nan")
        sd_cam = ens["camber_sd"] if ens else float("nan")
        se_toe = float(np.hypot(se, sd_toe)) if np.isfinite(se) else sd_toe
        se_cam = float(np.hypot(se, sd_cam)) if np.isfinite(se) else sd_cam
        rows.append(dict(
            corner=w["corner"], side=w["side_s"], axle=w.get("axle"),
            centre=[float(x) for x in c],
            hub_length=float(c[li]), hub_up=float(c[ui]), hub_lat=float(c[ti]),
            axis=[float(x) for x in a],
            radius_m=float(R), width_m=float(w["band"]["width"]),
            tread_points=int(w["n"]),
            tread_coverage=float(w["circle"]["coverage"]),
            fit_rms_m=float(w["rms"]),
            circle_rms_m=float(w["circle"]["rms"]),
            bottom_m=float(c[ui] - R - ground),
            toe_deg=float(toe), camber_deg=float(camber),
            axis_se_deg=float(se),
            toe_se_deg=se_toe, camber_se_deg=se_cam,
            selection_ensemble=ens,
            tread_lat_lo=float(w["band"]["t_lo"]),
            tread_lat_hi=float(w["band"]["t_hi"]),
        ))
    rows.sort(key=lambda r: r["corner"])

    out = dict(file=os.path.abspath(path), frame=fr,
               seed_method="name-free radius-band vote + below-axle robust "
                           "circle refine + below-axle lateral tread band",
               measured_in=("car frame (pose corrected)" if canonicalise
                            else "raw scene frame"),
               n_wheels=len(rows), wheels=rows, ground_plane=float(ground),
               axes=dict(length=li, lateral=ti, up=ui),
               pose=pose, pose_effect=prep)
    _derive(out, fr, spec)
    out["_meshes"] = meshes          # car-frame vertices for the second pass
    return out


def _spec_tyre_radius(spec):
    """Rolling radius from a tyre spec string like '225/45R17'."""
    import re
    s = ((spec or {}).get("tyre") or {}).get("spec") or ""
    m = re.match(r"\s*(\d{3})\s*/\s*(\d{2})\s*R\s*(\d{2})", s)
    if not m:
        return None
    w, ar, rim = float(m.group(1)), float(m.group(2)), float(m.group(3))
    return (rim * 25.4 / 2 + ar / 100.0 * w) / 1000.0


def _spec_tyre_width(spec):
    import re
    s = ((spec or {}).get("tyre") or {}).get("spec") or ""
    m = re.match(r"\s*(\d{3})\s*/", s)
    return float(m.group(1)) / 1000.0 if m else None


def _derive(out, fr, spec):
    """Axle-level numbers. Each axle is derived ONLY from its own two wheels —
    the owner asked for front and rear track measured independently, so no
    quantity here is ever averaged across axles."""
    rows = out["wheels"]
    by = {r["corner"]: r for r in rows}
    out["axles"] = {}
    for pre in ("F", "R", "L", "H"):
        L, Rt = by.get(pre + "L"), by.get(pre + "R")
        if pre in ("L", "H"):
            L, Rt = by.get(pre + "+"), by.get(pre + "-")
        if not (L and Rt):
            continue
        out["axles"][pre] = dict(
            track_m=float(abs(L["hub_lat"] - Rt["hub_lat"])),
            hub_lat_asym_m=float(abs(abs(L["hub_lat"]) - abs(Rt["hub_lat"]))),
            hub_long_asym_m=float(abs(L["hub_length"] - Rt["hub_length"])),
            hub_up_asym_m=float(abs(L["hub_up"] - Rt["hub_up"])),
            radius_diff_m=float(abs(L["radius_m"] - Rt["radius_m"])),
            width_diff_m=float(abs(L["width_m"] - Rt["width_m"])),
            # Per-wheel toe is signed so that POSITIVE IS TOE-IN on both
            # flanks, so the axle's total toe is their SUM and the axle's own
            # yaw relative to the body ("thrust", or a steered axle) is half
            # their difference. Subtracting them, as an earlier version did,
            # silently reported a 2.45-degree rear toe-in as -0.007.
            total_toe_deg=float(L["toe_deg"] + Rt["toe_deg"]),
            axle_yaw_deg=float((L["toe_deg"] - Rt["toe_deg"]) / 2.0),
        )
    if len(rows) == 4:
        rr = [r["radius_m"] for r in rows]
        ww = [r["width_m"] for r in rows]
        out["spread"] = dict(radius_m=float(max(rr) - min(rr)),
                             width_m=float(max(ww) - min(ww)),
                             radius_mean_m=float(np.mean(rr)),
                             width_mean_m=float(np.mean(ww)))
        fl = [r for r in rows if r["axle"] == ("lo" if fr["nose"] < 0 else "hi")]
        rl = [r for r in rows if r not in fl]
        if fl and rl:
            lf = float(np.mean([r["hub_length"] for r in fl]))
            lr = float(np.mean([r["hub_length"] for r in rl]))
            out["wheelbase_m"] = abs(lf - lr)
            # Rigid pitch implied by the hub line, and by the CONTACT line.
            # They differ when the two axles carry different radii, which is
            # exactly the case this car turns out to be, so both are reported.
            uf = float(np.mean([r["hub_up"] for r in fl]))
            ur = float(np.mean([r["hub_up"] for r in rl]))
            bf = float(np.mean([r["bottom_m"] for r in fl]))
            br = float(np.mean([r["bottom_m"] for r in rl]))
            out["hub_line_pitch_deg"] = float(
                math.degrees(math.atan2(uf - ur, lf - lr)))
            out["contact_line_pitch_deg"] = float(
                math.degrees(math.atan2(bf - br, lf - lr)))
            out["float_front_m"], out["float_rear_m"] = bf, br
        if spec:
            r = _spec_tyre_radius(spec)
            w = _spec_tyre_width(spec)
            out["spec_tyre"] = dict(spec=((spec.get("tyre") or {}).get("spec")),
                                    radius_m=r, section_width_m=w)
    return out


def _components(V, F, snap=1e-5):
    """Per-face component label, welding vertices that coincide in space.

    glTF splits vertices by normal and UV, so raw index adjacency reports one
    wheel as dozens of shells. Welding on rounded position first is what makes
    "does this component belong to the wheel?" a meaningful question. Lives
    here rather than in the repair operator because the MEASUREMENT needs it
    too: see `_wheel_owned` below.
    """
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    key = np.round(V / snap).astype(np.int64)
    _, inv = np.unique(key, axis=0, return_inverse=True)
    n = int(inv.max()) + 1
    e = inv[np.vstack([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])]
    M = coo_matrix((np.ones(len(e), np.int8), (e[:, 0], e[:, 1])), shape=(n, n))
    _, lab = connected_components(M, directed=False)
    # `lab` is indexed by WELDED vertex, so an original face index has to be
    # mapped through `inv` first. Indexing it directly with F[:, 0] — as the
    # first version of this function did — reads garbage whenever welding
    # actually merges anything, and raises IndexError as soon as the original
    # vertex count exceeds the welded one, which is every real glTF.
    return lab[inv[F[:, 0]]], lab[inv]


def _wheel_owned(meshes, wheels, cyl_r=1.03, cyl_w=0.80, contain=0.85,
                 min_faces=3):
    """Vertex mask per mesh: does this vertex belong to ANY wheel?

    WHY THIS EXISTS — TWO BUGS IT FIXES, BOTH MEASURED
    --------------------------------------------------
    The first version of `fender_and_arch` defined "not the wheel" as
    `~((rad < 1.02R) & (|lat| < 0.70W))`, i.e. by the fitted cylinder alone,
    and then asked two questions of the survivors:

      arch INTERSECTION  = not_wheel & (rad < 0.97R) & (|lat| < 0.48W)
          This set is EMPTY BY CONSTRUCTION. Any point with rad < 0.97R and
          |lat| < 0.48W satisfies both halves of the excluded term, so it is
          never "not_wheel". The criterion "no body geometry inside the tyre's
          swept volume" therefore reported 0 for every wheel of every car and
          had never once been tested. (CLAUDE.md: a gate nobody tested is a
          gate that does not exist.)

      arch CLEARANCE     = min radius of not_wheel points, minus R
          Its answer was the TYRE'S OWN OUTER SKIN. The fit's rms is ~4.5 mm,
          so tread vertices sit outside 1.02R, become "not_wheel", and set the
          minimum. Measured on this Golf: 8 of 8 wheels returned exactly
          0.0200 x R (0.02 = 1.02 - 1.00). It was reading back its own
          exclusion boundary, and the repair operator used that number to
          decide whether a radius correction would hit the body.

    Ownership by CONNECTED COMPONENT has neither failure: a component joins a
    wheel when `contain` of its faces lie inside the fitted cylinder, which is
    the same test `wheel_ground_op.isolate` uses to decide what it may move.
    So the clearance is measured against exactly the geometry that will NOT
    move, and the intersection test is answerable.

    WHY `contain` IS 0.85 AND WHY THAT NUMBER IS NOT A GUESS. Measured on
    this Golf across all four wheels: of the 259 components with any face
    inside a wheel cylinder, EVERY ONE scores either >= 0.90 or <= 0.15,
    except a single 5-face speck at 0.40. The population is bimodal with an
    empty gap three quarters of a decade wide, so any threshold inside that
    gap gives the same answer and the choice cannot be tuned to flatter a
    result. The repair operator keeps its own stricter 0.95, deliberately:
    measuring wrongly costs a wrong number, MOVING wrongly tears a car.
    """
    owned = {}
    for name, (V, F) in meshes.items():
        flab, vlab = _components(V, F)
        cen = V[F].mean(axis=1)
        keep = np.zeros(len(F), bool)
        for w in wheels:
            c = np.asarray(w["centre"]); a = np.asarray(w["axis"])
            R, W = w["radius_m"], w["width_m"]
            d = cen - c
            lat = d @ a
            rad = np.linalg.norm(d - np.outer(lat, a), axis=1)
            inside = (rad < cyl_r * R) & (np.abs(lat) < cyl_w * W)
            if not inside.any():
                continue
            for comp in np.unique(flab[inside]):
                sub = flab == comp
                n = int(sub.sum())
                if n < min_faces:
                    continue
                if int((sub & inside).sum()) / n >= contain:
                    keep |= sub
        vm = np.zeros(len(V), bool)
        if keep.any():
            vm[F[keep].ravel()] = True
        owned[name] = vm
    return owned


def fender_and_arch(m, cfg=None):
    """Second pass: fender lip position and arch intersection, per wheel.

    Kept separate because it needs the SKIN meshes distinguished from the
    wheel, which the fit does not need. The lip is the outermost lateral
    point of the body skin in the annulus just outside the tyre, in the upper
    half of the arch; a percentile is used so one stray vertex cannot move it.
    """
    cfg = dict(DEFAULTS, **(cfg or {}))
    meshes = m["_meshes"]                 # already in the frame `measure` used
    li, ti, ui = m["axes"]["length"], m["axes"]["lateral"], m["axes"]["up"]
    ALL = np.vstack([v for v, _ in meshes.values()])
    # Everything a wheel owns, by connected component — see `_wheel_owned`.
    # BODY is the complement, and it is the only thing an arch test may see.
    own = _wheel_owned(meshes, m["wheels"]) if m["wheels"] else {}
    OWNED = np.concatenate([own[n] for n in meshes]) if own else \
        np.zeros(len(ALL), bool)
    BODY = ALL[~OWNED]
    m["wheel_owned_vertices"] = int(OWNED.sum())
    m["body_vertices"] = int(len(BODY))
    for r in m["wheels"]:
        c = np.array(r["centre"]); a = np.array(r["axis"]); R = r["radius_m"]
        Wd = r["width_m"]
        d = ALL - c
        lat = d @ a
        rad = np.linalg.norm(d - np.outer(lat, a), axis=1)
        # ---- the TYRE carcass, defined geometrically: sidewall + tread, i.e.
        # the annulus outboard of the rim well, inside the wheel's own lateral
        # band. This is what the mission means by "the tyre is the annulus
        # outside the rim radius about the wheel axis"; nothing here consults
        # a material name, because on this car the names are wrong.
        carcass = (rad > 0.62 * R) & (rad < 1.02 * R) & \
                  (np.abs(lat) < 0.62 * Wd)
        r["outer_sidewall_lat"] = float(
            np.percentile(np.abs(ALL[carcass][:, ti]), 99.0)) \
            if carcass.sum() > 50 else float("nan")
        r["carcass_points"] = int(carcass.sum())
        # ---- the FENDER: the body skin DIRECTLY ABOVE the tyre.
        # Three candidate definitions were measured against each other on
        # this car (see the module docstring's method note). Two of them
        # sampled an ANNULUS around the axle and both came back ASYMMETRIC on
        # a body that is symmetric once the yaw is removed — 0.812 against
        # 0.762 across the front axle — because an annulus reaches past the
        # arch lip onto the sill and the bumper, and how far it reaches
        # depends on local geometry that differs corner to corner. The crown
        # window below reads 0.8005/0.8072 front and 0.8315/0.8316 rear: the
        # left/right agreement on a symmetric body is the evidence that it is
        # measuring the fender and not something else. It is also the surface
        # the criterion is actually about — the metal the sidewall must clear.
        db = BODY - c
        blat = db @ a
        brad = np.linalg.norm(db - np.outer(blat, a), axis=1)
        lip = (np.abs(BODY[:, li] - c[li]) < 0.25 * R) & \
            (BODY[:, ui] > c[ui] + R) & (BODY[:, ui] < c[ui] + 1.5 * R)
        lip_lat = float(np.percentile(np.abs(BODY[lip][:, ti]), 98.0)) \
            if lip.sum() > 30 else float("nan")
        r["fender_lip_lat"] = lip_lat
        # positive = tyre proud of the fender, negative = tucked inside it
        r["sidewall_vs_fender_m"] = float(r["outer_sidewall_lat"] - lip_lat)
        r["fender_lip_points"] = int(lip.sum())
        # ---- arch intersection: BODY geometry inside the TYRE.
        # "Body" means every vertex no wheel component owns, so this can
        # actually return a non-zero answer (the previous formulation could
        # not — see `_wheel_owned`). The band is the CARCASS, r in
        # [0.70R, 0.97R], not the whole swept disc: a brake disc, a hub
        # carrier and an inner wheel-house all legitimately live near the
        # axis, and counting them would report a fault on every car with
        # brakes. Measured on this Golf, the near-axis region holds 6-11k such
        # vertices per rear wheel; the carcass band is what the criterion
        # "no arch intersection / no penetrating wheels" is actually about.
        inside = (brad > 0.80 * R) & (brad < 0.97 * R) & \
            (np.abs(blat) < 0.48 * Wd)
        r["arch_intersect_points"] = int(inside.sum())
        r["arch_intersect_depth_m"] = float(R - brad[inside].min()) \
            if inside.sum() else 0.0
        # WHICH mesh is intruding matters to whoever has to act on a FAIL:
        # a fender panel in the tyre is a body defect, a fragment of a fused
        # 423k-face interior shell is a labelling artefact of THIS car. The
        # verdict stays FAIL either way; the attribution is what makes it
        # actionable instead of merely alarming.
        att, i0 = {}, 0
        for nm, (Vm, _F) in meshes.items():
            k = int(len(Vm) - own.get(nm, np.zeros(len(Vm), bool)).sum())
            if k:
                n_here = int(inside[i0:i0 + k].sum())
                if n_here:
                    att[nm] = n_here
                i0 += k
        r["arch_intersect_by_mesh"] = att
        # ---- how much radial room is left before the tread would touch the
        # body. The repair operator needs this BEFORE it grows a tyre: a
        # radius correction that closes this gap turns a floating wheel into
        # an intersecting one, which is worse.
        # Measured in the UPPER arc only (the arch, not the road) and only
        # OUTSIDE 1.05R. That floor is not arbitrary: the cylinder fit's rms
        # is ~4.5 mm here, so tread vertices scatter to ~1.02R, and any of
        # them the component test failed to claim would otherwise BE the
        # answer. 1.05R is ~3 sigma of that scatter. The consequence is
        # stated rather than hidden: a genuine arch closer than 0.05R is
        # reported as "at the floor", not as a number.
        floor = 1.05
        near = (brad > floor * R) & (brad < 1.60 * R) & \
            (np.abs(blat) < 0.48 * Wd) & \
            ((BODY[:, ui] - c[ui]) > 0.20 * R)
        r["arch_min_clearance_m"] = float(brad[near].min() - R) \
            if near.sum() > 20 else None
        r["arch_clearance_points"] = int(near.sum())
        r["arch_clearance_floor_m"] = float((floor - 1.0) * R)
        # ---- contact patch, from the tyre carcass only
        r["contact_patch"] = _contact(ALL[carcass], c, a, R, Wd,
                                      m["ground_plane"], li, ti, ui)
    return m


def _contact(P, c, a, R, W, ground, li, ti, ui):
    if len(P) == 0:
        return dict(points=0, note="no tyre carcass points")
    d = P - c
    rad = np.linalg.norm(d - np.outer(d @ a, a), axis=1)
    lat = d @ a
    near = (rad > 0.90 * R) & (P[:, ui] < ground + 0.004)
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



def _angle_verdict(val, se, tol, method, k=2.0):
    """Three-way verdict that respects the instrument's own precision.

    A bootstrap SE of 0.17 deg cannot certify a 0.10 deg tolerance — but it
    can still REFUTE it. A wheel measured at 1.23 deg with SE 0.15 is seven
    standard errors outside a 0.1 deg band, and calling that "not measurable"
    would hide a real fault behind the instrument. So:

        |val| - k*se >  tol   ->  FAIL           (confidently out)
        |val| + k*se <= tol   ->  PASS           (confidently in)
        otherwise             ->  NOT MEASURABLE (the tolerance is inside the
                                                  instrument's noise band)

    k = 2 standard errors, i.e. roughly 95%.
    """
    if not np.isfinite(se):
        return dict(verdict="NOT MEASURABLE", measured=round(val, 4),
                    threshold=f"+-{tol}", method=method,
                    note="no uncertainty estimate available "
                         "(bootstrap disabled)")
    lo, hi = abs(val) - k * se, abs(val) + k * se
    note = f"|value| = {abs(val):.3f} deg, axis SE {se:.3f} deg, " \
           f"{k:.0f}-SE interval [{max(lo, 0):.3f}, {hi:.3f}] deg"
    if lo > tol:
        return dict(verdict="FAIL", measured=round(val, 4),
                    threshold=f"+-{tol}", method=method,
                    note=note + " — the whole interval is outside tolerance")
    if hi <= tol:
        return dict(verdict="PASS", measured=round(val, 4),
                    threshold=f"+-{tol}", method=method,
                    note=note + " — the whole interval is inside tolerance")
    return dict(verdict="NOT MEASURABLE", measured=round(val, 4),
                threshold=f"+-{tol}", method=method,
                note=note + " — the tolerance falls inside the instrument's "
                            "noise band; this mesh is not round enough to "
                            "settle it either way")


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
        for key, tol in (("toe", TOL["toe_deg"]), ("camber", TOL["camber_deg"])):
            val = r[f"{key}_deg"]
            se = r.get(f"{key}_se_deg", r["axis_se_deg"])
            g[f"{key}_{cn}"] = _angle_verdict(
                val, se, tol,
                "axis of revolution from a least-squares cylinder fit to the "
                "tread band, in the car frame; uncertainty is the bootstrap SE "
                "within one band and the spread across eight equally valid "
                "band selections, in quadrature")
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
    ap.add_argument("--frame", choices=["car", "raw"], default="car",
                    help="'car' (default) measures after the pose solve, which "
                         "is the frame the criteria are defined in. 'raw' "
                         "measures in the file's own frame — use it when the "
                         "numbers must line up with the FILE, e.g. for an "
                         "evidence render of the unrepaired car.")
    a = ap.parse_args()
    spec = load_spec(a.spec)
    m = measure(a.glb, spec=spec, nose=a.nose, bootstrap=not a.no_bootstrap,
                canonicalise=(a.frame == "car"))
    m = fender_and_arch(m)
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
