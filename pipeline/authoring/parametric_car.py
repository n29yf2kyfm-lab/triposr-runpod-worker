#!/usr/bin/env python3
"""parametric_car.py — hand-write a car GLB from its real dimensions.

WHY THIS EXISTS. `pipeline/trellis/STUDY_3D.md` measured the thing every
generator route has been failing on: a shut line is 3-5mm on a 4000mm car, i.e.
0.19-0.38 of ONE VOXEL at every open generator resolution, so it is below the
representable bandwidth and cannot be generated at all. The same study measured
that authored geometry carries 8-20x more real edges than generated geometry
(sharp_share: catalogue car 18.6%, generated car 0.8%). The conclusion is not
"tune the generator" — it is that panel features have to be AUTHORED. This is
the machine that authors them.

WHAT IT DOES. Given a car's published dimensions (length, width, height,
wheelbase, track, wheel size) plus a body style, it lofts a body from named
cross-section landmarks, then:

  * cuts REAL WINDOW OPENINGS and builds the glazing as its own mesh, so
    glass_probe returns clear/proven by construction rather than by luck;
  * cuts wheel arches and fits wheels with separate tyre and rim meshes, so
    paint can never reach the rubber (the owner's standing ruling);
  * ENGRAVES shut lines — bonnet, both doors per side, tailgate — as grooves
    with real walls that catch a shadow, which is what makes a car read as
    assembled rather than carved from soap;
  * emits the proven material scheme, so a respray can only move the body.

WHAT IT IS NOT. It is not a likeness of a specific car. The silhouette is
driven by real dimensions and body style, so a Yaris comes out Yaris-sized and
Yaris-shaped, but the grille graphic, lamp signature and character lines are
generic. Treat the output as a correctly-proportioned, correctly-featured base —
honest about what it is, and measurably sharper than anything the generators
produce.

Usage:
    python3 pipeline/authoring/parametric_car.py --make toyota --model yaris \
        --out yaris.glb
    python3 pipeline/authoring/parametric_car.py --length 4255 --width 1799 \
        --height 1452 --wheelbase 2637 --style hatch --out golf.glb
"""
import argparse
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from glb import GLB  # noqa: E402


# --------------------------------------------------------------------- specs
# Dimensions are the manufacturer's published figures in MILLIMETRES. Per the
# accuracy rule in CLAUDE.md these are verifiable facts, not inferred ones — add
# a car by looking its dimensions up, never by guessing them.
SPECS = {
    ("toyota", "yaris"):    dict(length=3885, width=1695, height=1510, wheelbase=2510,
                                 track=1470, wheel_d=608, tyre_w=175, style="hatch"),
    ("volkswagen", "golf"): dict(length=4255, width=1799, height=1452, wheelbase=2637,
                                 track=1549, wheel_d=636, tyre_w=205, style="hatch"),
    ("ford", "fiesta"):     dict(length=4040, width=1735, height=1476, wheelbase=2493,
                                 track=1493, wheel_d=619, tyre_w=195, style="hatch"),
    ("bmw", "3-series"):    dict(length=4709, width=1827, height=1435, wheelbase=2851,
                                 track=1565, wheel_d=664, tyre_w=225, style="saloon"),
    ("alfa-romeo", "stelvio"): dict(length=4687, width=1903, height=1671, wheelbase=2818,
                                    track=1615, wheel_d=709, tyre_w=255, style="suv"),
    ("audi", "a4"):         dict(length=4762, width=1847, height=1428, wheelbase=2820,
                                 track=1572, wheel_d=664, tyre_w=225, style="saloon"),
}

