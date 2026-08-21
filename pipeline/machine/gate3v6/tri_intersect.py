#!/usr/bin/env python3
"""tri_intersect.py -- vectorised triangle/triangle intersection (Moller 1997).

Used by verify_front_gate.py for the self-intersection and inter-object
intersection checks. Written here rather than pulled from a library because
every checker in this gate has to be able to demonstrate a FAILURE on a
constructed negative control, and a black box cannot be calibrated.

METHOD (Moller, "A Fast Triangle-Triangle Intersection Test", 1997):
  1. reject if all three verts of A lie strictly on one side of B's plane
  2. reject if all three verts of B lie strictly on one side of A's plane
  3. otherwise both triangles cross the line L = plane(A) x plane(B); compute
     each triangle's interval on L and test for overlap.

COPLANAR TRIANGLES ARE NOT HANDLED and are reported separately as `coplanar`
rather than silently counted as a miss -- an honest gap, not a hidden one.

EPS is in metres and is a *penetration* threshold: two surfaces that merely
touch within EPS are not an intersection. Default 1e-6 m = 1 micron.
"""
import numpy as np


def _signed_dist(pts, n, d):
    return pts @ n + d


def tri_tri_pairs(VA, FA, VB, FB, pairs, eps=1e-6):
    """Test candidate (ia, ib) face-index pairs. Returns (hit_mask, coplanar_mask).

    VA/FA, VB/FB are vertex arrays and face index arrays. `pairs` is (M,2).
    Fully vectorised; no python loop over pairs.
    """
    if len(pairs) == 0:
        return np.zeros(0, bool), np.zeros(0, bool)
    ia, ib = pairs[:, 0], pairs[:, 1]
    A = VA[FA[ia]]                      # (M,3,3)
    B = VB[FB[ib]]

    def plane(T):
        n = np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0])
        ln = np.linalg.norm(n, axis=1)
        with np.errstate(invalid="ignore", divide="ignore"):
            n = n / ln[:, None]
        return n, -np.einsum("ij,ij->i", n, T[:, 0]), ln

    nB, dB, lnB = plane(B)
    dA_pts = np.einsum("mij,mj->mi", A, nB) + dB[:, None]      # (M,3)
    nA, dA, lnA = plane(A)
    dB_pts = np.einsum("mij,mj->mi", B, nA) + dA[:, None]

    degenerate = (lnA <= 1e-18) | (lnB <= 1e-18)
    sA = np.where(np.abs(dA_pts) < eps, 0.0, np.sign(dA_pts))
    sB = np.where(np.abs(dB_pts) < eps, 0.0, np.sign(dB_pts))
    # all strictly one side -> reject
    rejA = (np.abs(sA.sum(1)) == 3)
    rejB = (np.abs(sB.sum(1)) == 3)
    coplanar = (np.abs(dA_pts) < eps).all(1) | (np.abs(dB_pts) < eps).all(1)
    live = ~(rejA | rejB | degenerate | coplanar)

    hit = np.zeros(len(pairs), bool)
    if not live.any():
        return hit, coplanar & ~degenerate

    Al, Bl = A[live], B[live]
    nAl, nBl = nA[live], nB[live]
    dAl, dBl = dA_pts[live], dB_pts[live]

    D = np.cross(nAl, nBl)
    ax = np.argmax(np.abs(D), axis=1)
    pA = np.take_along_axis(Al, ax[:, None, None].repeat(3, 1), axis=2)[:, :, 0]
    pB = np.take_along_axis(Bl, ax[:, None, None].repeat(3, 1), axis=2)[:, :, 0]

    def interval(p, dist):
        """The two points of a triangle on the far side of the plane pair up
        with the lone point; compute the two parameter values on L."""
        s = np.sign(np.where(np.abs(dist) < 1e-15, 0.0, dist))
        # pick the vertex whose sign differs from the other two (the 'lone' one)
        lone = np.zeros(len(p), int)
        for k in range(3):
            o1, o2 = (k + 1) % 3, (k + 2) % 3
            same = (s[:, o1] == s[:, o2]) & (s[:, o1] != 0)
            lone = np.where(same, k, lone)
        idx = np.arange(len(p))
        k = lone
        o1, o2 = (k + 1) % 3, (k + 2) % 3
        pk, dk = p[idx, k], dist[idx, k]
        t = []
        for o in (o1, o2):
            po, do = p[idx, o], dist[idx, o]
            den = dk - do
            den = np.where(np.abs(den) < 1e-18, 1e-18, den)
            t.append(pk + (po - pk) * dk / den)
        lo = np.minimum(t[0], t[1])
        hi = np.maximum(t[0], t[1])
        return lo, hi

    aL, aH = interval(pA, dAl)
    bL, bH = interval(pB, dBl)
    ov = (aL <= bH + eps) & (bL <= aH + eps)
    # require real overlap length, not a tangential touch
    olen = np.minimum(aH, bH) - np.maximum(aL, bL)
    ov &= olen > eps
    hit[np.where(live)[0]] = ov
    return hit, coplanar & ~degenerate


