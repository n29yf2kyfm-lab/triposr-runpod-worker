"""
measure.py -- independent measurements. Every function takes a Glb and returns
plain numbers. Nothing here reads any other agent's report.

Conventions established by measurement, not assumption:
  * up axis and nose direction are DERIVED (derive_frame) and printed, never
    assumed from a note.
  * grounding is measured from the TYRE NODES' world-space minima, never from
    the whole-model bbox -- viewer_check.py passes a car with its front tyres
    183 mm in the air because it reads the bbox.
"""
import numpy as np
from glbcore import Glb, tri_areas, tri_centroids


# ---------------------------------------------------------------- frame
def derive_frame(g):
    """Return dict describing the car's frame from raw world geometry only."""
    P = []
    for n in g.nodes():
        for _mi, Vw, F in g.node_world_geom(n):
            if len(F):
                P.append(Vw[np.unique(F)])
    P = np.vstack(P)
    ext = P.max(0) - P.min(0)
    up = int(np.argmin(ext))          # smallest extent = height for a car
    length = int(np.argmax(ext))
    side = 3 - up - length
    return dict(extent=ext.tolist(), up=up, length=length, side=side,
                min=P.min(0).tolist(), max=P.max(0).tolist(), nverts=len(P))


def node_map(g):
    return {n.name: n for n in g.nodes()}


def node_world_verts(g, name):
    n = node_map(g).get(name)
    if n is None:
        return None
    out = []
    for _mi, Vw, F in g.node_world_geom(n):
        if len(F):
            out.append(Vw[np.unique(F)])
    return np.vstack(out) if out else None


def node_world_tris(g, name):
    """-> (V_world, F) concatenated over the node's primitives."""
    n = node_map(g).get(name)
    if n is None:
        return None, None
    Vs, Fs, off = [], [], 0
    for _mi, Vw, F in g.node_world_geom(n):
        if not len(F):
            continue
        Vs.append(Vw)
        Fs.append(F + off)
        off += len(Vw)
    if not Vs:
        return None, None
    return np.vstack(Vs), np.vstack(Fs)


# ---------------------------------------------------------------- M1 grounding
TYRES = ['Wheel_FL_Tyre', 'Wheel_FR_Tyre', 'Wheel_RL_Tyre', 'Wheel_RR_Tyre']


def tyre_grounding(g, up=1, contact_pct=0.02):
    """Per-tyre world-space minimum along `up`, in mm, relative to the
    CONTACT PLANE = the lowest of the four tyre minima (a car's ground plane is
    its contact patches -- not the lowest vertex in the scene, which on this
    car is the underbody 9.5 mm below the tyres)."""
    res = {}
    for t in TYRES:
        V = node_world_verts(g, t)
        res[t] = None if V is None else float(V[:, up].min())
    have = [v for v in res.values() if v is not None]
    if not have:
        return dict(per_tyre_m=res, ok=False)
    plane = min(have)
    return dict(per_tyre_m=res,
                contact_plane_m=plane,
                per_tyre_mm_above_contact={k: (None if v is None else (v - plane) * 1000.0)
                                           for k, v in res.items()},
                max_air_mm=max((v - plane) * 1000.0 for v in have),
                bbox_min_m=float(min(
                    node_world_verts(g, n.name)[:, up].min()
                    for n in g.nodes()
                    if n.mesh is not None and node_world_verts(g, n.name) is not None)))


# ---------------------------------------------------------------- M2 glass area
def node_areas(g, names=None, prefix=None):
    out = {}
    for n in g.nodes():
        if n.mesh is None:
            continue
        if names and n.name not in names:
            continue
        if prefix and not n.name.startswith(prefix):
            continue
        V, F = node_world_tris(g, n.name)
        out[n.name] = float(tri_areas(V, F).sum()) if V is not None else 0.0
    return out


def material_area(g):
    """world-space area per MATERIAL NAME (m^2 if the file is in metres)."""
    mats = g.material_names()
    out = {}
    for n in g.nodes():
        if n.mesh is None:
            continue
        R, t = n.world[:3, :3], n.world[:3, 3]
        for p in range(len(g.json['meshes'][n.mesh]['primitives'])):
            F = g.prim_indices(n.mesh, p)
            if not len(F):
                continue
            Vw = g.prim_positions(n.mesh, p) @ R.T + t
            mi = g.prim_material(n.mesh, p)
            nm = mats[mi] if mi is not None else '<none>'
            out[nm] = out.get(nm, 0.0) + float(tri_areas(Vw, F).sum())
    return out