# Body-style shape parameters. These are the knobs that turn a set of box
# dimensions into a recognisable silhouette. Each is a fraction of the car's
# length (u, nose at 1.0) or of its height, so they scale with any car.
#
# CALIBRATION NOTE (v2 -> v3, from looking at the render): `cowl` is the single
# most identity-carrying number here and v1/v2 had it badly wrong at 0.66. With
# the front axle at u=0.82 on a Yaris, that put the base of the windscreen
# 0.63m BEHIND the axle, which is a 1950s bonnet — and the render looked exactly
# like that. On a modern transverse-engine car the cowl sits within ~0.1m of the
# front axle. Setting cowl near the axle fixes the whole silhouette at once.
# `bonnet_h` is a fraction of overall height; a real hatchback bonnet is ~0.58H,
# not the 0.655H v1 used.
STYLES = {
    "hatch":     dict(cowl=0.780, roof_f=0.655, roof_r=0.250, tail=0.050, belt=0.575,
                      tumble=0.82, roof_w=0.52, bonnet_h=0.585, boot=0.0),
    "saloon":    dict(cowl=0.790, roof_f=0.665, roof_r=0.315, tail=0.045, belt=0.585,
                      tumble=0.80, roof_w=0.50, bonnet_h=0.575, boot=0.22),
    "estate":    dict(cowl=0.785, roof_f=0.660, roof_r=0.150, tail=0.045, belt=0.575,
                      tumble=0.82, roof_w=0.54, bonnet_h=0.580, boot=0.0),
    "suv":       dict(cowl=0.770, roof_f=0.660, roof_r=0.210, tail=0.050, belt=0.555,
                      tumble=0.85, roof_w=0.56, bonnet_h=0.600, boot=0.0),
    "coupe":     dict(cowl=0.775, roof_f=0.620, roof_r=0.330, tail=0.050, belt=0.610,
                      tumble=0.76, roof_w=0.46, bonnet_h=0.560, boot=0.16),
}

NU, NV = 190, 56          # stations along the car, points around the half-section
SHUT_W = 0.0035           # groove half-width, in metres of car length
SHUT_DEPTH = 0.010        # how far the groove floor sits below the skin