def broadphase(VA, FA, VB, FB, share_verts=False, max_pairs=40_000_000):
    """TRUE AABB-overlap candidate pairs, via a bulk-loaded 3-D R-tree.

    The first version of this used bounding SPHERES from a KD-tree, with the
    query radius padded by the largest triangle in the other mesh. On a real
    component pair that produced 16.8 million candidates and blew the cap --
    a sphere padded by the global maximum radius is enormously looser than the
    per-triangle box it is standing in for. Boxes are both tighter and cheaper,
    so this is a correctness fix as well as a memory one.

    Returns an (M,2) int array of candidate (faceA, faceB) pairs.
    """
    import rtree
    if len(FA) == 0 or len(FB) == 0:
        return np.zeros((0, 2), int)
    swap = len(FA) > len(FB)
    if swap:
        VA, FA, VB, FB = VB, FB, VA, FA
    TA, TB = VA[FA], VB[FB]
    loA, hiA = TA.min(1), TA.max(1)
    loB, hiB = TB.min(1), TB.max(1)
    prop = rtree.index.Property()
    prop.dimension = 3
    idx = rtree.index.Index(
        ((i, (loB[i, 0], loB[i, 1], loB[i, 2], hiB[i, 0], hiB[i, 1], hiB[i, 2]), None)
         for i in range(len(FB))), properties=prop)   # interleaved=True order:
        # (xmin, ymin, zmin, xmax, ymax, zmax). Passing interleaved=False with
        # THIS order raises "minimums more than maximums" -- it did, first run.
    out_a, out_b, total = [], [], 0
    for i in range(len(FA)):
        hits = idx.intersection((loA[i, 0], loA[i, 1], loA[i, 2],
                                 hiA[i, 0], hiA[i, 1], hiA[i, 2]))
        h = np.fromiter(hits, np.int64)
        if h.size:
            out_a.append(np.full(h.size, i, np.int64))
            out_b.append(h)
            total += h.size
            if total > max_pairs:
                raise MemoryError(f"broadphase exceeded {max_pairs} candidate pairs")
    if not out_a:
        return np.zeros((0, 2), int)
    P = np.stack([np.concatenate(out_a), np.concatenate(out_b)], 1)
    if swap:
        P = P[:, ::-1].copy()
        FA, FB = FB, FA
    if share_verts:
        fa, fb = FA[P[:, 0]], FB[P[:, 1]]
        shares = (fa[:, :, None] == fb[:, None, :]).any(axis=(1, 2))
        P = P[~shares]
    return P


def intersect_count(VA, FA, VB, FB, share_verts=False, eps=1e-6,
                    max_pairs=40_000_000, chunk=1_000_000):
    """Candidate pairs + exact tri-tri hits, evaluated in bounded chunks so a
    deeply overlapping pair cannot exhaust memory."""
    try:
        P = broadphase(VA, FA, VB, FB, share_verts=share_verts, max_pairs=max_pairs)
    except MemoryError as e:
        return {"candidate_pairs": -1, "intersecting_pairs": -1,
                "coplanar_pairs": -1, "error": str(e)}
    if share_verts:
        P = P[P[:, 0] < P[:, 1]]
    hits = cop = 0
    for s in range(0, len(P), chunk):
        h, c = tri_tri_pairs(VA, FA, VB, FB, P[s:s + chunk], eps=eps)
        hits += int(h.sum())
        cop += int(c.sum())
    return {"candidate_pairs": int(len(P)), "intersecting_pairs": hits,
            "coplanar_pairs": cop}
