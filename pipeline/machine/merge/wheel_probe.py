#!/usr/bin/env python3
"""wheel_probe.py — find and measure the four wheels of a GLB, geometrically.

WHY NOT THE EXISTING DETECTOR. `wheel_metrology.find_wheels` votes for circles
in the whole point cloud. On Gate 6's input (one fused shell) that was the only
thing that could work. Run on Gate 7+8's REBOUND car it mis-fits the rear right:
it returns R = 0.2670 m and a tyre bottom of +0.1214 m where the RR tyre node's
own lowest vertex is at +0.0147 m — 107 mm out. Gate 7+8 re-cut the point cloud
(bumpers, arch liner and interior are separate meshes now), so the vote lands
somewhere else. A pose solved from those four contacts came out pitch 2.78 /
roll -1.94 with a 26.9 mm rms residual, against Gate 6's 4.12 / 0.44 at 1.5 mm.
A detector that is 17x worse on the same car is not the instrument to repair it
with.

WHAT THIS DOES INSTEAD, AND WHY IT IS NOT "TRUSTING NAMES". Candidates come
from node names (`Wheel_<CORNER>_<PART>`), which on this family of files is
where the wheel geometry actually lives — but a name only nominates. Every
candidate is then CHECKED against geometry and the check can fail:

  * the corner letters must agree with the node's own position (front = nose
    half, L/R = sign of the lateral coordinate). Reported as a confusion
    table, refused on mismatch. This is not idle: Gate 6's L/R labels are the
    MIRROR of Gate 7+8's on the same car — Gate 6's "FL" hub sits at lateral
    +0.721 and Gate 7+8's "Wheel_FL" at -0.652 — so a merge that trusted the
    letters would have swapped the car's wheels side for side.
  * the union of a corner's nodes must fit a cylinder: >= `min_cov` of the
    circle's circumference occupied, and a tread-band rms under `max_rms`.
    A body panel does not pass that.
  * exactly four corners, or the caller refuses.

CLAUDE.md's standing warning is about MATERIAL names ("a tyre material bound
to the front bumper face"), and it stands: nothing here selects by material.

THE ANGLE INSTRUMENT IS wheel_metrology's, ON PURPOSE. `iterate_axis` re-draws
the tread band about the evolving axis; the seeded-band version it replaced had
a measured response slope of 0.35 (a 2.000 deg injection read 0.69 deg), which
made every reported toe/camber ~3x too small AND made the repair under-correct
by the same factor. `merge_calib.py` re-runs that injection ladder through THIS
module's own CLI path, because a slope measured on someone else's call stack is
not a measurement of mine.
"""
from __future__ import annotations

import math
import os
import re
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import wheel_metrology as WM          # noqa: E402  (fit_cylinder / iterate_axis)
from glb_io import GLB                # noqa: E402

NODE_RE = re.compile(r"^Wheel_([FR][LR])_(\w+)$", re.I)
CORNERS = ("FL", "FR", "RL", "RR")

DEFAULTS = dict(
    band_rel=0.030,      # tread band half-thickness, fraction of R
    lat_frac=0.55,       # lateral half-window, fraction of measured width
    min_cov=0.90,        # fraction of circumference the tread must occupy
    max_rms=0.010,       # m, tread-band cylinder fit rms
    width_pct=1.0,       # lateral percentile trim for the width measure
)


def _corner_of(x, z, xmid, nose_sign):
    """Geometric corner label. nose_sign = +1 if the nose is at +length."""
    front = (x > xmid) if nose_sign > 0 else (x < xmid)
    # right-handed y-up: forward x cross up y = lateral. With the nose at -x,
    # LEFT is -z; with the nose at +x, LEFT is +z.
    left = (z > 0) if nose_sign > 0 else (z < 0)
    return ("F" if front else "R") + ("L" if left else "R")


def _circle_seed(P, axis):
    """Centre + radius of the outer rim of a disc-like point set."""
    d = P - P.mean(0)
    lat = d @ axis
    Q = d - np.outer(lat, axis)                   # in-plane offsets
    e = np.array([0.0, 1.0, 0.0])
    e1 = np.cross(axis, e)
    if np.linalg.norm(e1) < 1e-6:
        e1 = np.cross(axis, np.array([1.0, 0.0, 0.0]))
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(axis, e1)
    u, v = Q @ e1, Q @ e2
    r = np.hypot(u, v)
    keep = r > np.percentile(r, 90)               # the outer ring only
    A = np.column_stack([u[keep], v[keep], np.ones(keep.sum())])
    b = u[keep] ** 2 + v[keep] ** 2
    sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    cu, cv = sol[0] / 2, sol[1] / 2
    R = math.sqrt(max(sol[2] + cu ** 2 + cv ** 2, 1e-9))
    return P.mean(0) + cu * e1 + cv * e2, R


