#!/usr/bin/env python3
"""panel_reform.py — Class-A body-surface repair by LOCAL RECONSTRUCTION.

GATE 5. The owner's criteria are continuous reflection flow, no triangle
chatter, no broad dents or scan noise, consistent manufactured curvature,
clean edge flow around apertures, and no zero-area or stretched faces. He is
explicit that smooth shading, weighted normals, subdivision and glossy paint
MAY SUPPORT good geometry but CANNOT correct bad geometry, and that endless
smoothing of a bad scan is not acceptable — a defective panel is to be
REPLACED BY RECONSTRUCTION.

WHY THIS IS NOT THE SIXTH SMOOTHING PASS. Five levers have already been
measured against this melt and survived by all five (input prep, view count,
generation resolution, seed, and the Blender correction stage), and this repo
already holds `surface_clean.py` (bilateral normal filtering), `despike.py`,
`bonnet_relax.py` and `process_candidate.py` (measured a VISUAL NO-OP). Every
one of them is a DIFFUSION: an iterative averaging that walks the surface
downhill. Diffusion has three properties that make it the wrong tool here —
it shrinks curved panels, it rounds the features you want to keep, and it has
no wavelength: "8 iterations" is not a statement about what survives.

This is a PROJECTION instead. Each vertex is replaced by its position on a
polynomial surface fitted to its neighbourhood (moving least squares, the
Levin / point-set-surfaces construction). The consequences are the ones the
brief asks for:

  * The support radius R IS the wavelength cutoff, stated in millimetres.
    Undulation shorter than R is not in the function space, so it cannot
    survive the projection — it is removed BY CONSTRUCTION, not by iterating
    until it fades.
  * A degree-2 fit REPRODUCES a curved panel exactly (a roof of radius 2 m is
    a quadric at this scale), so there is no shrinkage and no flattening. This
    is the property Laplacian smoothing does not have and is the whole reason
    a projection can be run hard enough to matter.
  * It is one shot. `--iters` reweights outliers; it does not accumulate
    smoothing.

FEATURE PRESERVATION, which is the obvious way this gate fails. Flattening the
waves by also flattening the shut lines is a worse car, so:
  * an edge sharper than --feature-deg is a FEATURE; faces touching one, and
    --feature-rings of faces around them, get weight 0 and are not moved,
  * the weight ramps smoothly from 0 to 1 over those rings, so no step is
    introduced at the boundary of the protected zone,
  * neighbours whose normal disagrees by more than --normal-agree are excluded
    from the fit, so a fit near a crease stays on ITS OWN side and cannot
    reach across a panel gap and fill it,
  * `surface_metric.py` prints crease_len_m beside the quality number for
    exactly this reason. A run that improved the metric by destroying the
    creases is visible there, and this file prints the same number itself.

FRAGMENT SOUP. The generated body is 1,974 connected shells whose border
vertices are DUPLICATED (194,892 vertices weld to 140,124). Fitting per-shell
would move each copy of a border vertex differently and crack every seam, so
faces are re-indexed onto welded ids, the projection runs on welded topology,
and each welded vertex's displacement is written back to ALL of its
duplicates. Seams stay sealed by construction. Topology and UVs are never
touched, so the baked texture survives — the file only ever moves positions.

NORMALS ARE A SEPARATE, DECLARED STEP (--normals). The exported NORMAL
attribute on the input is the UNWELDED geometric normal (measured: 0.018 deg
from it), which puts a hard shading break along every one of those 1,973 shell
borders — 25% of body vertices differ from the welded normal by more than
5 deg. Recomputing them is legitimate and is NOT a geometry repair, so it is a
separate flag, it defaults ON only because shipping known-wrong normals is
worse, and the evidence protocol in the report compares LIKE FOR LIKE (both
sides of the before/after carrying the same normals treatment) so that no part
of the geometry claim can be resting on it.

Run:
  python3 panel_reform.py <in.glb> <out.glb>
        [--passes 0.090:14,0.035:6]   # radius_m:cap_mm, applied in order
        [--degree 2] [--iters 3] [--feature-deg 35] [--feature-rings 2]
        [--normal-agree 0.60] [--geom carpaint] [--normals smooth|keep]
        [--smooth-deg 35] [--report out.json]
"""
import argparse
import json
import math
import os
import struct
import sys
import time

