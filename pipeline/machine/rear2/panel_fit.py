#!/usr/bin/env python3
"""panel_fit.py — fit a CLASS-A surface to a measured rear panel.

The rebuilt panel is a robust tensor-product POLYNOMIAL in the panel's own
(theta, y) parameter space, evaluated on a regular grid. That choice is the
whole point of the gate:

  * a low-order polynomial is C-infinity, so the panel is curvature-continuous
    by CONSTRUCTION -- it cannot carry the 2.4 mm rms waviness the melt has
  * it is fitted to the MEASURED outer skin, so the car keeps its own shape
    and this is a reconstruction, not an invention
  * it is fitted PER SIDE in one parameterisation whose pivot is the section's
    OWN centre, so the 100-160 mm rear shear is absorbed rather than fought
    (the g4_lamps2 "one design, seated per side" pattern)

Robustness: IRLS with a Tukey weight. The melt's outer-extreme samples include
spikes and torn shards; a plain least-squares fit would ride them.

Every number this module reports (residual rms/p95, curvature) is measured on
the SAMPLES, not asserted.
"""
import numpy as np


def tensor_design(u, v, du, dv):
    cols = [(u ** i) * (v ** j) for i in range(du + 1) for j in range(dv + 1)]
    return np.stack(cols, 1)


def robust_fit(u, v, r, du, dv, iters=6, c=2.5):
    A = tensor_design(u, v, du, dv)
    w = np.ones(len(r))
    coef = None
    for _ in range(iters):
        W = np.sqrt(w)[:, None]
        coef, *_ = np.linalg.lstsq(A * W, r * np.sqrt(w), rcond=None)
        res = r - A @ coef
        s = 1.4826 * np.median(np.abs(res - np.median(res))) + 1e-9
        t = np.clip(res / (c * s), -1, 1)
        w = (1 - t ** 2) ** 2
    res = r - A @ coef
    return coef, res, w


def evaluate(coef, u, v, du, dv):
    return tensor_design(u, v, du, dv) @ coef


def fit_report(res, w, tag):
    inl = w > 0.05
    return {"tag": tag, "n": int(len(res)), "n_inlier": int(inl.sum()),
            "res_rms_mm": round(float(np.sqrt(np.mean(res[inl] ** 2)) * 1000), 3),
            "res_p95_mm": round(float(np.percentile(np.abs(res[inl]), 95) * 1000), 3),
            "res_max_mm": round(float(np.abs(res[inl]).max() * 1000), 3),
            "outlier_pct": round(float((~inl).mean() * 100), 2)}


def grid_waviness(pts, k=24, nsample=3000, seed=0):
    """Waviness of a BUILT surface, the SAME estimator rear_survey used on the
    melt it replaces -- local quadratic fit over a k-point neighbourhood,
    residual rms in mm. Batched (one SVD call, one normal-equation solve) so a
    degree sweep is affordable; the per-point loop cost 2 min a sweep.
    """
    from scipy.spatial import cKDTree
    pts = np.asarray(pts, float)
    tree = cKDTree(pts)
    rng = np.random.default_rng(seed)
    sel = rng.choice(len(pts), min(nsample, len(pts)), replace=False)
    k = min(k, len(pts))
    _, nb = tree.query(pts[sel], k=k)
    P = pts[nb]                                  # (N,k,3)
    Q = P - P.mean(1, keepdims=True)
    _, _, vt = np.linalg.svd(Q, full_matrices=False)   # batched
    e1, e2, nrm = vt[:, 0, :], vt[:, 1, :], vt[:, 2, :]
    a = np.einsum('nkj,nj->nk', Q, e1)
    b = np.einsum('nkj,nj->nk', Q, e2)
    h = np.einsum('nkj,nj->nk', Q, nrm)
    A = np.stack([a * a, a * b, b * b, a, b, np.ones_like(a)], -1)   # (N,k,6)
    AtA = np.einsum('nki,nkj->nij', A, A) + 1e-12 * np.eye(6)
    Atb = np.einsum('nki,nk->ni', A, h)
    coef = np.linalg.solve(AtA, Atb[..., None])[..., 0]
    res = np.einsum('nki,ni->nk', A, coef) - h
    r = np.sqrt((res ** 2).mean(1))
    return {"n": int(len(r)), "wav_rms_mm": round(float(r.mean() * 1000), 4),
            "wav_p95_mm": round(float(np.percentile(r, 95) * 1000), 4),
            "wav_p99_mm": round(float(np.percentile(r, 99) * 1000), 4)}