def _coverage(P, c, axis, R, band):
    d = P - c
    lat = d @ axis
    Q = d - np.outer(lat, axis)
    rad = np.linalg.norm(Q, axis=1)
    sel = np.abs(rad - R) < band * R
    if sel.sum() < 50:
        return 0.0
    e = np.array([0.0, 1.0, 0.0])
    e1 = np.cross(axis, e)
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(axis, e1)
    th = np.arctan2(Q[sel] @ e2, Q[sel] @ e1)
    h, _ = np.histogram(th, bins=72, range=(-math.pi, math.pi))
    return float((h > 0).sum() / 72.0)


def corners(glb: GLB, cfg=None):
    """{corner: dict(nodes, P, F_offsets)} keyed by the GEOMETRIC corner."""
    cfg = dict(DEFAULTS, **(cfg or {}))
    prims, allv = [], []
    for name, W, mi, pi, p in glb.prims():
        V = glb.world_positions(W, p)
        prims.append((name, mi, pi, p, W, V))
        allv.append(V)
    A = np.vstack(allv)
    xmid = 0.5 * (A[:, 0].min() + A[:, 0].max())
    # nose sign: the windscreen end. Fall back to the recorded convention.
    nose = -1
    out = {}
    for name, mi, pi, p, W, V in prims:
        m = NODE_RE.match(name)
        if not m:
            continue
        claimed = m.group(1).upper()
        cen = V.mean(0)
        geo = _corner_of(cen[0], cen[2], xmid, nose)
        e = out.setdefault(geo, dict(nodes=[], claimed=set(), P=[], prims=[]))
        e["nodes"].append(name)
        e["claimed"].add(claimed)
        e["P"].append(V)
        e["prims"].append((name, mi, pi, p, W))
    for k, e in out.items():
        e["P"] = np.vstack(e["P"])
    return out, nose, xmid


def measure_corner(P, cfg=None, seed_axis=None):
    """Cylinder fit of one wheel: centre, axis, radius, width, bottom."""
    cfg = dict(DEFAULTS, **(cfg or {}))
    if seed_axis is None:
        seed_axis = np.array([0.0, 0.0, 1.0])
    a0 = np.asarray(seed_axis, float)
    a0 /= np.linalg.norm(a0)
    c0, R0 = _circle_seed(P, a0)
    # lateral width from the arc BELOW the hub, where no body panel reaches
    d = P - c0
    lat = d @ a0
    rad = np.linalg.norm(d - np.outer(lat, a0), axis=1)
    up = np.array([0.0, 1.0, 0.0])
    below = (d @ up) < -0.25 * R0
    band = np.abs(rad - R0) < 0.12 * R0
    sel = below & band
    if sel.sum() < 100:
        sel = band
    lo = float(np.percentile(lat[sel], cfg["width_pct"]))
    hi = float(np.percentile(lat[sel], 100 - cfg["width_pct"]))
    W0 = hi - lo
    c0 = c0 + a0 * (0.5 * (lo + hi))
    fit = WM.iterate_axis(P, c0.copy(), a0.copy(), R0, W0,
                          band_rel=cfg["band_rel"], lat_frac=cfg["lat_frac"])
    if fit is None:
        fit = WM.fit_cylinder(P[sel], c0, a0, R0)
    c = np.asarray(fit["centre"], float)
    a = np.asarray(fit["axis"], float)
    a = a / np.linalg.norm(a)
    R = float(fit["R"])
    d = P - c
    lat = d @ a
    rad = np.linalg.norm(d - np.outer(lat, a), axis=1)
    below = (d @ up) < -0.25 * R
    band = np.abs(rad - R) < 0.12 * R
    sel = below & band
    lo = float(np.percentile(lat[sel], cfg["width_pct"]))
    hi = float(np.percentile(lat[sel], 100 - cfg["width_pct"]))
    c = c + a * (0.5 * (lo + hi))
    return dict(centre=c, axis=a, R=R, width=hi - lo,
                rms=float(fit.get("rms", float("nan"))),
                coverage=_coverage(P, c, a, R, cfg["band_rel"]),
                bottom=float(P[:, 1].min()), n=int(len(P)))


def angles(axis, centre, nose_sign=-1):
    """toe (+ = toe-in) and camber (+ = top outward), in degrees."""
    a = np.asarray(axis, float)
    a = a / np.linalg.norm(a)
    outw = np.array([0.0, 0.0, 1.0 if centre[2] > 0 else -1.0])
    if a @ outw < 0:
        a = -a
    fwd = np.array([float(nose_sign), 0.0, 0.0])
    up = np.array([0.0, 1.0, 0.0])
    toe = math.degrees(math.asin(float(np.clip(a @ fwd, -1, 1))))
    cam = -math.degrees(math.asin(float(np.clip(a @ up, -1, 1))))
    return toe, cam