import numpy as np
import trimesh
from scipy.spatial import cKDTree

BODY_TOK = ("carpaint", "paint", "body", "coloured", "car_paint")
NOTBODY_TOK = ("glass", "window", "windscreen", "screen", "tyre", "tire",
               "rubber", "interior", "lamp", "light", "lens", "rim", "wheel")
MAX_NBRS = 260


# --------------------------------------------------------------------- weld
class Weld:
    """Welded view of one geometry, plus the map back to its own vertices."""

    def __init__(self, V, F, tol_rel=1e-6):
        s = float(np.ptp(V, axis=0).max())
        key = np.round(V / (tol_rel * s)).astype(np.int64)
        _, first, inv = np.unique(key, axis=0, return_index=True,
                                  return_inverse=True)
        self.inv = inv
        self.Vw = V[first].astype(np.float64)
        Fw = inv[F]
        keep = (Fw[:, 0] != Fw[:, 1]) & (Fw[:, 1] != Fw[:, 2]) & \
               (Fw[:, 0] != Fw[:, 2])
        self.Fw = Fw[keep]
        self.keep = keep                # welded faces map to F[keep], not F
        self.dropped = int((~keep).sum())
        self.mesh = trimesh.Trimesh(vertices=self.Vw, faces=self.Fw,
                                    process=False)

    def scatter(self, Vw_new):
        return Vw_new[self.inv]


# ------------------------------------------------------------ feature weight
def feature_weight(mesh, feature_deg, rings):
    """Per-VERTEX blend weight: 0 on a feature, ramping to 1 `rings` away.

    The ramp is what stops the repair introducing a step at the edge of the
    protected zone — a hard 0/1 mask would leave the last unmoved ring
    standing proud of its moved neighbour by the full displacement.
    """
    adj = mesh.face_adjacency
    ang = mesh.face_adjacency_angles
    sharp = ang > math.radians(feature_deg)
    F = mesh.faces
    nv = len(mesh.vertices)
    lvl = np.full(nv, rings + 1, dtype=np.int32)
    if sharp.any():
        seed = np.unique(mesh.face_adjacency_edges[sharp].ravel())
        lvl[seed] = 0
        # BFS over the edge graph, `rings` steps
        e = mesh.edges_unique
        cur = seed
        for r in range(1, rings + 1):
            m0 = np.isin(e[:, 0], cur)
            m1 = np.isin(e[:, 1], cur)
            nxt = np.unique(np.concatenate([e[m0][:, 1], e[m1][:, 0]]))
            nxt = nxt[lvl[nxt] > r]
            if len(nxt) == 0:
                break
            lvl[nxt] = r
            cur = nxt
    w = np.clip(lvl / float(max(rings, 1)), 0.0, 1.0)
    # smoothstep so the ramp has no corner of its own
    w = w * w * (3.0 - 2.0 * w)
    return w, int((lvl == 0).sum())


def crease_length(mesh, deg):
    ang = mesh.face_adjacency_angles
    e = mesh.face_adjacency_edges[ang > math.radians(deg)]
    if len(e) == 0:
        return 0.0
    return float(np.linalg.norm(mesh.vertices[e[:, 0]] - mesh.vertices[e[:, 1]],
                                axis=1).sum())


