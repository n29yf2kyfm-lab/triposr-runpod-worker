#!/usr/bin/env python3
"""geo7.py -- GATE 3 v7 geometry primitives.

Every component is a CLOSED grid solid extruded along -X (the nose direction on
this file).  Nothing is ever extruded along a sampled surface normal: 46% of the
body faces in the lamp band carry inverted normals on this family of meshes, and
that built three earlier lens passes inside-out.

`grid_solid` returns one watertight shell: a front sheet, a back sheet, and a
skirt joining their boundaries.  A minimum thickness is ENFORCED rather than
assumed -- if the back sheet is allowed to cross the front one the shell
self-intersects, which is precisely v6's worst defect (10,258 self-intersecting
triangle pairs, 2,924 of them in Bumper_Front).
"""
import numpy as np
import trimesh

MIN_T = 0.0015          # 1.5 mm: below this a shell is not reliably manifold


def grid_solid(XBASE, Y, Z, Dfront, Dback, enforce=True):
    """Closed shell between two depth sheets over a structured (Y,Z) grid.

    Y, Z are (ny, nz).  Dfront/Dback are depths BEHIND the nose plane, so the
    front sheet is at x = XBASE + Dfront.  Dback must exceed Dfront everywhere.
    """
    Y = np.asarray(Y, float)
    Z = np.asarray(Z, float)
    ny, nz = Y.shape
    n = ny * nz
    Df = np.broadcast_to(np.asarray(Dfront, float), (ny, nz)).astype(float).copy()
    Db = np.broadcast_to(np.asarray(Dback, float), (ny, nz)).astype(float).copy()
    if enforce:
        Df = np.maximum(Df, 0.002)              # never in front of the nose plane
        Db = np.maximum(Db, Df + MIN_T)
    V = np.vstack([np.stack([XBASE + Df.ravel(), Y.ravel(), Z.ravel()], 1),
                   np.stack([XBASE + Db.ravel(), Y.ravel(), Z.ravel()], 1)])
    F = []
    for j in range(ny - 1):
        for i in range(nz - 1):
            a = j * nz + i
            b, c, e = a + 1, a + nz, a + nz + 1
            F += [[a, c, e], [a, e, b],
                  [a + n, e + n, c + n], [a + n, b + n, e + n]]
    edge = ([j * nz for j in range(ny)] +
            [(ny - 1) * nz + i for i in range(1, nz)] +
            [j * nz + (nz - 1) for j in range(ny - 2, -1, -1)] +
            [i for i in range(nz - 2, 0, -1)])
    for k in range(len(edge)):
        a, b = edge[k], edge[(k + 1) % len(edge)]
        F += [[a, b, b + n], [a, b + n, a + n]]
    m = trimesh.Trimesh(vertices=V, faces=np.asarray(F), process=True)
    m.fix_normals()
    return m


def rect_grid(y0, y1, z0, z1, ny, nz):
    Y = np.repeat(np.linspace(y0, y1, ny)[:, None], nz, 1)
    Z = np.repeat(np.linspace(z0, z1, nz)[None, :], ny, 0)
    return Y, Z


def disc_solid(XBASE, yc, zc, r, dfront, dback, nr=6, nt=56):
    """A CLOSED disc solid: front cap, back cap, and a cylindrical rim.

    A radial (nr x nt) grid must NOT go through `grid_solid`.  The angular axis
    WRAPS, and grid_solid treats its grid as an open rectangle -- so the seam
    between the last and first angular sample is never joined and the "skirt" is
    built across the radius instead of around the rim.  The result renders as a
    disc with a wedge missing, which is exactly what the badge and the tow-eye
    cover did on the first build.  Caught in the material-ID pass, where both
    appeared as half-discs.

    Built explicitly here instead: rings share their angular indices modulo nt,
    the centre is a single vertex per cap (a fan, but only at the very centre,
    where the triangles are still non-degenerate because r0 > 0 is not needed),
    and the rim is a quad strip.

    `dfront`/`dback` may be scalars OR callables f(y, z) -> depth.  They must be
    callables on a RAKED panel: this car's fascia falls back 136.8 mm across the
    badge's own 118.6 mm height, so a flat disc at the centre depth sits 61.5 mm
    BEHIND the bumper at its lower edge and a third of it disappears.  Measured,
    after it happened.
    """
    t = np.linspace(0, 2 * np.pi, nt, endpoint=False)
    rr = np.linspace(r / nr, r, nr)
    yy = yc + np.outer(rr, np.cos(t))
    zz = zc + np.outer(rr, np.sin(t))
    V, Fc = [], []

    def dep(f, y, z):
        return float(f(y, z)) if callable(f) else float(f)

    def cap(depth, flip):
        base = len(V)
        V.append([XBASE + dep(depth, yc, zc), yc, zc])   # centre
        for k in range(nr):
            for i in range(nt):
                V.append([XBASE + dep(depth, yy[k, i], zz[k, i]),
                          yy[k, i], zz[k, i]])
        f = []
        for i in range(nt):                            # fan
            a, b = base + 1 + i, base + 1 + (i + 1) % nt
            f.append([base, b, a] if flip else [base, a, b])
        for k in range(nr - 1):                        # rings
            o0 = base + 1 + k * nt
            o1 = o0 + nt
            for i in range(nt):
                j = (i + 1) % nt
                q = [[o0 + i, o1 + i, o1 + j], [o0 + i, o1 + j, o0 + j]]
                f += [x[::-1] for x in q] if flip else q
        return base, f

    b0, f0 = cap(dfront, True)
    b1, f1 = cap(dback, False)
    Fc += f0 + f1
    r0o = b0 + 1 + (nr - 1) * nt                       # outer ring, front cap
    r1o = b1 + 1 + (nr - 1) * nt                       # outer ring, back cap
    for i in range(nt):
        j = (i + 1) % nt
        Fc += [[r0o + i, r1o + i, r1o + j], [r0o + i, r1o + j, r0o + j]]
    m = trimesh.Trimesh(vertices=np.asarray(V, float), faces=np.asarray(Fc),
                        process=True)
    m.fix_normals()
    return m


def funnel(ny, nz, ramp):
    """0 on the outer flange ring, 1 in the interior, smoothstepped.

    Used to ramp an aperture from its lip down to its floor so the well has a
    real wall instead of a vertical discontinuity."""
    j = np.minimum(np.arange(ny)[:, None], (ny - 1) - np.arange(ny)[:, None])
    i = np.minimum(np.arange(nz)[None, :], (nz - 1) - np.arange(nz)[None, :])
    t = np.clip(np.minimum(j, i) / max(ramp, 1), 0, 1)
    return t * t * (3 - 2 * t)


def mirror_z(mesh, zc):
    """Mirror about z = zc AND flip winding, so the copy is not inside-out."""
    m = mesh.copy()
    v = m.vertices.copy()
    v[:, 2] = 2.0 * zc - v[:, 2]
    m.vertices = v
    m.faces = m.faces[:, ::-1]
    m.fix_normals()
    return m
