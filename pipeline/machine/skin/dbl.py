#!/usr/bin/env python3
"""dbl.py -- the doubled-face detector, and its two negative controls.

DEFINITION (v2, stated so it can be argued with).  Face i is DOUBLED at
perpendicular threshold t when some face j exists with

    n_i . n_j  < -0.7                       anti-parallel  (>134 deg apart)
    |(c_j - c_i) . n_i| < t                 j lies in i's plane
    |(c_j - c_i) . n_j| < t                 i lies in j's plane   (symmetric)
    dlat < OVL * (Lc_i + Lc_j) / 2          they overlap in projection

Rationale for each clause:
  * anti-parallel, because the second sheet of a doubled shell faces back at the
    first.  This says nothing about whether either normal is CORRECT -- only that
    they disagree -- so it survives the 46%-flipped-normal problem.
  * perpendicular separation, not centroid distance: two sheets at zero gap but
    with different tessellation have centroids ~Lc/2 apart LATERALLY, which a
    centroid-distance test reads as 4 mm of separation when the real gap is 0.
  * projection overlap, so that a face across a crease or a nearby but distinct
    component cannot pair up with one on the far side of a gap.

v1 of this file used nearest-centroid and is withdrawn: it under-reported by 5x
for exactly the tessellation reason above (3.9% at d<1mm vs the real answer).

CONTROLS (F5 in HYPOTHESIS.md): a synthetic single-sheet curved panel must score
~0%, a synthetic panel plus a reversed-winding copy at 0.2 mm must score ~100%.
Run `python3 dbl.py --controls` for those.
"""
import sys
import numpy as np
import trimesh
from scipy.spatial import cKDTree

ANTI = -0.7
OVL = 1.0
K = 32


def world_faces(path):
    sc = trimesh.load(path, process=False, force="scene")
    # graph-preserving loop.  A multi-primitive GLB gives its NODES names that
    # differ from its geometry names, so sc.graph.get(geom_name) raises
    # "No path from world->..."  -- and trimesh's dedup suffix carries a hash
    # that CHANGES BETWEEN LOADS, so node names must never be used as a join key
    # either.  CLAUDE.md's instance-collapse rule: iterate graph.nodes_geometry.
    nodes = list(sc.graph.nodes_geometry)
    names = [sc.graph[nd][1] for nd in nodes]
    Vl, Fl, Gl = [], [], []
    off = 0
    for gi, nd in enumerate(nodes):
        T, n = sc.graph[nd]
        m = sc.geometry[n]
        v = trimesh.transformations.transform_points(np.asarray(m.vertices, np.float64), T)
        f = np.asarray(m.faces, np.int64)
        Vl.append(v); Fl.append(f + off); Gl.append(np.full(len(f), gi, np.int32))
        off += len(v)
    return np.vstack(Vl), np.vstack(Fl), np.concatenate(Gl), names


def face_frame(V, F):
    tri = V[F]
    C = tri.mean(1)
    cr = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    a2 = np.linalg.norm(cr, axis=1)
    N = cr / np.maximum(a2[:, None], 1e-20)
    A = a2 * 0.5
    Lc = np.sqrt(np.maximum(A, 1e-20) * 2.0)
    return C, N, A, Lc


def doubled(C, N, Lc, tlist, k=K, chunk=40000, verbose=True):
    """Return dict t -> boolean mask, plus the partner index at the loosest t."""
    NF = len(C)
    tmax = max(tlist)
    tree = cKDTree(C)
    best_dp = np.full(NF, np.inf)
    best_j = np.full(NF, -1, np.int64)
    for s in range(0, NF, chunk):
        e = min(s + chunk, NF)
        dd, jj = tree.query(C[s:e], k=k, workers=-1)
        ii = np.arange(s, e)[:, None]
        ni = N[s:e][:, None, :]
        nj = N[jj]
        dot = (ni * nj).sum(2)
        dv = C[jj] - C[s:e][:, None, :]
        dpi = np.abs((dv * ni).sum(2))
        dpj = np.abs((dv * nj).sum(2))
        dlat = np.sqrt(np.maximum(dd ** 2 - dpi ** 2, 0.0))
        lim = OVL * 0.5 * (Lc[s:e][:, None] + Lc[jj])
        ok = (jj != ii) & (dot < ANTI) & (dlat < lim) & (dpj < tmax)
        cand = np.where(ok, dpi, np.inf)
        k0 = cand.argmin(1)
        r = np.arange(e - s)
        best_dp[s:e] = cand[r, k0]
        best_j[s:e] = np.where(np.isfinite(cand[r, k0]), jj[r, k0], -1)
        if verbose and s and s % 200000 == 0:
            print("  ", s, flush=True)
    return best_dp, best_j


