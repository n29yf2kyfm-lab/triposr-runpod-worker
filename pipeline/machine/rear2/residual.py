#!/usr/bin/env python3
"""residual.py — pull a fitted panel back onto the measured skin, smoothly.

WHY THIS EXISTS (measured, not anticipated). A single low-order polynomial
cannot follow a CLIFF, and this car has one: at the tailgate's +z upper corner
the measured surface drops from x = 1.783 at y = 1.21 to x = 1.324 at y = 1.33
-- the D-pillar sweeping forward. Both parameterisations I tried rang badly
there (up to 210 mm off the measured skin at the corner) while fitting the rest
of the panel to 5 mm. Raising the degree chases the cliff and buys waviness
everywhere else; that trade was measured in the degree sweep.

THE FIX is standard surfacing practice: keep the smooth global fit, then add a
HEAVILY LOW-PASSED residual field measured against the real skin. The
correction is band-limited by construction, so it cannot reintroduce the melt's
2.4 mm waviness, and the panel tracks the car everywhere instead of only in the
middle. Both properties are then MEASURED on the built grid, not assumed.

Normalized convolution is used so cells with no measurement (the melt has
holes) neither pull the field toward zero nor leave a step.
"""
import numpy as np


def gauss_kernel(sigma, trunc=3.0):
    r = max(1, int(trunc * sigma))
    x = np.arange(-r, r + 1)
    k = np.exp(-0.5 * (x / sigma) ** 2)
    return k / k.sum()


def sepconv(A, k):
    pad = len(k) // 2
    B = np.pad(A, ((pad, pad), (0, 0)), mode="edge")
    B = np.apply_along_axis(lambda m: np.convolve(m, k, "valid"), 0, B)
    C = np.pad(B, ((0, 0), (pad, pad)), mode="edge")
    return np.apply_along_axis(lambda m: np.convolve(m, k, "valid"), 1, C)


def smooth_residual(res, valid, sigma_cells):
    """normalized convolution: smooth(res*valid)/smooth(valid)."""
    k = gauss_kernel(sigma_cells)
    w = valid.astype(float)
    num = sepconv(np.where(valid, res, 0.0), k)
    den = sepconv(w, k)
    out = num / np.maximum(den, 1e-6)
    out[den < 1e-3] = 0.0
    return out


class SkinMap:
    """measured OUTER skin as a regular map, with the spike guard."""

    def __init__(self, P, ycoords, qcoords, mode, pivot=None, xmin=1.20):
        self.y = ycoords; self.q = qcoords; self.mode = mode
        dy = ycoords[1] - ycoords[0]; dq = qcoords[1] - qcoords[0]
        M = np.full((len(ycoords), len(qcoords)), np.nan)
        for i, y in enumerate(ycoords):
            m = (np.abs(P[:, 1] - y) < dy) & (P[:, 0] > xmin)
            if m.sum() < 5: continue
            pp = P[m]
            if mode == "radial":
                xc, zc = pivot(y)
                q = np.degrees(np.arctan2(pp[:, 2] - zc, pp[:, 0] - xc))
                val = np.hypot(pp[:, 0] - xc, pp[:, 2] - zc)
            else:
                q = pp[:, 2]; val = pp[:, 0]
            idx = np.digitize(q, qcoords - dq / 2) - 1
            for k in range(len(qcoords)):
                v = np.sort(val[idx == k])[::-1]
                if len(v) < 3: continue
                v0 = v[0]
                if len(v) >= 5 and (v0 - v[1:5].max()) > 0.012: v0 = v[1]
                M[i, k] = v0
        self.M = M

        self.valid = np.isfinite(M)
        # fill holes once, so sampling is plain bilinear and never NaN-poisoned
        F = M.copy()
        for _ in range(60):
            bad = ~np.isfinite(F)
            if not bad.any(): break
            acc = np.zeros_like(F); cnt = np.zeros_like(F)
            for sh, ax in ((1, 0), (-1, 0), (1, 1), (-1, 1)):
                R = np.roll(F, sh, axis=ax)
                ok = np.isfinite(R)
                acc[ok] += R[ok]; cnt[ok] += 1
            F = np.where(bad & (cnt > 0), acc / np.maximum(cnt, 1), F)
        self.F = np.where(np.isfinite(F), F, np.nanmean(M))

    def sample(self, y, q):
        yy = np.clip(y, self.y[0], self.y[-1]); qq = np.clip(q, self.q[0], self.q[-1])
        dy = self.y[1] - self.y[0]; dq = self.q[1] - self.q[0]
        fy = (yy - self.y[0]) / dy; fq = (qq - self.q[0]) / dq
        i0 = np.clip(fy.astype(int), 0, len(self.y) - 2); j0 = np.clip(fq.astype(int), 0, len(self.q) - 2)
        ty = fy - i0; tq = fq - j0
        F = self.F
        v = ((1 - ty) * (1 - tq) * F[i0, j0] + (1 - ty) * tq * F[i0, j0 + 1] +
             ty * (1 - tq) * F[i0 + 1, j0] + ty * tq * F[i0 + 1, j0 + 1])
        ok = (self.valid[i0, j0] | self.valid[i0, j0 + 1] |
              self.valid[i0 + 1, j0] | self.valid[i0 + 1, j0 + 1])
        return v, ok
