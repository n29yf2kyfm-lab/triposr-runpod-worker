#!/usr/bin/env python3
"""kit.py — parts built here rather than borrowed from the master.

alloy_wheel: a plain five-spoke alloy with no maker's design or badge, so a
car made from the Golf master does not wear the GTI's own wheels. Built in
the wheel's frame (axis along x, outer face toward +x, centre at the origin)
and returned as separate meshes for the face, the barrel and the cap so each
can take its own material.
"""
import math

import numpy as np


def _normals(V, F):
    N = np.zeros_like(V)
    fn = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
    for k in range(3):
        np.add.at(N, F[:, k], fn)
    return N / np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-12)


def alloy_wheel(r_rim, width, spokes=5, face_inset=0.012, depth=0.024):
    """r_rim: radius of the rim's outer lip (m). width: rim width (m).
    Returns {'face': (V,N,F), 'barrel': (V,N,F), 'cap': (V,N,F)}."""
    xf = width / 2 - face_inset                     # outer face plane
    r_hub = 0.30 * r_rim
    nr, na = 16, 240
    rs = np.linspace(r_hub * 0.55, r_rim * 1.01, nr + 1)
    th = np.linspace(0, 2 * math.pi, na + 1)

    def dish(r):                                    # concave: centre set back
        return xf - 0.035 * np.clip(1 - (r - r_hub) / (r_rim - r_hub), 0, 1)

    pitch = 2 * math.pi / spokes

    def solid(r, t):
        if r < r_hub * 1.18 or r > r_rim * 0.90:
            return True                             # hub ring and outer lip
        hw = 0.20 - 0.09 * (r - r_hub) / (r_rim - r_hub)      # spoke half-width, radians, tapering out
        a = (t + pitch / 2) % pitch - pitch / 2
        return abs(a) < hw

    keep = np.zeros((nr, na), bool)
    for i in range(nr):
        for k in range(na):
            keep[i, k] = solid((rs[i] + rs[i + 1]) / 2, (th[k] + th[k + 1]) / 2)

    V, F = [], []
    idx = {}

    def vid(i, k, back):
        key = (i, k % na, back)
        if key not in idx:
            r, t = rs[i], th[k % na]
            x = dish(r) - (depth if back else 0.0)
            idx[key] = len(V)
            V.append([x, r * math.cos(t), r * math.sin(t)])
        return idx[key]

    for i in range(nr):
        for k in range(na):
            if not keep[i, k]:
                continue
            a, b, c, d = vid(i, k, 0), vid(i + 1, k, 0), vid(i + 1, k + 1, 0), vid(i, k + 1, 0)
            F += [[a, b, c], [a, c, d]]                         # front, facing +x
            a2, b2, c2, d2 = vid(i, k, 1), vid(i + 1, k, 1), vid(i + 1, k + 1, 1), vid(i, k + 1, 1)
            F += [[a2, c2, b2], [a2, d2, c2]]                   # back
            # walls where a window starts: give the spoke its thickness
            if i > 0 and not keep[i - 1, k]:
                F += [[a, d, d2], [a, d2, a2]]
            if i < nr - 1 and not keep[i + 1, k]:
                F += [[b, b2, c2], [b, c2, c]]
            if not keep[i, (k - 1) % na]:
                F += [[a, a2, b2], [a, b2, b]]
            if not keep[i, (k + 1) % na]:
                F += [[d, c, c2], [d, c2, d2]]
    V, F = np.array(V, float), np.array(F, np.uint32)
    face = (V, _normals(V, F), F)

    # barrel: the inside of the rim, seen through the windows
    bv, bf = [], []
    xs = (xf - 0.01, -width / 2)
    for k in range(na + 1):
        t = th[k]
        for x in xs:
            bv.append([x, r_rim * 0.99 * math.cos(t), r_rim * 0.99 * math.sin(t)])
    for k in range(na):
        a, b, c, d = 2 * k, 2 * k + 1, 2 * k + 3, 2 * k + 2
        bf += [[a, d, c], [a, c, b]]                            # facing the axis
    bv, bf = np.array(bv, float), np.array(bf, np.uint32)
    barrel = (bv, _normals(bv, bf), bf)

    # centre cap, plain, slightly proud
    cv, cf = [[xf + 0.004, 0.0, 0.0]], []
    rc = r_hub * 0.55
    for k in range(64):
        t = 2 * math.pi * k / 64
        cv.append([xf + 0.001, rc * math.cos(t), rc * math.sin(t)])
    for k in range(64):
        cf.append([0, 1 + k, 1 + (k + 1) % 64])
    cv, cf = np.array(cv, float), np.array(cf, np.uint32)
    cap = (cv, _normals(cv, cf), cf)
    return {"face": face, "barrel": barrel, "cap": cap}


def place(mesh, centre, side, scale=1.0):
    """Move a wheel-frame mesh to a corner. side +1 = the car's left (+x)."""
    V, N, F = mesh
    V2 = V * scale
    N2 = N.copy()
    if side < 0:                                    # mirror across the car: outer face to -x
        V2 = V2 * np.array([-1, 1, 1])
        N2 = N2 * np.array([-1, 1, 1])
        F = F[:, [0, 2, 1]]
    return V2 + centre, N2, F