def controls():
    print("=== CONTROL A: single-sheet curved panel (must score ~0%) ===")
    nu, nv = 120, 100
    u = np.linspace(0, 1.2, nu); v = np.linspace(0, 0.9, nv)
    U, Vv = np.meshgrid(u, v, indexing="ij")
    W = 0.10 * np.sin(2.4 * U) + 0.06 * np.cos(3.1 * Vv)
    P = np.stack([U, Vv, W], -1).reshape(-1, 3)
    idx = np.arange(nu * nv).reshape(nu, nv)
    f = []
    for i in range(nu - 1):
        for j in range(nv - 1):
            a, b, c, d = idx[i, j], idx[i + 1, j], idx[i + 1, j + 1], idx[i, j + 1]
            f.append([a, b, c]); f.append([a, c, d])
    F = np.array(f, np.int64)
    C, N, A, Lc = face_frame(P, F)
    dp, _ = doubled(C, N, Lc, [0.0005], verbose=False)
    for t in (0.0002, 0.0005, 0.001):
        print(f"   t={t*1000:.1f}mm  doubled {100*(dp<t).mean():6.3f}%   ({len(F)} faces)")

    print("=== CONTROL B: same panel + reversed-winding copy 0.2 mm off (must score ~100%) ===")
    P2 = P + np.array([0, 0, 0.0002])
    P3 = np.vstack([P, P2])
    F3 = np.vstack([F, (F[:, ::-1] + len(P))])
    C, N, A, Lc = face_frame(P3, F3)
    dp, _ = doubled(C, N, Lc, [0.0005], verbose=False)
    for t in (0.0002, 0.0005, 0.001):
        print(f"   t={t*1000:.1f}mm  doubled {100*(dp<t).mean():6.3f}%   ({len(F3)} faces)")

    print("=== CONTROL C: same panel + reversed copy 5 mm off (a REAL thin solid; must NOT score at 0.5mm) ===")
    P2 = P + np.array([0, 0, 0.005])
    P3 = np.vstack([P, P2])
    F3 = np.vstack([F, (F[:, ::-1] + len(P))])
    C, N, A, Lc = face_frame(P3, F3)
    dp, _ = doubled(C, N, Lc, [0.010], verbose=False)
    for t in (0.0005, 0.002, 0.006):
        print(f"   t={t*1000:.1f}mm  doubled {100*(dp<t).mean():6.3f}%   ({len(F3)} faces)")


if __name__ == "__main__":
    if "--controls" in sys.argv:
        controls(); sys.exit()
    path = sys.argv[1]
    V, F, G, names = world_faces(path)
    C, N, A, Lc = face_frame(V, F)
    print(f"{path}: {len(F)} faces, area {A.sum():.4f} m2")
    dp, bj = doubled(C, N, Lc, [0.010])
    np.savez_compressed(sys.argv[2] if len(sys.argv) > 2 else "dbl.npz",
                        dp=dp, bj=bj, A=A, G=G, Lc=Lc, C=C, N=N, names=np.array(names))
    print("\n  t(mm)   doubled%     area m2")
    for t in [0.0001, 0.00025, 0.0005, 0.001, 0.002, 0.003, 0.005, 0.010]:
        m = dp < t
        print(f"  {t*1000:6.2f}  {100*m.mean():8.3f}   {A[m].sum():9.4f}")
