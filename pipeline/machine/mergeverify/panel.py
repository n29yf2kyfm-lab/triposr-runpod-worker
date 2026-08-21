"""
panel.py -- surface-quality measures that need no reference surface.

WAVINESS is defined here as the rms residual of each vertex from a QUADRIC fitted
to its own neighbourhood within a fixed PHYSICAL radius. Fitting a quadric (not a
plane) removes the panel's real curvature, so what is left is genuine ripple.
The radius is physical, not a neighbour COUNT, so a dense melt patch and a coarse
constructed grid are measured over the same area of car -- a k-NN definition would
measure a 3 mm patch on melt against a 60 mm patch on a built grid and report the
built panel as smoother for a reason that has nothing to do with the panel.

This is MY definition and it is stated so that a number that disagrees with another
agent's "waviness" can be attributed to the definition rather than to the car.
"""
import numpy as np
from scipy.spatial import cKDTree


def waviness(V, radius_m=0.030, min_nb=12, max_nb=200, sample=None, seed=0):
    """-> dict with rms/p95/max residual in mm, and the sample size actually used."""
    V = np.asarray(V, float)
    tree = cKDTree(V)
    idx = np.arange(len(V))
    if sample and len(V) > sample:
        idx = np.random.default_rng(seed).choice(len(V), sample, replace=False)
    res = []
    nbs = tree.query_ball_point(V[idx], r=radius_m)
    for i, nb in zip(idx, nbs):
        if len(nb) < min_nb:
            continue
        nb = np.asarray(nb)
        if len(nb) > max_nb:
            nb = nb[:max_nb]
        P = V[nb] - V[nb].mean(0)
        # local frame from PCA; smallest-variance axis is the surface normal
        _, _, Vt = np.linalg.svd(P, full_matrices=False)
        L = P @ Vt.T                      # columns: t1, t2, n
        x, y, z = L[:, 0], L[:, 1], L[:, 2]
        A = np.column_stack([x * x, x * y, y * y, x, y, np.ones_like(x)])
        try:
            coef, *_ = np.linalg.lstsq(A, z, rcond=None)
        except np.linalg.LinAlgError:
            continue
        r = z - A @ coef
        j = np.nonzero(nb == i)[0]
        if len(j):
            res.append(abs(r[j[0]]))
    if not res:
        return dict(n=0)
    r = np.array(res) * 1000.0
    return dict(n=int(len(r)), rms_mm=float(np.sqrt((r ** 2).mean())),
                p95_mm=float(np.percentile(r, 95)), max_mm=float(r.max()),
                median_mm=float(np.median(r)))


def dihedral_roughness(V, F, sample=200_000, seed=0):
    """Fit-free companion metric: rms angle (deg) between the normals of faces that
    share an edge. A constructed grid panel is near 0; melt is not."""
    a = V[F[:, 1]] - V[F[:, 0]]
    b = V[F[:, 2]] - V[F[:, 0]]
    n = np.cross(a, b)
    ln = np.linalg.norm(n, axis=1)
    good = ln > 1e-14
    n = np.where(good[:, None], n / np.maximum(ln, 1e-30)[:, None], 0)
    E = np.vstack([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    fid = np.tile(np.arange(len(F)), 3)
    E = np.sort(E, axis=1)
    key = E[:, 0].astype(np.int64) * (V.shape[0] + 1) + E[:, 1]
    o = np.argsort(key, kind='stable')
    key, fid = key[o], fid[o]
    same = np.nonzero(key[1:] == key[:-1])[0]
    if not len(same):
        return dict(n=0)
    f1, f2 = fid[same], fid[same + 1]
    m = good[f1] & good[f2]
    f1, f2 = f1[m], f2[m]
    if sample and len(f1) > sample:
        k = np.random.default_rng(seed).choice(len(f1), sample, replace=False)
        f1, f2 = f1[k], f2[k]
    c = np.clip(np.einsum('ij,ij->i', n[f1], n[f2]), -1, 1)
    ang = np.degrees(np.arccos(c))
    return dict(n=int(len(ang)), rms_deg=float(np.sqrt((ang ** 2).mean())),
                p95_deg=float(np.percentile(ang, 95)), median_deg=float(np.median(ang)))
