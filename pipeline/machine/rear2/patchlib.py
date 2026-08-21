#!/usr/bin/env python3
"""patchlib.py — evaluate a fitted rear patch and build grids from it."""
import numpy as np


class Patch:
    def __init__(self, path):
        d = np.load(path)
        self.coef = d["coef"]; self.du = int(d["du"]); self.dv = int(d["dv"])
        self.ylo = float(d["ylo"]); self.yhi = float(d["yhi"]); self.mode = str(d["mode"])
        self.ys = d["ys"]
        self.c_lo, self.c_hi = d["c_lo"], d["c_hi"]
        self.c_cx, self.c_cz = d["c_cx"], d["c_cz"]
        self.zdom = d["zdom"] if "zdom" in d else np.array([-1.0, 1.0])

    def _t(self, y):
        return (y - self.ys.mean()) / (0.5 * (self.ys.max() - self.ys.min()) + 1e-9)

    def _cv(self, c, y):
        t = self._t(y)
        return sum(c[i] * t ** i for i in range(len(c)))

    def frame(self, y):
        """lo, hi (theta deg or z), pivot xc, zc at height y."""
        return (self._cv(self.c_lo, y), self._cv(self.c_hi, y),
                self._cv(self.c_cx, y), self._cv(self.c_cz, y))

    def v_of_y(self, y):
        return (y - self.ylo) / (self.yhi - self.ylo) * 2 - 1

    def y_of_v(self, v):
        return self.ylo + (v + 1) / 2 * (self.yhi - self.ylo)

    def surf(self, u, v):
        u = np.atleast_1d(u); v = np.atleast_1d(v)
        cols = [(u ** i) * (v ** j) for i in range(self.du + 1) for j in range(self.dv + 1)]
        return np.stack(cols, 1) @ self.coef

    def point(self, u, v):
        """(u,v) in [-1,1]^2 -> world xyz."""
        u = np.atleast_1d(np.asarray(u, float)); v = np.atleast_1d(np.asarray(v, float))
        y = self.y_of_v(v)
        lo, hi, xc, zc = self.frame(y)
        q = 0.5 * (lo + hi) + u * 0.5 * (hi - lo)
        if self.mode == "cartphys":
            z0, z1 = self.zdom
            r = self.surf((q - 0.5 * (z0 + z1)) / (0.5 * (z1 - z0)), v)
        else:
            r = self.surf(u, v)
        if self.mode == "radial":
            a = np.radians(q)
            return np.stack([xc + r * np.cos(a), y, zc + r * np.sin(a)], 1)
        return np.stack([r, y, q], 1)

    def local_value(self, p):
        """inverse: for a world point, its (u, v) and the surface value there.

        Used by the STRIP so the cut footprint and the rebuilt panel are the
        same surface by construction and cannot drift apart.
        """
        y = p[:, 1]
        v = self.v_of_y(y)
        lo, hi, xc, zc = self.frame(y)
        if self.mode == "radial":
            q = np.degrees(np.arctan2(p[:, 2] - zc, p[:, 0] - xc))
            val = np.hypot(p[:, 0] - xc, p[:, 2] - zc)
        else:
            q = p[:, 2]; val = p[:, 0]
        u = (q - 0.5 * (lo + hi)) / (0.5 * (hi - lo) + 1e-12)
        return u, v, val

    def surface_at(self, p):
        """the fitted surface VALUE at the (u,v) of a world point."""
        u, v, val = self.local_value(p)
        if self.mode == "cartphys":
            z0, z1 = self.zdom
            return u, v, val, self.surf((p[:, 2] - 0.5 * (z0 + z1)) / (0.5 * (z1 - z0)),
                                        np.clip(v, -1, 1))
        return u, v, val, self.surf(np.clip(u, -1, 1), np.clip(v, -1, 1))


def arclen_u(patch, v, nu, margin_m):
    """u nodes for one row, UNIFORM IN ARC LENGTH, inset by margin_m each end.

    Uniform-in-parameter nodes bunch badly where a section turns a corner --
    which on the wrapping bumper made the built grid's own neighbourhoods
    anisotropic. Arc length gives even quads and a well-conditioned surface.
    """
    us = np.linspace(-1, 1, 601)
    P = patch.point(us, np.full(601, v))
    d = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))]
    S = d[-1]
    if S <= 2 * margin_m + 1e-6:
        return np.linspace(-1, 1, nu)
    tgt = np.linspace(margin_m, S - margin_m, nu)
    return np.interp(tgt, d, us)


def grid_normals(V):
    """outward vertex normals of an (nv, nu, 3) grid, from parametric tangents."""
    nv, nu, _ = V.shape
    du = np.gradient(V, axis=1); dv = np.gradient(V, axis=0)
    N = np.cross(du, dv)
    n = np.linalg.norm(N, axis=2, keepdims=True)
    N = N / np.maximum(n, 1e-12)
    return N


def orient_outward(V, N, pivot):
    """flip the whole normal field if it points inward (never per-face --
    CLAUDE.md: 46% of body normals in this zone are flipped, so a per-face
    rule learns the melt's mistakes)."""
    c = V.reshape(-1, 3).mean(0)
    out = c - np.array([pivot[0], c[1], pivot[1]])
    out /= (np.linalg.norm(out) + 1e-12)
    if float(np.dot(N.reshape(-1, 3).mean(0), out)) < 0:
        return -N
    return N


def quads(nv, nu, mask=None, flip=False, base=0):
    """triangulate a grid; mask[i,j] True keeps the quad (i,j)-(i+1,j+1)."""
    f = []
    for i in range(nv - 1):
        for j in range(nu - 1):
            if mask is not None and not mask[i, j]: continue
            a = base + i * nu + j; b = a + 1; c = a + nu; d = c + 1
            if flip: f += [[a, b, c], [b, d, c]]
            else:    f += [[a, c, b], [b, c, d]]
    return np.array(f, np.int64).reshape(-1, 3)