# ------------------------------------------------------------------ the MLS
def mls_project(V, N, radius, degree=2, iters=3, normal_agree=0.60,
                chunk_bytes=4e7, verbose=True):
    """Return the MLS-projected positions of V.

    For each point: build a REFERENCE FRAME, weight neighbours by a compact
    radial kernel, least-squares fit a bivariate polynomial of `degree`, and
    move the point to the fitted height at its own (x=0, y=0).

    THE FRAME COMES FROM A WEIGHTED PCA OF THE NEIGHBOURHOOD, NOT FROM THE
    VERTEX'S OWN NORMAL, and that is the difference between this working and
    not working. MEASURED on the Golf body, R = 90 mm, no blend and no cap, so
    nothing else could be blamed:

        vertex-normal frames   crease(35deg)  102.0 m -> 1188.3 m
        PCA frames             crease(35deg)  102.0 m ->    36.5 m

    A projection along each vertex's own normal moves neighbouring vertices in
    WILDLY DIFFERENT DIRECTIONS precisely where the normal field is worst —
    which is the defect being repaired — so it scatters the surface instead of
    reforming it, and it does so more the harder you push. The neighbourhoods
    at this radius overlap heavily, so their PCA normals vary smoothly even
    when the per-vertex normals do not, and the projection becomes coherent.
    This is Alexa/Levin's reference-plane construction and the reason it is
    specified that way; arriving at it from the other direction cost one
    12x-worse run.

    The vertex normal is still used, but only for two things it can be trusted
    with: choosing the SIGN of the PCA normal, and a first-pass neighbour
    agreement test.

    Robustness: `iters` rounds of reweighting knock down neighbours that the
    current fit does not explain (a Welsch-style redescending weight). Without
    it a single spike inside the support drags the whole patch, which is how a
    naive fit turns one artefact into a dent the size of the support radius.
    """
    n = len(V)
    tree = cKDTree(V)
    k = min(MAX_NBRS, n)
    ncol = {1: 3, 2: 6, 3: 10}[degree]
    out = V.copy()
    moved_h = np.zeros(n)
    determined = np.zeros(n, dtype=bool)
    CH = max(1, int(chunk_bytes / (k * 8 * (ncol + 6))))
    t0 = time.time()
    for s in range(0, n, CH):
        sl = slice(s, min(s + CH, n))
        P0 = V[sl]
        n0 = N[sl]
        d, nb = tree.query(P0, k=k, workers=-1)
        ok = (d <= radius) & (nb < n)
        ok[:, 0] = True
        ok &= np.einsum("mkj,mj->mk", N[nb], n0) > normal_agree

        D = V[nb] - P0[:, None, :]

        # ---- reference frame: weighted PCA of the neighbourhood
        wp = (1.0 - np.minimum(d, radius) / radius) ** 2 * ok
        wsum = wp.sum(1).clip(1e-12)
        mu = np.einsum("mk,mkj->mj", wp, D) / wsum[:, None]
        Dc = D - mu[:, None, :]
        cov = np.einsum("mk,mki,mkj->mij", wp, Dc, Dc) / wsum[:, None, None]
        evals, evecs = np.linalg.eigh(cov)          # ascending
        npca = evecs[:, :, 0]
        # sign: agree with the vertex normal, which is reliable for a SIGN even
        # when it is useless for a direction
        npca *= np.sign(np.einsum("mj,mj->m", npca, n0))[:, None]
        # a neighbourhood too flat to define a plane (a degenerate sliver) keeps
        # the vertex normal rather than a random eigenvector
        degen = evals[:, 2] < 1e-18
        npca[degen] = n0[degen]

        tmp = np.tile(np.array([1.0, 0.0, 0.0]), (len(P0), 1))
        tmp[np.abs(npca[:, 0]) > 0.9] = np.array([0.0, 1.0, 0.0])
        ex = np.cross(npca, tmp)
        ex /= np.linalg.norm(ex, axis=1, keepdims=True).clip(1e-12)
        ey = np.cross(npca, ex)
        x = np.einsum("mkj,mj->mk", D, ex)
        y = np.einsum("mkj,mj->mk", D, ey)
        z = np.einsum("mkj,mj->mk", D, npca)

        r = np.sqrt(x * x + y * y).clip(0, radius)
        wker = (1.0 - r / radius) ** 4 * ok          # compact, C1 at the rim
        cols = [np.ones_like(x), x, y]
        if degree >= 2:
            cols += [x * x, x * y, y * y]
        if degree >= 3:
            cols += [x ** 3, x * x * y, x * y * y, y ** 3]
        B = np.stack(cols, axis=-1)

        w = wker.copy()
        coef = None
        for it in range(max(1, iters)):
            Bw = B * w[..., None]
            AtA = np.einsum("mki,mkj->mij", Bw, B)
            Atb = np.einsum("mki,mk->mi", Bw, z)
            tr = np.trace(AtA, axis1=1, axis2=2)
            AtA[:, np.arange(ncol), np.arange(ncol)] += (1e-9 * tr + 1e-30)[:, None]
            good = ok.sum(1) >= (ncol + 4)
            coef = np.zeros((len(P0), ncol))
            if good.any():
                # b as (n,ncol,1): NumPy 2 reads a 2-D b as one matrix, not a
                # stack of vectors, and silently mis-shapes the solve.
                coef[good] = np.linalg.solve(AtA[good],
                                             Atb[good][..., None])[..., 0]
            if it == max(1, iters) - 1:
                break
            res = z - np.einsum("mki,mi->mk", B, coef)
            scale = 1.4826 * np.median(np.abs(res) * ok + 1e-9, axis=1)
            scale = np.maximum(scale, 1e-5)[:, None]
            w = wker * np.exp(-(res / (3.0 * scale)) ** 2)

        h = coef[:, 0]                               # fitted height at x=y=0
        determined[sl] = good
        h = np.where(good, h, 0.0)
        moved_h[sl] = h
        out[sl] = P0 + h[:, None] * n0
    if verbose:
        print(f"    MLS r={radius*1000:.0f}mm deg{degree} iters{iters}: "
              f"{determined.sum()}/{n} determined, "
              f"|h| mean {np.abs(moved_h[determined]).mean()*1000:.2f}mm "
              f"p99 {np.percentile(np.abs(moved_h[determined]),99)*1000:.2f}mm "
              f"max {np.abs(moved_h[determined]).max()*1000:.2f}mm "
              f"({time.time()-t0:.1f}s)")
    return out, moved_h, determined