class Car:
    def __init__(self, length, width, height, wheelbase, track, wheel_d, tyre_w,
                 style="hatch", name="car"):
        self.L = length / 1000.0
        self.W = width / 1000.0
        self.H = height / 1000.0
        self.WB = wheelbase / 1000.0
        self.TR = track / 1000.0
        self.RW = wheel_d / 2000.0                 # wheel RADIUS, metres
        self.TW = tyre_w / 1000.0
        self.s = STYLES.get(style, STYLES["hatch"])
        self.style = style
        self.name = name
        # axle positions in u (0 = tail, 1 = nose)
        overhang = (self.L - self.WB) / 2.0
        self.u_front = (overhang + self.WB) / self.L
        self.u_rear = overhang / self.L
        self.ground = 0.0

    # ------------------------------------------------------ silhouette curves
    def roofline(self, u):
        """Top of the body at station u — the single most identity-carrying curve."""
        s = self.s
        H = self.H
        if u <= s["tail"]:                                   # rear bumper top
            return H * (0.56 + 0.10 * u / max(s["tail"], 1e-6))
        if u <= s["roof_r"]:                                 # tailgate / boot rise
            t = (u - s["tail"]) / (s["roof_r"] - s["tail"])
            t = t * t * (3 - 2 * t)                          # smoothstep
            if s["boot"] > 0:                                # saloon: boot deck then C-pillar
                deck = H * 0.66
                if t < 0.45:
                    return deck * (0.86 + 0.14 * t / 0.45)
                tt = (t - 0.45) / 0.55
                tt = tt * tt * (3 - 2 * tt)
                return deck + (H - deck) * tt
            return H * (0.66 + 0.34 * t)
        if u <= s["roof_f"]:                                 # roof, gently domed
            mid = (s["roof_r"] + s["roof_f"]) / 2
            k = abs(u - mid) / max((s["roof_f"] - s["roof_r"]) / 2, 1e-6)
            return H * (1.0 - 0.012 * k * k)
        bh = H * s["bonnet_h"]
        if u <= s["cowl"]:                                   # windscreen
            t = (u - s["roof_f"]) / (s["cowl"] - s["roof_f"])
            t = t * t * (3 - 2 * t)
            return H - (H - bh) * t
        t = (u - s["cowl"]) / (1.0 - s["cowl"])              # bonnet to nose
        return bh - (bh * 0.085) * t * t

    def sill(self, u):
        """Underside of the visible body — the rocker line.

        v3 had this at 0.52 x wheel RADIUS, i.e. BELOW the wheel centres, so the
        body skirt reached almost to the ground and the car rendered like a taxi
        with sunken wheels. On a real car the rocker sits just above the wheel
        centre line — roughly 1.0-1.1 x radius — which is what makes the wheels
        read as wheels and gives the flank its visible ground shadow.
        """
        base = self.RW * 1.02
        if u < 0.08:                      # bumpers wrap slightly lower
            return base * (0.88 + 0.12 * u / 0.08)
        if u > 0.92:
            return base * (0.88 + 0.12 * (1 - u) / 0.08)
        return base

    def halfwidth(self, u):
        """Plan-view half width — FLAT-TOPPED, not a bell.

        v1 used sin(pi*u)**0.42, which pinches the body from the axles outward
        and rendered a bulbous 1940s nose and tail. A real car is within a few
        percent of full width from just behind the front bumper to just ahead of
        the rear one; only the last ~10% wraps in. Measured against the render,
        this single curve was the biggest single cause of "it doesn't look like
        a car".
        """
        e = 0.5 * self.W
        t = min(max(u, 0.0), 1.0)
        edge = min(t, 1.0 - t) / 0.065
        f = min(max(edge, 0.0), 1.0)
        f = f * f * (3 - 2 * f)                     # smoothstep into the corners
        # a real bumper is ~85% of maximum width, not 66% — v2's deeper taper
        # rendered a rounded snout instead of a bumper face
        return e * (0.85 + 0.15 * f)

    def belt_y(self, u):
        """Beltline height — the bottom edge of the side glass."""
        return self.sill(u) + (self.roofline(u) - self.sill(u)) * self.s["belt"]

    # ------------------------------------------------------- section geometry
    def section(self, u, nv=NV):
        """One half cross-section as (nv,2) points in (y, z), z >= 0.

        Built from named landmarks and resampled, so every returned point knows
        which REGION it belongs to — that is what makes window openings, shut
        lines and material assignment possible without any guesswork later.
        Returns (points, region_index) where region is one of:
            0 underbody, 1 sill, 2 lower body, 3 upper body/shoulder,
            4 glazing, 5 roof
        """
        w = self.halfwidth(u)
        y0, y1 = self.sill(u), self.roofline(u)
        yb = self.belt_y(u)
        s = self.s
        tumble = s["tumble"]
        roof_w = s["roof_w"]
        # landmark polyline from floor centre, out and up, over to roof centre
        pts = [
            (y0 + 0.02 * (y1 - y0), 0.0),           # 0 floor centre
            (y0 + 0.01 * (y1 - y0), w * 0.55),      # 1 floor edge
            (y0, w * 0.90),                          # 2 sill
            (y0 + (yb - y0) * 0.45, w * 0.995),      # 3 shoulder (widest)
            (yb, w * 0.965),                         # 4 beltline
            (yb + (y1 - yb) * 0.55, w * tumble),     # 5 mid glass (tumblehome)
            (y1 - (y1 - yb) * 0.10, w * roof_w),     # 6 roof rail
            (y1, w * roof_w * 0.55),                 # 7 roof edge
            (y1, 0.0),                               # 8 roof centre
        ]
        regions = [0, 0, 1, 2, 3, 4, 4, 5, 5]
        P = np.array(pts, dtype=np.float64)
        # chordal resample with light smoothing so the section reads as surfaced
        d = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))]
        d /= d[-1]
        t = np.linspace(0, 1, nv)
        out = np.empty((nv, 2))
        reg = np.empty(nv, dtype=int)
        for k in range(2):
            out[:, k] = np.interp(t, d, P[:, k])
        reg[:] = np.interp(t, d, regions).round().astype(int)
        # one pass of Laplacian smoothing on the interior keeps the corners soft
        # without losing the landmarks' proportions
        sm = out.copy()
        sm[1:-1] = 0.25 * out[:-2] + 0.5 * out[1:-1] + 0.25 * out[2:]
        return sm, reg

    # ------------------------------------------------------------- shut lines
    def shut_positions(self):
        """u positions of the panel seams, derived from the axles, not guessed.

        A door seam sits just behind the front wheel arch and the rear one just
        ahead of the rear arch; the bonnet seam sits at the cowl; the tailgate
        seam at the rear roof pillar.
        """
        s = self.s
        arch_f = self.u_front + self.RW / self.L * 1.05
        arch_r = self.u_rear - self.RW / self.L * 1.05
        seams = [
            (s["cowl"] + 0.005, (0, 5)),      # bonnet / cowl shut
            (arch_f, (0, 5)),                 # A-pillar side, front door leading edge
            ((arch_f + arch_r) / 2, (0, 4)),  # door-to-door
            (arch_r, (0, 4)),                 # rear door trailing edge
            (s["roof_r"] - 0.01, (3, 5)),     # tailgate / boot shut
        ]
        return [(u, r) for u, r in seams if 0.05 < u < 0.97]


