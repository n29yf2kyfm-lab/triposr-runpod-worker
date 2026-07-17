#!/usr/bin/env python3
"""Name-independent geometry audit for ingested car GLBs.

The paint/material QC could not catch cars that are upside-down, on their side,
wheels-removed race shells, doors-open poses, or wrecked floorpans — those are
*structural* faults, invisible to a coverage check, and scraped GLBs almost never
name their glass/wheel materials so a name-based check is unreliable. This module
judges structure from the raw world-space vertex distribution instead.

Signals (all fractions of the model's own bounding box — scale & unit free; the
vertical axis is taken as the smallest bbox extent, matching the render worker's
auto-upright assumption height < width < length):

  h_over_l      height / longest-horizontal. Low sedans/sports ~0.24-0.30,
                saloons/hatch ~0.30-0.42, SUV ~0.45-0.52. Very low (<0.22) =
                flat floorpan/road-scene/wreck; very high = doors-up / on-side.
  top_over_bot  width of the top third / width of the bottom third. A car is wide
                at the wheels and narrow at the roof, so good cars sit ~0.65-0.80.
                >1.2 = wide-top (roll cage / wheels-up flip); <0.55 = flip/on-side.
  glass_zf      area-weighted glass-material centroid height (0=floor..1=roof).
                Only trustworthy when glass_af is meaningful; <0.40 = upside-down.
  glass_af      glass share of surface area (used only to gate glass_zf).

Calibrated 2026-07-17 against a 12-car known-truth set: 5/6 broken auto-rejected
(upside-down Qashqai, Astra floorpan, A3 roll-cage, Golf-6 flip, doors-open
Fiesta), 0/6 good cars false-rejected. The one residual miss is soft "melt"
geometry with normal proportions — that still needs a human glance at the hero.

`glass_zf`/`glass_af` are supplied by the render worker's material classifier
(handler `audit` block); `geom_signals` here computes the name-independent part
from a GLB path via trimesh (world-space verts, decompresses draco).
"""
import numpy as np


def geom_signals(glb_path):
    """Return {h_over_l, top_over_bot, upper_frac} from a GLB's world-space verts."""
    import trimesh
    sc = trimesh.load(glb_path, process=False)
    tf = {}
    if hasattr(sc, "graph"):
        for name in sc.graph.nodes_geometry:
            T, gname = sc.graph[name]
            tf.setdefault(gname, []).append(T)
    allv = []
    items = sc.geometry.items() if hasattr(sc, "geometry") else [("m", sc)]
    for gname, g in items:
        v = np.asarray(g.vertices)
        for T in tf.get(gname, [np.eye(4)]):
            allv.append(trimesh.transform_points(v, T))
    V = np.vstack(allv)
    lo = V.min(0); hi = V.max(0); ext = hi - lo
    up = int(np.argmin(ext)); horiz = [a for a in range(3) if a != up]
    length = max(ext[horiz[0]], ext[horiz[1]]) or 1.0
    h_over_l = round(float(ext[up] / length), 3)
    z = V[:, up]; zlo = z.min(); zspan = ext[up] or 1.0; zf = (z - zlo) / zspan

    def band_w(a, b):
        m = (zf >= a) & (zf <= b)
        if m.sum() < 20:
            return 0.0
        P = V[m][:, horiz]
        return float(max(np.ptp(P[:, 0]), np.ptp(P[:, 1])))

    bot = band_w(0.0, 0.33); top = band_w(0.67, 1.0)
    top_over_bot = round(top / bot, 3) if bot > 1e-6 else 9.99
    return {"h_over_l": h_over_l, "top_over_bot": top_over_bot,
            "upper_frac": round(float((zf > 0.65).mean()), 3)}


def verdict(geom, handler_audit=None, coverage=None):
    """Combine geometry signals with the render worker's glass metrics.

    Returns (verdict, reasons) where verdict is 'reject' | 'warn' | 'ok'.
    'reject' cars must never reach a human sheet; 'warn' cars are shown but
    flagged (tall estates/vans, and the geometry-normal 'melt' cases).

    `coverage` is the render worker's recolour body-paint share. A fully
    transparent 'glass shell' GLB (every material transmissive, no solid
    body) has normal proportions so no geometry signal fires, but the body
    detector finds nothing to paint -> coverage collapses to ~0. A real car
    always paints >=0.15, so coverage below ~0.02 means there is no opaque
    body at all: a see-through shell or an empty scene. (Caught the glass
    Mitsubishi Colt that passed every geometry check, 2026-07-17.)
    """
    hh = handler_audit or {}
    tob = geom["top_over_bot"]; hl = geom["h_over_l"]
    gaf = hh.get("glass_af") or 0
    gzf = hh.get("glass_zf")
    R, W = [], []
    if coverage is not None and coverage < 0.02:
        R.append(f"glass-shell/no-body(coverage={coverage})")
    if gaf > 0.012 and gzf is not None and gzf < 0.40:
        R.append(f"upside-down(glass_zf={gzf})")
    if tob > 1.20:
        R.append(f"wide-top/cage(tob={tob})")
    if tob < 0.40:
        R.append(f"flipped/on-side(tob={tob})")
    if hl < 0.22:
        R.append(f"floorpan/wreck(h/l={hl})")
    if tob < 0.62 and hl > 0.50:
        R.append(f"doors-open(tob={tob},h/l={hl})")
    # tob 0.40-0.55: a genuinely flipped/on-side car has a narrow top third, but so
    # does an upright PICKUP (open bed, no rear roof) or convertible/targa. Don't
    # hard-reject that zone — inversion is already caught by glass_zf<0.40 above and
    # by the h/l floor; flag it for the human sheet instead of binning good trucks.
    if not R and 0.40 <= tob < 0.55:
        W.append(f"low-top(tob={tob})=pickup/convertible?")
    if not R and hl > 0.52:
        W.append(f"tall(h/l={hl})=van/estate?")
    return ("reject", R) if R else (("warn", W) if W else ("ok", []))
