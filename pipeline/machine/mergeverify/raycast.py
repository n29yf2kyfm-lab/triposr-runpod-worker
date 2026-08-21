"""
raycast.py -- vectorised Moller-Trumbore that returns ALL hits along each ray,
tagged with the owning NODE index.

Written rather than reused deliberately. My brief warns that a hole test built on
`intersects_any` can never see a hole because the cabin sits behind every panel,
and that a clearance probe read back its own exclusion boundary on 8 of 8 wheels.
Returning the full ordered hit list per ray is what makes both "did a surface
disappear" and "how many surfaces are stacked here" answerable from the same data.

No BVH: the triangle set is pre-filtered to a slab around the rays, which for a
rear-fascia or roof zone is 10-60k triangles, and the ray count is a few thousand.
"""
import numpy as np

EPS = 1e-12


def gather(g, node_filter=None):
    """-> (V, F, owner) world-space, owner = index into `names`, plus names list."""
    import measure as M
    Vs, Fs, own, names = [], [], [], []
    off = 0
    for n in g.nodes():
        if n.mesh is None:
            continue
        if node_filter and not node_filter(n.name):
            continue
        V, F = M.node_world_tris(g, n.name)
        if V is None:
            continue
        names.append(n.name)
        Vs.append(V)
        Fs.append(F + off)
        own.append(np.full(len(F), len(names) - 1, dtype=np.int32))
        off += len(V)
    if not Vs:
        return None, None, None, []
    return np.vstack(Vs), np.vstack(Fs), np.concatenate(own), names


def all_hits(V, F, owner, origins, direction, tri_chunk=200_000):
    """origins (R,3), single unit `direction`. Returns list of (t_sorted, owner_sorted)
    per ray. Triangles are pre-culled to the rays' lateral bounding box."""
    d = np.asarray(direction, dtype=np.float64)
    d = d / np.linalg.norm(d)
    # build an orthonormal frame; cull triangles outside the ray bundle's cross-section
    a = np.array([1.0, 0, 0]) if abs(d[0]) < 0.9 else np.array([0, 1.0, 0])
    u = np.cross(d, a); u /= np.linalg.norm(u)
    v = np.cross(d, u)
    O = np.asarray(origins, dtype=np.float64)
    ou, ov = O @ u, O @ v
    pad = 0.02
    lo_u, hi_u, lo_v, hi_v = ou.min() - pad, ou.max() + pad, ov.min() - pad, ov.max() + pad
    tv = V[F]                                   # (T,3,3)
    tu_ = tv @ u
    tv_ = tv @ v
    keep = ~((tu_.max(1) < lo_u) | (tu_.min(1) > hi_u) |
             (tv_.max(1) < lo_v) | (tv_.min(1) > hi_v))
    Fk, ownk = F[keep], owner[keep]
    p0, p1, p2 = V[Fk[:, 0]], V[Fk[:, 1]], V[Fk[:, 2]]
    e1, e2 = p1 - p0, p2 - p0
    pvec = np.cross(d, e2)
    det = np.einsum('ij,ij->i', e1, pvec)
    ok = np.abs(det) > EPS
    p0, e1, e2, pvec, det, ownk = p0[ok], e1[ok], e2[ok], pvec[ok], det[ok], ownk[ok]
    inv = 1.0 / det
    out = []
    T = len(p0)
    for r in range(len(O)):
        o = O[r]
        ts, ow = [], []
        for s in range(0, T, tri_chunk):
            e = min(s + tri_chunk, T)
            tvec = o - p0[s:e]
            uu = np.einsum('ij,ij->i', tvec, pvec[s:e]) * inv[s:e]
            m = (uu >= -1e-9) & (uu <= 1 + 1e-9)
            if not m.any():
                continue
            idx = np.nonzero(m)[0]
            qvec = np.cross(tvec[idx], e1[s:e][idx])
            vv = (qvec @ d) * inv[s:e][idx]
            m2 = (vv >= -1e-9) & (uu[idx] + vv <= 1 + 1e-9)
            if not m2.any():
                continue
            idx2 = idx[m2]
            t = np.einsum('ij,ij->i', e2[s:e][idx2], qvec[m2]) * inv[s:e][idx2]
            m3 = t > 1e-7
            if m3.any():
                ts.append(t[m3])
                ow.append(ownk[s:e][idx2][m3])
        if ts:
            t = np.concatenate(ts); o_ = np.concatenate(ow)
            k = np.argsort(t)
            out.append((t[k], o_[k]))
        else:
            out.append((np.zeros(0), np.zeros(0, dtype=np.int32)))
    return out