def node_normal_stats(g, name, up=1):
    """area-weighted mean unit normal + area, for asking 'is this a screen or a
    near-horizontal scuttle shelf'."""
    V, F = node_world_tris(g, name)
    if V is None:
        return None
    a = V[F[:, 1]] - V[F[:, 0]]
    b = V[F[:, 2]] - V[F[:, 0]]
    cr = np.cross(a, b)
    ar = 0.5 * np.linalg.norm(cr, axis=1)
    m = ar > 0
    nrm = cr[m] / (2 * ar[m])[:, None]
    mean = (nrm * ar[m][:, None]).sum(0) / ar[m].sum()
    return dict(area=float(ar.sum()), mean_normal=mean.tolist(),
                mean_abs_up=float(np.abs((nrm[:, up] * ar[m]).sum() / ar[m].sum())),
                bbox=[V[np.unique(F)].min(0).tolist(), V[np.unique(F)].max(0).tolist()])


# ---------------------------------------------------------------- M3 provenance
def centroid_coincidence(g_new, names_new, g_src, tol_m=1e-6):
    """% of the new components' face centroids that coincide with ANY face
    centroid in the source file. 0% = the component is genuinely new geometry,
    not reused source faces. Uses a KD-tree, tolerance in metres."""
    from scipy.spatial import cKDTree
    C = []
    for n in g_src.nodes():
        for _mi, Vw, F in g_src.node_world_geom(n):
            if len(F):
                C.append(tri_centroids(Vw, F))
    C = np.vstack(C)
    tree = cKDTree(C)
    out = {}
    for nm in names_new:
        V, F = node_world_tris(g_new, nm)
        if V is None:
            out[nm] = None
            continue
        c = tri_centroids(V, F)
        d, _ = tree.query(c, k=1)
        out[nm] = dict(faces=int(len(c)),
                       pct_coincident=float(100.0 * (d <= tol_m).mean()),
                       min_d_mm=float(d.min() * 1000), median_d_mm=float(np.median(d) * 1000))
    return out


def mirror_symmetry(g, names, side_axis=2, plane=0.0):
    """max |v + mirror(nearest)| residual, mm. For a component set that should be
    mirror-symmetric about the side axis."""
    from scipy.spatial import cKDTree
    out = {}
    for nm in names:
        V = node_world_verts(g, nm)
        if V is None:
            out[nm] = None
            continue
        M = V.copy()
        M[:, side_axis] = 2 * plane - M[:, side_axis]
        d, _ = cKDTree(V).query(M, k=1)
        out[nm] = dict(verts=int(len(V)), max_mm=float(d.max() * 1000),
                       rms_mm=float(np.sqrt((d ** 2).mean()) * 1000))
    return out


def pair_symmetry(g, a, b, side_axis=2, plane=0.0):
    """Mirror node a onto node b and measure nearest-neighbour residual."""
    from scipy.spatial import cKDTree
    A, B = node_world_verts(g, a), node_world_verts(g, b)
    if A is None or B is None:
        return None
    Am = A.copy()
    Am[:, side_axis] = 2 * plane - Am[:, side_axis]
    d, _ = cKDTree(B).query(Am, k=1)
    return dict(a=a, b=b, nA=int(len(A)), nB=int(len(B)),
                max_mm=float(d.max() * 1000), rms_mm=float(np.sqrt((d**2).mean()) * 1000),
                mean_mm=float(d.mean() * 1000))


def centreline_offset(g, names, side_axis=2):
    """area-weighted centroid offset from z=0, mm -- for badge / plate."""
    out = {}
    for nm in names:
        V, F = node_world_tris(g, nm)
        if V is None:
            out[nm] = None
            continue
        ar = tri_areas(V, F)
        c = tri_centroids(V, F)
        out[nm] = dict(area_weighted_mm=float((c[:, side_axis] * ar).sum() / ar.sum() * 1000),
                       bbox_mid_mm=float((V[:, side_axis].min() + V[:, side_axis].max()) / 2 * 1000),
                       verts=int(len(V)))
    return out