# --------------------------------------------------------------- normals
def smooth_normals(mesh, smooth_deg, inv, nvert):
    """Per-ORIGINAL-vertex normals averaged only across edges softer than
    `smooth_deg`, so a shut line stays a hard edge and a panel goes smooth.
    Topology is not changed: the mesh already carries duplicate vertices at
    every shell border, which is where the hard breaks need to be anyway."""
    F = mesh.faces
    fn = mesh.face_normals
    fa = mesh.area_faces
    adj = mesh.face_adjacency
    ang = mesh.face_adjacency_angles
    soft = ang <= math.radians(smooth_deg)
    # smoothing groups = connected components of the face graph over soft edges
    import scipy.sparse as sp
    from scipy.sparse.csgraph import connected_components
    e = adj[soft]
    g = sp.coo_matrix((np.ones(len(e)), (e[:, 0], e[:, 1])),
                      shape=(len(F), len(F)))
    ngrp, grp = connected_components(g + g.T, directed=False)
    # accumulate per (welded vertex, group) then read back per original vertex
    key = grp[:, None].repeat(3, 1).ravel() * (len(mesh.vertices) + 1) + F.ravel()
    uk, ui = np.unique(key, return_inverse=True)
    acc = np.zeros((len(uk), 3))
    np.add.at(acc, ui, (fn * fa[:, None])[:, None, :].repeat(3, 1).reshape(-1, 3))
    acc /= np.linalg.norm(acc, axis=1, keepdims=True).clip(1e-12)
    # each ORIGINAL vertex: average the (group,vertex) normals of its faces
    return acc, ui, ngrp


# ------------------------------------------------------------------- driver
def pick_body(scene, geom):
    names = []
    for name, g in scene.geometry.items():
        if not isinstance(g, trimesh.Trimesh) or len(g.faces) == 0:
            continue
        mat = getattr(getattr(g, "visual", None), "material", None)
        mname = (getattr(mat, "name", None) or name or "").lower()
        if geom:
            if any(t.strip().lower() in (name or "").lower()
                   or t.strip().lower() in mname for t in geom.split(",")):
                names.append(name)
        elif any(t in mname for t in BODY_TOK) and \
                not any(t in mname for t in NOTBODY_TOK):
            names.append(name)
    return names