def first_hit_depth(V, F, owner, origins, direction, **kw):
    hits = all_hits(V, F, owner, origins, direction, **kw)
    t = np.array([h[0][0] if len(h[0]) else np.inf for h in hits])
    o = np.array([h[1][0] if len(h[0]) else -1 for h in hits])
    return t, o, hits


def grid_origins(centre, u, v, half_u, half_v, n_u, n_v, direction, back):
    """(R,3) plane of ray origins sitting `back` metres UPSTREAM of `centre`
    along `direction`, spanning +-half_u along u and +-half_v along v."""
    d = np.asarray(direction, float); d = d / np.linalg.norm(d)
    a = np.linspace(-half_u, half_u, n_u)
    b = np.linspace(-half_v, half_v, n_v)
    A, B = np.meshgrid(a, b, indexing='ij')
    P = (np.asarray(centre, float)[None, :]
         + A.reshape(-1, 1) * np.asarray(u, float)[None, :]
         + B.reshape(-1, 1) * np.asarray(v, float)[None, :]
         - back * d[None, :])
    return P, A.shape


def selftest():
    """PROVE THE INSTRUMENT. A closed icosphere must return exactly 2 hits on every
    ray that crosses it and 0 on every ray that misses; deleting a cap must drop
    the far-side count on exactly the rays through the hole."""
    import trimesh
    s = trimesh.creation.icosphere(subdivisions=3, radius=1.0)
    V = np.asarray(s.vertices, float); F = np.asarray(s.faces, np.int64)
    own = np.zeros(len(F), np.int32)
    o, _ = grid_origins(np.zeros(3), [0, 1, 0], [0, 0, 1], 0.7, 0.7, 12, 12, [1, 0, 0], 3.0)
    h = all_hits(V, F, own, o, [1, 0, 0])
    n = np.array([len(x[0]) for x in h])
    r = dict(closed_rays=len(o), closed_two_hit=int((n == 2).sum()),
             closed_other=sorted(set(n.tolist())))
    # now punch a hole in the +x cap
    keep = ~(s.triangles_center[:, 0] > 0.80)
    F2 = F[keep]
    h2 = all_hits(V, F2, np.zeros(len(F2), np.int32), o, [1, 0, 0])
    n2 = np.array([len(x[0]) for x in h2])
    r.update(holed_two_hit=int((n2 == 2).sum()), holed_one_hit=int((n2 == 1).sum()),
             rays_that_lost_a_surface=int((n2 < n).sum()))
    return r