def build(car, nu=NU, nv=NV):
    """Loft the body and return per-part (verts, faces) plus the region grid."""
    seams = car.shut_positions()
    us = list(np.linspace(0.012, 0.988, nu))
    for u, _ in seams:                       # insert the groove's own stations
        us += [u - SHUT_W, u - SHUT_W * 0.45, u + SHUT_W * 0.45, u + SHUT_W]
    us = np.array(sorted(us))

    NUu = len(us)
    P = np.zeros((NUu, nv, 3))
    REG = np.zeros((NUu, nv), dtype=int)
    for i, u in enumerate(us):
        sec, reg = car.section(u, nv)
        inset = 0.0
        for su, (r0, r1) in seams:
            if abs(u - su) <= SHUT_W * 0.5:
                inset = SHUT_DEPTH
                reg_mask = (reg >= r0) & (reg <= r1)
                break
        else:
            reg_mask = np.zeros(nv, dtype=bool)
        y, z = sec[:, 0].copy(), sec[:, 1].copy()
        if inset:
            # push the groove floor in along the local section normal
            cy = (y.max() + y.min()) / 2
            ny = y - cy
            nz = z
            ln = np.hypot(ny, nz) + 1e-9
            y[reg_mask] -= inset * (ny / ln)[reg_mask]
            z[reg_mask] -= inset * (nz / ln)[reg_mask]
        P[i, :, 0] = car.L * (u - 0.5)
        P[i, :, 1] = y
        P[i, :, 2] = z
        REG[i] = reg

    # ---- which quads are glazing: the glass band, over the cabin only
    s = car.s
    glass = np.zeros((NUu - 1, nv - 1), dtype=bool)
    for i in range(NUu - 1):
        u = 0.5 * (us[i] + us[i + 1])
        if not (s["roof_r"] - 0.005 < u < s["cowl"] + 0.02):
            continue
        for j in range(nv - 1):
            r = REG[i, j]
            if r == 4:
                glass[i, j] = True
            # windscreen and backlight: the top band is glass where the roof
            # is steeply raked rather than horizontal
            elif r == 5 and (u > s["roof_f"] or u < s["roof_r"] + 0.06):
                glass[i, j] = True

    # ---- wheel arches
    # Removing whole quads leaves a staircase edge — plainly visible in the v1
    # render and the first thing that read as "computer generated". So the ring
    # of vertices straddling the arch circle is SNAPPED onto it first, giving a
    # clean circular lip, and only then are the interior quads dropped.
    arch_r = car.RW * 1.16
    axles = [car.L * (car.u_front - 0.5), car.L * (car.u_rear - 0.5)]
    for i in range(NUu):
        flank = car.halfwidth(us[i]) * 0.5
        for j in range(nv):
            x, y, z = P[i, j]
            if z < flank or REG[i, j] > 3:
                continue
            for ax in axles:
                d = math.hypot(x - ax, y - car.RW)
                if d < 1e-6 or abs(d - arch_r) > arch_r * 0.16:
                    continue
                k = arch_r / d
                P[i, j, 0] = ax + (x - ax) * k
                P[i, j, 1] = car.RW + (y - car.RW) * k
                break

    arch = np.zeros((NUu - 1, nv - 1), dtype=bool)
    for i in range(NUu - 1):
        flank = car.halfwidth(us[i]) * 0.5
        for j in range(nv - 1):
            if REG[i, j] > 3 or P[i, j, 2] < flank:
                continue
            x = 0.25 * (P[i, j, 0] + P[i + 1, j, 0] + P[i, j + 1, 0] + P[i + 1, j + 1, 0])
            y = 0.25 * (P[i, j, 1] + P[i + 1, j, 1] + P[i, j + 1, 1] + P[i + 1, j + 1, 1])
            for ax in axles:
                if math.hypot(x - ax, y - car.RW) < arch_r * 0.995:
                    arch[i, j] = True
                    break

    def emit(mask, mirror=True):
        """Turn a quad mask over the (station, section) grid into a mesh."""
        V, F = [], []
        idx = {}

        def vid(i, j, side):
            key = (i, j, side)
            if key not in idx:
                p = P[i, j].copy()
                if side < 0:
                    p[2] = -p[2]
                idx[key] = len(V)
                V.append(p)
            return idx[key]

        sides = (1, -1) if mirror else (1,)
        for side in sides:
            for i in range(NUu - 1):
                for j in range(nv - 1):
                    if not mask[i, j]:
                        continue
                    a = vid(i, j, side)
                    b = vid(i + 1, j, side)
                    c = vid(i + 1, j + 1, side)
                    d = vid(i, j + 1, side)
                    if side > 0:
                        F += [[a, b, c], [a, c, d]]
                    else:
                        F += [[a, c, b], [a, d, c]]
        if not V:
            return np.zeros((0, 3)), np.zeros((0, 3), dtype=np.uint32)
        return np.array(V), np.array(F, dtype=np.uint32)

    def caps():
        """Close the front and rear of the loft.

        v1 had none, so the nose rendered as a dark hole straight into the
        interior — the single most obvious defect in the first render. Each end
        ring is fanned to its own centroid across BOTH sides, which also gives
        the bumper a flat face to sit on rather than a dome.
        """
        V, F = [], []
        for end, outward in ((0, -1), (NUu - 1, 1)):
            ring_pts = [P[end, j].copy() for j in range(nv)]
            ring_pts += [np.array([p[0], p[1], -p[2]]) for p in reversed(ring_pts[1:-1])]
            base = len(V)
            V += ring_pts
            c = len(V)
            V.append(np.mean(ring_pts, axis=0))
            n = len(ring_pts)
            for k in range(n):
                a, b = base + k, base + (k + 1) % n
                F.append([c, a, b] if outward > 0 else [c, b, a])
        return np.array(V), np.array(F, dtype=np.uint32)

    def arch_liners():
        """A dark inner surface behind each arch, so the cut is not see-through."""
        V, F = [], []
        depth = car.TW * 1.15
        for ax in axles:
            for side in (1, -1):
                # take the flank z at this station as the arch mouth
                i_near = int(np.argmin(np.abs(car.L * (us - 0.5) - ax)))
                zo = car.halfwidth(us[i_near]) * 0.985 * side
                angs = np.linspace(math.pi * 0.02, math.pi * 0.98, 26)
                base = len(V)
                for a in angs:
                    V.append([ax + arch_r * math.cos(a), car.RW + arch_r * math.sin(a), zo])
                for a in angs:
                    V.append([ax + arch_r * 0.97 * math.cos(a),
                              car.RW + arch_r * 0.97 * math.sin(a), zo - depth * side])
                m = len(angs)
                for k in range(m - 1):
                    a0, a1 = base + k, base + k + 1
                    b0, b1 = base + m + k, base + m + k + 1
                    if side > 0:
                        F += [[a0, b0, b1], [a0, b1, a1]]
                    else:
                        F += [[a0, b1, b0], [a0, a1, b1]]
        return np.array(V), np.array(F, dtype=np.uint32)

    body_mask = ~glass & ~arch
    body = emit(body_mask)
    glazing = emit(glass)
    return body, glazing, caps(), arch_liners()


