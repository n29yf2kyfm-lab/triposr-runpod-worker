#!/usr/bin/env python3
"""rear_zone.py — the shared radial parameterisation of this car's tail.

Every stage (strip, rebuild, backstop, verification) uses THIS module, so the
strip footprint and the rebuilt panel are the same surface by construction and
cannot drift apart.

WHY RADIAL, not (y,z)->x: the rear bumper WRAPS the corners, where the surface
turns side-facing and x stops being a function of (y,z). A sweep about a pivot
handles the turn naturally -- the parameterisation Gate 4 validated for its
corner lamp units.

WHY PER SIDE: the tail of this car is sheared toward -z by 100-160 mm
(measured here at every height, agreeing with Gate 4's 150 mm). Nothing is
mirrored: the pivot's z is the section's OWN centre at that height, and the
radius is measured from that side's own skin. This is the wheel_stage /
g4_lamps2 pattern -- one design, seated per side.

Frame facts for this file, established by render, not assumed:
  TAIL at +X, nose at -X.  az090 = straight rear.
"""
import numpy as np, trimesh

# --- panel bands, every number measured in measurements/tail_profile.json ---
# bumper top shut line: the tail surface steps back 48 mm between y 0.550 and
# y 0.570 (Gate 4 measured the same step as 44 mm between 0.54 and 0.56).
Y_BUMPER_TOP = 0.560
# bumper lower edge: x jumps 1.92 -> 2.03 between y 0.210 and y 0.230.
Y_BUMPER_BOT = 0.230
# backlight sill: Rear_Glass starts at y 0.894.
Y_HATCH_TOP = 0.900
Y_HATCH_BOT = Y_BUMPER_TOP
# tailgate lateral edge: Gate 4's lamp-derived shut line (hatch lens units end
# at |z| 0.520, outer units start at 0.535 -> midpoint).
Z_HATCH_EDGE = 0.5275


def load_points(sc, exclude_prefix=("Tail_Lens", "Tail_Housing", "Rear_Plate")):
    """face centres + owner index, excluding CONSTRUCTED parts.

    The Gate-4 lamp and plate solids sit ON the surface; including them would
    make the measured profile ride the lens crest instead of the panel.
    """
    G = dict(sc.geometry)
    names = [n for n in G if not n.startswith(exclude_prefix)]
    pts = [G[n].triangles_center for n in names]
    own = [np.full(len(p), i) for i, p in enumerate(pts)]
    return np.vstack(pts), np.concatenate(own), names


def section_centre(P, ys, half=0.030):
    """pivot (x_c, z_c) per height band, from the section's OWN extremes."""
    out = []
    for y in ys:
        m = (np.abs(P[:, 1] - y) < half) & (P[:, 0] > 1.30)
        if m.sum() < 50:
            out.append((np.nan, np.nan)); continue
        z = P[m, 2]
        zc = 0.5 * (np.percentile(z, 99.5) + np.percentile(z, 0.5))
        xc = np.percentile(P[m, 0], 99.5) - 0.75
        out.append((float(xc), float(zc)))
    return np.array(out)


def polar(P, xc, zc):
    dx = P[:, 0] - xc; dz = P[:, 2] - zc
    return np.hypot(dx, dz), np.degrees(np.arctan2(dz, dx))


def outer_radius(P, xc, zc, y, ys_half, th_edges, min_pts=3, spike_mm=12.0):
    """OUTER-EXTREME radius per theta cell, with a lone-spike guard.

    Gate 4: a p95 estimator is pulled short by the melt's dense INTERIOR
    points and seated a lens 150 mm inside the body. So: take the max, and
    reject it as a spike if it is >12 mm proud of the 2nd..5th largest.
    """
    m = (np.abs(P[:, 1] - y) < ys_half) & (P[:, 0] > xc)
    r, th = polar(P[m], xc, zc)
    out = np.full(len(th_edges) - 1, np.nan)
    idx = np.digitize(th, th_edges) - 1
    for k in range(len(out)):
        rr = np.sort(r[idx == k])[::-1]
        if len(rr) < min_pts: continue
        r0 = rr[0]
        if len(rr) >= 5 and (r0 - rr[1:5].max()) > spike_mm / 1000.0:
            r0 = rr[1]
        out[k] = r0
    return out