# ---------------------------------------------------------------- binned caster
class Binned:
    """Uniform-grid acceleration in the plane normal to `direction`.

    Built because the brute caster is O(rays x triangles) and the 15-direction hole
    test on a 1M-triangle car needs ~10^9 tests per direction. Each triangle is
    written into every grid cell its (u,v) bbox touches, so a ray tests only the
    triangles that could possibly cover it -- exact, not approximate.
    """

    def __init__(self, V, F, owner, direction, ncell=192):
        d = np.asarray(direction, float); self.d = d / np.linalg.norm(d)
        a = np.array([1.0, 0, 0]) if abs(self.d[0]) < 0.9 else np.array([0, 1.0, 0])
        self.u = np.cross(self.d, a); self.u /= np.linalg.norm(self.u)
        self.v = np.cross(self.d, self.u)
        tv = V[F]
        tu = tv @ self.u; tvv = tv @ self.v
        self.lo = np.array([tu.min(), tvv.min()]); hi = np.array([tu.max(), tvv.max()])
        self.cell = np.maximum((hi - self.lo) / ncell, 1e-9)
        self.n = ncell
        iu0 = np.clip(((tu.min(1) - self.lo[0]) / self.cell[0]).astype(int), 0, ncell - 1)
        iu1 = np.clip(((tu.max(1) - self.lo[0]) / self.cell[0]).astype(int), 0, ncell - 1)
        iv0 = np.clip(((tvv.min(1) - self.lo[1]) / self.cell[1]).astype(int), 0, ncell - 1)
        iv1 = np.clip(((tvv.max(1) - self.lo[1]) / self.cell[1]).astype(int), 0, ncell - 1)
        # Vectorised cell expansion. Most triangles land in ONE cell on a 1M-face
        # car, so that case is handled without a Python loop; only the few that
        # straddle cells go round the slow path.
        cnt = (iu1 - iu0 + 1) * (iv1 - iv0 + 1)
        one = cnt == 1
        tri_l = [np.nonzero(one)[0]]
        cu_l = [iu0[one]]
        cv_l = [iv0[one]]
        multi = np.nonzero(~one)[0]
        for t in multi:
            g0, g1 = np.meshgrid(np.arange(iu0[t], iu1[t] + 1),
                                 np.arange(iv0[t], iv1[t] + 1), indexing='ij')
            g0 = g0.ravel(); g1 = g1.ravel()
            tri_l.append(np.full(len(g0), t)); cu_l.append(g0); cv_l.append(g1)
        tri = np.concatenate(tri_l)
        cu = np.concatenate(cu_l); cv = np.concatenate(cv_l)
        key = cu.astype(np.int64) * ncell + cv
        o = np.argsort(key, kind='stable')
        self.tri = tri[o]
        k = key[o]
        self.start = np.searchsorted(k, np.arange(ncell * ncell), 'left')
        self.end = np.searchsorted(k, np.arange(ncell * ncell), 'right')
        # precomputed MT terms
        p0 = V[F[:, 0]]; e1 = V[F[:, 1]] - p0; e2 = V[F[:, 2]] - p0
        self.p0, self.e1, self.e2 = p0, e1, e2
        self.pvec = np.cross(self.d, e2)
        self.det = np.einsum('ij,ij->i', e1, self.pvec)
        self.inv = np.where(np.abs(self.det) > EPS, 1.0 / np.where(self.det == 0, 1, self.det), 0.0)
        self.valid = np.abs(self.det) > EPS
        self.owner = owner

    def hits(self, origins):
        O = np.asarray(origins, float)
        ou = ((O @ self.u - self.lo[0]) / self.cell[0]).astype(int)
        ov = ((O @ self.v - self.lo[1]) / self.cell[1]).astype(int)
        out = []
        for r in range(len(O)):
            iu, iv = ou[r], ov[r]
            if iu < 0 or iv < 0 or iu >= self.n or iv >= self.n:
                out.append((np.zeros(0), np.zeros(0, np.int32))); continue
            c = iu * self.n + iv
            cand = self.tri[self.start[c]:self.end[c]]
            if not len(cand):
                out.append((np.zeros(0), np.zeros(0, np.int32))); continue
            cand = cand[self.valid[cand]]
            o = O[r]
            tvec = o - self.p0[cand]
            uu = np.einsum('ij,ij->i', tvec, self.pvec[cand]) * self.inv[cand]
            m = (uu >= -1e-9) & (uu <= 1 + 1e-9)
            if not m.any():
                out.append((np.zeros(0), np.zeros(0, np.int32))); continue
            cd = cand[m]; tv2 = tvec[m]
            qvec = np.cross(tv2, self.e1[cd])
            vv = (qvec @ self.d) * self.inv[cd]
            m2 = (vv >= -1e-9) & (uu[m] + vv <= 1 + 1e-9)
            if not m2.any():
                out.append((np.zeros(0), np.zeros(0, np.int32))); continue
            cd2 = cd[m2]
            t = np.einsum('ij,ij->i', self.e2[cd2], qvec[m2]) * self.inv[cd2]
            m3 = t > 1e-7
            t = t[m3]; ow = self.owner[cd2[m3]]
            k = np.argsort(t)
            out.append((t[k], ow[k]))
        return out