def wheel(cx, cz, r, tw, spokes=5, seg=48):
    """Tyre + rim as SEPARATE meshes. Returns (tyre, rim)."""
    def ring(radius, zoff):
        a = np.linspace(0, 2 * math.pi, seg, endpoint=False)
        return np.c_[cx + radius * np.cos(a), r + radius * np.sin(a),
                     np.full(seg, cz + zoff)]

    zi, zo = -np.sign(cz) * tw / 2, np.sign(cz) * tw / 2
    rim_r = r * 0.66
    V = np.vstack([ring(r, zi), ring(r, zo), ring(rim_r, zi), ring(rim_r, zo)])
    F = []
    for i in range(seg):
        j = (i + 1) % seg
        F += [[i, seg + i, seg + j], [i, seg + j, j]]                      # tread
        F += [[2 * seg + i, 3 * seg + j, 3 * seg + i],                     # inner wall
              [2 * seg + i, 2 * seg + j, 3 * seg + j]]
        F += [[i, j, 2 * seg + j], [i, 2 * seg + j, 2 * seg + i]]          # sidewall out
        F += [[seg + i, 3 * seg + i, 3 * seg + j], [seg + i, 3 * seg + j, seg + j]]
    tyre = (V, np.array(F, dtype=np.uint32))

    # rim: a dished face with real spoke gaps, so the wheel reads as a wheel
    RV, RF = [], []
    hub = r * 0.17
    face_z = cz + zo * 0.55
    centre = len(RV)
    RV.append([cx, r, face_z])
    per = max(3, int(seg / spokes / 2))
    for k in range(spokes):
        a0 = 2 * math.pi * k / spokes + 0.12
        a1 = 2 * math.pi * (k + 1) / spokes - 0.12
        angs = np.linspace(a0, a1, per)
        base = len(RV)
        for a in angs:
            RV.append([cx + hub * math.cos(a), r + hub * math.sin(a), face_z])
        for a in angs:
            RV.append([cx + rim_r * math.cos(a), r + rim_r * math.sin(a), face_z])
        for t in range(per - 1):
            i0, i1 = base + t, base + t + 1
            o0, o1 = base + per + t, base + per + t + 1
            RF += [[i0, o0, o1], [i0, o1, i1]]
        RF += [[centre, base, base + per - 1]]
    # rim barrel so it is not a floating disc
    ai = np.linspace(0, 2 * math.pi, seg, endpoint=False)
    b0 = len(RV)
    for a in ai:
        RV.append([cx + rim_r * math.cos(a), r + rim_r * math.sin(a), face_z])
    for a in ai:
        RV.append([cx + rim_r * math.cos(a), r + rim_r * math.sin(a), cz + zi])
    for i in range(seg):
        j = (i + 1) % seg
        RF += [[b0 + i, b0 + seg + i, b0 + seg + j], [b0 + i, b0 + seg + j, b0 + j]]
    rim = (np.array(RV), np.array(RF, dtype=np.uint32))
    return tyre, rim