def face_health(mesh):
    a = mesh.area_faces
    tri = mesh.vertices[mesh.faces]
    e = np.stack([np.linalg.norm(tri[:, 1] - tri[:, 0], axis=1),
                  np.linalg.norm(tri[:, 2] - tri[:, 1], axis=1),
                  np.linalg.norm(tri[:, 0] - tri[:, 2], axis=1)], axis=1)
    lo = e.min(1).clip(1e-12)
    hi = e.max(1)
    return dict(min_area_mm2=round(float(a.min()) * 1e6, 6),
                zero_area=int((a < 1e-12).sum()),
                aspect_p99=round(float(np.percentile(hi / lo, 99)), 2),
                aspect_max=round(float((hi / lo).max()), 2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inp")
    ap.add_argument("out")
    ap.add_argument("--passes", default="0.090:14,0.035:6",
                    help="radius_m:cap_mm pairs, applied in order")
    ap.add_argument("--degree", type=int, default=2, choices=(1, 2, 3))
    ap.add_argument("--iters", type=int, default=3)
    ap.add_argument("--feature-deg", type=float, default=35.0)
    ap.add_argument("--feature-rings", type=int, default=2)
    ap.add_argument("--normal-agree", type=float, default=0.60)
    ap.add_argument("--geom", default=None,
                    help="comma list of geometry/material names to repair; "
                         "default = auto-detected body paint")
    ap.add_argument("--normals", choices=["smooth", "keep"], default="smooth")
    ap.add_argument("--smooth-deg", type=float, default=35.0)
    ap.add_argument("--report", default=None)
    a = ap.parse_args()

    sc = trimesh.load(a.inp, force="scene")
    targets = pick_body(sc, a.geom)
    if not targets:
        raise SystemExit(f"REFUSED: no body geometry found in {a.inp}")
    print(f"{a.inp}: repairing {targets}, leaving "
          f"{[n for n in sc.geometry if n not in targets]} untouched")

    rep = dict(input=os.path.basename(a.inp), targets=targets,
               passes=a.passes, degree=a.degree, iters=a.iters,
               feature_deg=a.feature_deg, feature_rings=a.feature_rings,
               normal_agree=a.normal_agree, normals=a.normals, geoms={})

    plan = []
    for tok in a.passes.split(","):
        r, c = tok.split(":")
        plan.append((float(r), float(c) / 1000.0))

    for name in targets:
        g = sc.geometry[name]
        V0 = np.asarray(g.vertices, dtype=np.float64).copy()
        F = np.asarray(g.faces)
        wl = Weld(V0, F)
        mesh = wl.mesh
        print(f"  {name}: {len(V0)} verts -> {len(wl.Vw)} welded, "
              f"{len(wl.Fw)} faces")
        gw, nfeat = feature_weight(mesh, a.feature_deg, a.feature_rings)
        cl0 = crease_length(mesh, a.feature_deg)
        h0 = face_health(mesh)
        print(f"    feature verts {nfeat} ({nfeat/len(wl.Vw)*100:.1f}%), "
              f"crease {cl0:.2f}m, movable weight mean {gw.mean():.3f}")

        Vw = wl.Vw.copy()
        for (R, cap) in plan:
            mesh.vertices = Vw
            mesh._cache.clear()
            N = np.asarray(mesh.vertex_normals)
            tgt, h, det = mls_project(Vw, N, R, degree=a.degree,
                                      iters=a.iters,
                                      normal_agree=a.normal_agree)
            delta = (tgt - Vw) * gw[:, None]
            d = np.linalg.norm(delta, axis=1)
            over = d > cap
            if over.any():
                delta[over] *= (cap / d[over])[:, None]
            Vw = Vw + delta
            print(f"    applied cap {cap*1000:.0f}mm: moved "
                  f"{(d>1e-6).sum()} verts, mean "
                  f"{d[d>1e-6].mean()*1000:.2f}mm, capped {int(over.sum())}")

        mesh.vertices = Vw
        mesh._cache.clear()
        cl1 = crease_length(mesh, a.feature_deg)
        h1 = face_health(mesh)
        tot = np.linalg.norm(Vw - wl.Vw, axis=1)
        print(f"    TOTAL displacement: mean {tot.mean()*1000:.2f}mm "
              f"p99 {np.percentile(tot,99)*1000:.2f}mm max {tot.max()*1000:.2f}mm")
        print(f"    crease {cl0:.2f}m -> {cl1:.2f}m "
              f"({(cl1-cl0)/max(cl0,1e-9)*100:+.1f}%)   faces {h0} -> {h1}")
        rep["geoms"][name] = dict(
            verts=int(len(V0)), welded=int(len(wl.Vw)), faces=int(len(wl.Fw)),
            feature_verts=nfeat,
            crease_m_before=round(cl0, 3), crease_m_after=round(cl1, 3),
            crease_pct=round((cl1 - cl0) / max(cl0, 1e-9) * 100, 2),
            disp_mm=dict(mean=round(float(tot.mean()) * 1000, 3),
                         p99=round(float(np.percentile(tot, 99)) * 1000, 3),
                         max=round(float(tot.max()) * 1000, 3)),
            faces_before=h0, faces_after=h1)

        g.vertices = wl.scatter(Vw)
        if a.normals == "smooth":
            acc, ui, ngrp = smooth_normals(mesh, a.smooth_deg, wl.inv, len(V0))
            # per ORIGINAL vertex: mean of the (group, welded-vertex) normals
            # of the corners that reference it. F[wl.keep], NOT F — welding
            # DROPS degenerate faces, so the corner arrays are only the same
            # length on the kept subset. Using F here mis-shapes the scatter.
            corner_v = F[wl.keep].ravel()
            nrm = np.zeros((len(V0), 3))
            np.add.at(nrm, corner_v, acc[ui])
            ln = np.linalg.norm(nrm, axis=1, keepdims=True)
            bad = (ln[:, 0] < 1e-9)
            nrm = nrm / ln.clip(1e-12)
            if bad.any():
                nrm[bad] = np.asarray(g.vertex_normals)[bad]
            g.vertex_normals = nrm
            print(f"    normals: {ngrp} smoothing groups at "
                  f"{a.smooth_deg:.0f}deg")
            rep["geoms"][name]["smoothing_groups"] = int(ngrp)

    out = trimesh.Scene()
    for node in sc.graph.nodes_geometry:
        T, gn = sc.graph[node]
        if gn not in out.geometry:
            out.add_geometry(sc.geometry[gn], geom_name=gn, node_name=node,
                             transform=T)
        else:
            out.graph.update(frame_to=node, matrix=T, geometry=gn)
    out.export(a.out, include_normals=True)

    # a body without a NORMAL attribute renders flat-shaded and every claim in
    # the report would be about the wrong thing. Refuse rather than ship it.
    with open(a.out, "rb") as fh:
        fh.seek(12)
        ln, _ = struct.unpack("<II", fh.read(8))
        j = json.loads(fh.read(ln))
    missing = [m.get("name") for m in j["meshes"]
               if any("NORMAL" not in p["attributes"] for p in m["primitives"])]
    if missing:
        raise SystemExit(f"REFUSED: NORMAL missing on {missing[:4]}")
    lost_uv = [m.get("name") for m in j["meshes"]
               if any("TEXCOORD_0" not in p["attributes"] for p in m["primitives"])
               and m.get("name") in targets]
    rep["output_bytes"] = os.path.getsize(a.out)
    rep["uv_missing_on_targets"] = lost_uv
    print(f"wrote {a.out} ({rep['output_bytes']} bytes)")
    if lost_uv:
        print(f"  WARNING: TEXCOORD_0 absent on repaired {lost_uv}")
    if a.report:
        with open(a.report, "w") as fh:
            json.dump(rep, fh, indent=1)
        print("report ->", a.report)


if __name__ == "__main__":
    main()