def disc(cx, cy, cz, rx, ry, depth, seg=28):
    """A shallow inset disc — used for lamp lenses and the grille."""
    a = np.linspace(0, 2 * math.pi, seg, endpoint=False)
    front = np.c_[cx + rx * np.cos(a), cy + ry * np.sin(a), np.full(seg, cz)]
    back = front.copy()
    back[:, 2] -= np.sign(cz) * depth if cz else depth
    V = np.vstack([front, back, [[cx, cy, back[0, 2]]]])
    F = []
    c = 2 * seg
    for i in range(seg):
        j = (i + 1) % seg
        F += [[i, seg + i, seg + j], [i, seg + j, j], [c, seg + j, seg + i]]
    return V, np.array(F, dtype=np.uint32)


def make(car, out):
    g = GLB(generator=f"parametric_car/{car.name}")
    m_paint = g.material("Material_0", [0.72, 0.73, 0.75, 1.0], 0.10, 0.28)
    m_glass = g.material("Glass_Tint", [0.03, 0.04, 0.05, 0.26], 0.0, 0.05, blend=True)
    m_tyre = g.material("Tyre_Rubber", [0.026, 0.026, 0.030, 1.0], 0.0, 0.92)
    m_rim = g.material("Rim_Alloy", [0.52, 0.53, 0.55, 1.0], 0.92, 0.28)
    m_lamp = g.material("Lamp_Lens", [0.070, 0.072, 0.085, 1.0], 0.0, 0.07)
    m_dark = g.material("Trim_Dark", [0.020, 0.020, 0.022, 1.0], 0.0, 0.80)

    (bV, bF), (gV, gF), (cV, cF), (aV, aF) = build(car)
    g.mesh("body", bV, bF, m_paint)
    g.mesh("body_caps", cV, cF, m_paint)
    g.mesh("glazing", gV, gF, m_glass)
    g.mesh("arch_liner", aV, aF, m_dark)

    xf = car.L * (car.u_front - 0.5)
    xr = car.L * (car.u_rear - 0.5)
    half = car.TR / 2
    for n, (x, z) in enumerate([(xf, half), (xf, -half), (xr, half), (xr, -half)]):
        (tv, tf), (rv, rf) = wheel(x, z, car.RW, car.TW)
        g.mesh(f"tyre_{n}", tv, tf, m_tyre)
        g.mesh(f"rim_{n}", rv, rf, m_rim)

    nose = car.L * 0.5
    lampy = car.roofline(0.985) * 0.62
    for n, z in enumerate((car.W * 0.30, -car.W * 0.30)):
        v, f = disc(nose - 0.10, lampy, z, 0.16, 0.075, 0.05)
        g.mesh(f"lamp_f{n}", v, f, m_lamp)
    for n, z in enumerate((car.W * 0.32, -car.W * 0.32)):
        v, f = disc(-nose + 0.09, car.roofline(0.02) * 0.72, z, 0.13, 0.070, 0.05)
        g.mesh(f"lamp_r{n}", v, f, m_lamp)
    v, f = disc(nose - 0.06, lampy * 0.62, 0.0, 0.30, 0.085, 0.06)
    g.mesh("grille", v, f, m_dark)

    size = g.save(out)
    return size, len(bV), len(bF), len(gF)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--make")
    ap.add_argument("--model")
    ap.add_argument("--length", type=float)
    ap.add_argument("--width", type=float)
    ap.add_argument("--height", type=float)
    ap.add_argument("--wheelbase", type=float)
    ap.add_argument("--track", type=float)
    ap.add_argument("--wheel-d", type=float, default=640)
    ap.add_argument("--tyre-w", type=float, default=205)
    ap.add_argument("--style", default="hatch", choices=sorted(STYLES))
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    if a.make and a.model:
        key = (a.make.lower(), a.model.lower())
        if key not in SPECS:
            raise SystemExit(f"no spec for {key}. Known: {sorted(SPECS)}\n"
                             "Add it with the manufacturer's published dimensions "
                             "— never estimate them (CLAUDE.md accuracy rule).")
        spec = dict(SPECS[key])
        name = f"{a.make}-{a.model}"
    else:
        missing = [k for k in ("length", "width", "height", "wheelbase")
                   if getattr(a, k) is None]
        if missing:
            raise SystemExit(f"give --make/--model, or all of {missing}")
        spec = dict(length=a.length, width=a.width, height=a.height,
                    wheelbase=a.wheelbase, track=a.track or a.width * 0.86,
                    wheel_d=a.wheel_d, tyre_w=a.tyre_w, style=a.style)
        name = os.path.splitext(os.path.basename(a.out))[0]

    car = Car(name=name, **spec)
    size, nv, nf, ng = make(car, a.out)
    print(f"{a.out}: {size/1024:.0f} KB  body {nv} verts / {nf} tris  "
          f"glazing {ng} tris  style={car.style}  "
          f"L{car.L:.3f} W{car.W:.3f} H{car.H:.3f} WB{car.WB:.3f}")
    print(f"shut lines engraved: {len(car.shut_positions())}")


if __name__ == "__main__":
    main()
