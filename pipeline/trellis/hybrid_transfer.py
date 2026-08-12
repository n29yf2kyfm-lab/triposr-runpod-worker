#!/usr/bin/env python3
"""hybrid_transfer.py — PartCrafter structure onto a Hunyuan3D mesh.

The measured trade (2026-08-12, same input photo through both generators):

  * PartCrafter (16 parts): parts SEPARATE — canopy, wheels, lamps all come
    out as their own meshes, so materials are assignable — but the surfacing
    is melt, below even TRELLIS.
  * Hunyuan3D-2: clearly the best surfacing of any generator tested (clean
    panels, formed mirrors, readable spokes) — but ONE fused component
    (measured 100.0% of verts), so on its own it is an automatic scrap:
    opaque glazing, painted tyres.

Each has exactly what the other lacks, and both were generated from the SAME
image, so their geometries align (measured mean nearest-neighbour distance
0.020 in the normalized frame). This tool transfers PartCrafter's part
labels onto the Hunyuan mesh per-face:

  1. classify PartCrafter components with partcrafter_materials.classify
     (same rules as the Blender stage; debris dropped),
  2. normalize both meshes into a (length, width, up) unit frame using
     2nd/98th-percentile bounds; resolve orientation by trying length/width
     flips and keeping the lowest NN distance,
  3. k-NN distance-weighted label vote per Hunyuan vertex, face majority,
  4. physical priors (no glazing below the beltline, no tyres above
     mid-height, lamps only at the ends, no interior at the outer width
     extremes or in the roof),
  5. neighbourhood-majority smoothing + absorption of small single-border
     label islands,
  6. canopy faces split roof/glass by |n_up| (ROOF_NORMAL_UP shared with
     partcrafter_materials),
  7. export one GLB with the proven golf scheme (Material_0 / Glass_Tint /
     Wheel_Dark / Interior_Dark / Lamp_Lens).

VALIDATED on the test pair: glass_probe "clear (proven)", red-control
respray keeps glazing/tyres/lamps dark, glazing lands at 10.1% of faces
(real-car band is 4-12%).

KNOWN LIMIT of this v1: label boundaries are only as good as PartCrafter's
own parts. On the test car the windscreen boundary is ragged and one
interior-junk blob transfers onto the front wing — PartCrafter put dashboard
mush against the windscreen base and the NN vote follows it. The fix is a
better segmentation source (e.g. 2D segmentation of multi-view renders
projected onto the mesh), not more smoothing here.

Usage:
    python3 pipeline/trellis/hybrid_transfer.py \
        --parts pc_object.glb --mesh hy_shape.glb --out hybrid.glb
"""
import argparse
import json
import sys
from collections import Counter

import numpy as np
import trimesh
import scipy.sparse as sp
from scipy.spatial import cKDTree
from trimesh.visual.material import PBRMaterial

try:
    import maxflow          # PyMaxflow — crease-snapping graph cut
except ImportError:
    maxflow = None

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from partcrafter_materials import classify, ROOF_NORMAL_UP  # noqa: E402

LABS = ["body", "canopy", "wheel", "interior", "lamp"]
MATS = {
    "body":     PBRMaterial(name="Material_0",    baseColorFactor=[0.60, 0.61, 0.63, 1.0],
                            metallicFactor=0.1, roughnessFactor=0.35),
    "glass":    PBRMaterial(name="Glass_Tint",    baseColorFactor=[0.030, 0.035, 0.045, 0.72],
                            metallicFactor=0.0, roughnessFactor=0.05, alphaMode="BLEND"),
    "wheel":    PBRMaterial(name="Wheel_Dark",    baseColorFactor=[0.030, 0.030, 0.033, 1.0],
                            metallicFactor=0.3, roughnessFactor=0.5),
    "interior": PBRMaterial(name="Interior_Dark", baseColorFactor=[0.045, 0.045, 0.050, 1.0],
                            metallicFactor=0.0, roughnessFactor=0.9),
    "lamp":     PBRMaterial(name="Lamp_Lens",     baseColorFactor=[0.080, 0.080, 0.090, 1.0],
                            metallicFactor=0.0, roughnessFactor=0.08),
}


def _norm_frame(verts):
    """(len, wid, up) axis order + percentile bounds for a Y-up glTF car."""
    lo = np.percentile(verts, 2, axis=0)
    hi = np.percentile(verts, 98, axis=0)
    ext = np.maximum(hi - lo, 1e-9)
    UP = 1                                     # glTF Y-up, trusted (see
    LEN, WID = (0, 2) if ext[0] >= ext[2] else (2, 0)   # partcrafter_materials)
    axes = [LEN, WID, UP]
    return axes, lo[axes], ext[axes]


def labeled_points(parts_glb, cap=8000, seed=0):
    """PartCrafter components -> (points in unit frame, label per point)."""
    s = trimesh.load(parts_glb)
    comps = [c for g in s.geometry.values() for c in g.split(only_watertight=False)]
    allv = np.concatenate([c.vertices for c in comps])
    axes, lo, ext = _norm_frame(allv)
    total = len(allv)
    pts, labs = [], []
    for c in comps:
        clo = [(c.vertices.min(0)[a] - lo[i]) / ext[i] for i, a in enumerate(axes)]
        chi = [(c.vertices.max(0)[a] - lo[i]) / ext[i] for i, a in enumerate(axes)]
        wspan = [c.vertices.max(0)[a] - c.vertices.min(0)[a] for a in axes]
        kind = classify({"frac": len(c.vertices) / total,
                         "lo": clo, "hi": chi, "wspan": wspan}, None)
        if kind == "debris":
            continue
        p = (c.vertices[:, axes] - lo) / ext
        if len(p) > cap:
            p = p[np.random.RandomState(seed).choice(len(p), cap, replace=False)]
        pts.append(p)
        labs += [LABS.index(kind)] * len(p)
    return np.concatenate(pts), np.array(labs)



def _patches(flab, adj, n, lab):
    mask = flab == lab
    same = mask[adj[:, 0]] & mask[adj[:, 1]]
    g = sp.csr_matrix((np.ones(same.sum()), (adj[same, 0], adj[same, 1])), shape=(n, n))
    _, comp = sp.csgraph.connected_components(g + g.T, directed=False)
    comp[~mask] = -1
    return comp, Counter(comp[mask])


def _crease_cut(m, adj, ang, zidx, seed, p_seed, p_other, decay_d=None, tau=0.06,
                lam=4.0):
    """Binary graph cut over zone faces: confident data term from seeds,
    smoothness cheap across creases, optional distance decay. Segment->label
    mapping is resolved EMPIRICALLY against the seeds — PyMaxflow's segment
    convention cost one inverted-run already; never assume it."""
    zmap = {f: i for i, f in enumerate(zidx)}
    p = np.where(seed, p_seed, p_other)
    if decay_d is not None:
        p = np.maximum(p * np.exp(-(decay_d / tau) ** 2), 0.02)
    p = np.clip(p, 1e-4, 1 - 1e-4)
    g = maxflow.Graph[float]()
    nodes = g.add_nodes(len(zidx))
    for i in range(len(zidx)):
        g.add_tedge(nodes[i], -np.log(1 - p[i]), -np.log(p[i]))
    for k, (a, b) in enumerate(adj):
        if a in zmap and b in zmap:
            w = lam * np.exp(-(ang[k] / 0.30) ** 2)
            g.add_edge(nodes[zmap[a]], nodes[zmap[b]], w, w)
    g.maxflow()
    seg = np.array([g.get_segment(nodes[i]) for i in range(len(zidx))])
    pos = 1 if np.mean((seg == 1) == seed) >= np.mean((seg == 0) == seed) else 0
    return seg == pos


def refine(m, flab, hy, pc_pts, pc_lab_names):
    """Fix the transfer's known failure modes, each with a physical argument:
    ragged glass boundaries (snap to creases), interior on the outside
    (visibility ray test), lamp/wheel bleed onto bumper and arch (distance +
    cylinder tests, one-sided lamps mirrored), body islands inside windows.
    All measured on the 2026-08-12 test car; see CLAUDE.md."""
    B, C, W, I, L = 0, 1, 2, 3, 4
    fc = hy[m.faces].mean(axis=1)
    adj = m.face_adjacency
    ang = m.face_adjacency_angles
    n = len(m.faces)
    n_up = np.abs(m.face_normals[:, 1])

    if maxflow is not None:
        # GLASS: cut in the greenhouse zone, data decayed by distance to the
        # PC canopy cloud so stray votes far from the greenhouse cannot win
        can = pc_pts[pc_lab_names == "canopy"]
        d_can = cKDTree(can).query(fc, workers=4)[0] if len(can) else np.full(n, 9.)
        zone = (fc[:, 2] > 0.42) & (fc[:, 0] > 0.05) & (fc[:, 0] < 0.95) \
               & np.isin(flab, [B, C])
        zidx = np.where(zone)[0]
        if len(zidx):
            seed = flab[zidx] == C
            p_roof = np.where(seed, 0.88, 0.10)
            is_g = _crease_cut(m, adj, ang, zidx, seed, 0.88, 0.10,
                               decay_d=d_can[zidx], tau=0.06)
            # roof skin can never be glass — but "roof" is up-facing AND at
            # the top of the car; a raked windscreen centre is up-facing too
            # and must stay eligible (head-on render caught it painted body)
            is_g &= ~((n_up[zidx] > 0.85) & (fc[zidx, 2] > 0.90))
            flab[zidx] = np.where(is_g, C, B)

        # LAMPS: same recipe in the nose/tail bands
        lam = pc_pts[pc_lab_names == "lamp"]
        if len(lam):
            d_l = cKDTree(lam).query(fc, workers=4)[0]
            zone = ((fc[:, 0] > 0.80) | (fc[:, 0] < 0.20)) \
                   & (fc[:, 2] > 0.25) & (fc[:, 2] < 0.80) & np.isin(flab, [B, L])
            zidx = np.where(zone)[0]
            if len(zidx):
                seed = flab[zidx] == L
                is_l = _crease_cut(m, adj, ang, zidx, seed, 0.85, 0.08,
                                   decay_d=d_l[zidx], tau=0.04)
                flab[zidx] = np.where(is_l, L, B)

    # INTERIOR must be invisible from outside (Hunyuan shells usually have
    # no interior at all — every "interior" patch is exterior bleed)
    comp, cnt = _patches(flab, adj, n, I)
    rng = np.random.RandomState(0)
    for cid, c in cnt.items():
        faces = np.where(comp == cid)[0]
        pick = faces if len(faces) <= 40 else rng.choice(faces, 40, replace=False)
        origins = m.triangles_center[pick] + m.face_normals[pick] * 1e-3
        if 1 - m.ray.intersects_any(origins, m.face_normals[pick]).mean() > 0.5:
            flab[faces] = B

    # WHEELS live inside one of four cylinders defined by the 4 big patches
    comp, cnt = _patches(flab, adj, n, W)
    big = [cid for cid, c in sorted(cnt.items(), key=lambda kv: -kv[1])[:4]]
    keep = np.zeros(n, bool)
    for cid in big:
        f = np.where(comp == cid)[0]
        c = fc[f].mean(axis=0)
        r = np.linalg.norm(fc[f][:, [0, 2]] - c[[0, 2]], axis=1).max()
        d = np.linalg.norm(fc[:, [0, 2]] - c[[0, 2]], axis=1)
        keep |= (d < r * 1.02) & (np.abs(fc[:, 1] - c[1]) < 0.17)
    flab[(flab == W) & ~keep] = B

    # arch boundary: the arch lip is a strong crease — a per-cylinder cut
    # snaps the tyre/body boundary onto it instead of leaving ragged spill
    if maxflow is not None:
        for cid in big:
            f = np.where(comp == cid)[0]
            c = fc[f].mean(axis=0)
            r = np.linalg.norm(fc[f][:, [0, 2]] - c[[0, 2]], axis=1).max()
            d = np.linalg.norm(fc[:, [0, 2]] - c[[0, 2]], axis=1)
            zone = (d < r * 1.35) & (np.abs(fc[:, 1] - c[1]) < 0.20) \
                   & np.isin(flab, [B, W])
            zidx = np.where(zone)[0]
            if len(zidx) < 50:
                continue
            seed = flab[zidx] == W
            is_w = _crease_cut(m, adj, ang, zidx, seed, 0.85, 0.10, lam=4.0)
            flab[zidx] = np.where(is_w, W, B)

    # LAMPS: trim baggy patches to their corner, mirror one-sided lamps —
    # a single grey lamp is the per-side defect class the audit hunts for
    tree = cKDTree(fc)
    comp, cnt = _patches(flab, adj, n, L)
    for cid, c in cnt.items():
        f = np.where(comp == cid)[0]
        wlo, whi = fc[f, 1].min(), fc[f, 1].max()
        if whi - wlo > 0.20:
            corner = wlo if (0.5 - wlo) > (whi - 0.5) else whi
            flab[f[np.abs(fc[f, 1] - corner) > 0.16]] = B
            f = f[np.abs(fc[f, 1] - corner) <= 0.16]
        mir = fc[f].copy()
        mir[:, 1] = 1 - mir[:, 1]
        d, nnf = tree.query(mir, workers=4)
        tgt = nnf[d < 0.02]
        if len(tgt) and (flab[tgt] == L).mean() < 0.5:
            flab[tgt] = L

    # BODY islands fully enclosed by glass are absurd — absorb whatever size
    comp, cnt = _patches(flab, adj, n, B)
    for cid, c in cnt.items():
        faces = np.where(comp == cid)[0]
        fs = set(faces)
        border = {flab[b] if a in fs else flab[a]
                  for a, b in adj if (a in fs) != (b in fs)}
        if border == {C}:
            flab[faces] = C
    return flab


def clamp_spikes(m, hy, thresh=1.015):
    """Flatten antenna-spike artefacts: geometry above the real roofline
    (measured: roof crown tops at ~1.012, spikes at 1.03-1.06) is clamped
    down. No topology change, so face labels stay valid."""
    above = hy[:, 2] > thresh
    if not above.any():
        return m
    lo = np.percentile(m.vertices, 2, axis=0)
    hi = np.percentile(m.vertices, 98, axis=0)
    v = m.vertices.copy()
    v[above, 1] = lo[1] + thresh * (hi[1] - lo[1])
    m.vertices = v
    return m


def transfer(parts_glb, mesh_glb, out_glb, report=None):
    pc_pts, pc_lab = labeled_points(parts_glb)
    tree = cKDTree(pc_pts)

    m = trimesh.load(mesh_glb, force="mesh")
    axes, lo, ext = _norm_frame(m.vertices)
    base = (m.vertices[:, axes] - lo) / ext

    # orientation: both cars came from the same image, but the generators may
    # disagree on which end of an axis is the nose — try flips, keep best fit
    best = None
    for fl in (False, True):
        for fw in (False, True):
            p = base.copy()
            if fl:
                p[:, 0] = 1 - p[:, 0]
            if fw:
                p[:, 1] = 1 - p[:, 1]
            sam = p[np.random.RandomState(1).choice(len(p), min(20000, len(p)), replace=False)]
            score = tree.query(sam, workers=4)[0].mean()
            if best is None or score < best[0]:
                best = (score, p)
    fit, hy = best
    print(f"alignment mean NN distance: {fit:.4f}"
          + (" — POOR FIT, labels will be wrong" if fit > 0.05 else ""))

    # k-NN weighted vote per vertex, then face majority
    d, nn = tree.query(hy, k=15, workers=4)
    votes = np.zeros((len(hy), len(LABS)))
    w = 1.0 / np.maximum(d, 1e-6)
    for j in range(nn.shape[1]):
        np.add.at(votes, (np.arange(len(hy)), pc_lab[nn[:, j]]), w[:, j])
    vlab = votes.argmax(1)
    flab = np.array([Counter(vlab[f]).most_common(1)[0][0] for f in m.faces])

    fc = hy[m.faces].mean(axis=1)
    B, C, W, I, L = (LABS.index(k) for k in ("body", "canopy", "wheel", "interior", "lamp"))
    flab[(flab == C) & (fc[:, 2] < 0.40)] = B
    flab[(flab == W) & (fc[:, 2] > 0.55)] = B
    flab[(flab == L) & ~((fc[:, 0] > 0.78) | (fc[:, 0] < 0.22))] = B
    flab[(flab == I) & (fc[:, 2] > 0.80)] = B
    flab[(flab == I) & (np.abs(fc[:, 1] - 0.5) > 0.38)] = B

    # smoothing
    adj = m.face_adjacency
    neigh = [[] for _ in range(len(m.faces))]
    for a, b in adj:
        neigh[a].append(b)
        neigh[b].append(a)
    for _ in range(25):
        new = flab.copy()
        for i in range(len(flab)):
            cnt = Counter(flab[j] for j in neigh[i])
            cnt[flab[i]] += 1
            new[i] = cnt.most_common(1)[0][0]
        if int(np.sum(new != flab)) < 50:
            flab = new
            break
        flab = new

    # island absorption
    n = len(m.faces)
    for target in range(len(LABS)):
        mask = flab == target
        same = mask[adj[:, 0]] & mask[adj[:, 1]]
        g = sp.csr_matrix((np.ones(same.sum()), (adj[same, 0], adj[same, 1])), shape=(n, n))
        _, comp = sp.csgraph.connected_components(g + g.T, directed=False)
        comp[~mask] = -1
        for cid, cnt in Counter(comp[mask]).items():
            if cnt > 4000:
                continue
            faces = np.where(comp == cid)[0]
            fs = set(faces)
            border = {flab[b] if a in fs else flab[a]
                      for a, b in adj if (a in fs) != (b in fs)}
            border.discard(target)
            if len(border) == 1:
                flab[faces] = border.pop()

    # refinement passes (graph cut, visibility, cylinders, mirroring, islands)
    flab = refine(m, flab, hy, pc_pts, np.array(LABS)[pc_lab])
    m = clamp_spikes(m, hy)

    # canopy -> roof/glass by normal (up axis is glTF Y on the raw mesh)
    n_up = np.abs(m.face_normals[:, 1])
    out_lab = np.array(["body", "glass", "wheel", "interior", "lamp"])[flab]
    fcu = hy[m.faces].mean(axis=1)[:, 2]
    roofish = (n_up > ROOF_NORMAL_UP) & (fcu > 0.90)
    out_lab[(flab == C) & roofish] = "body"
    out_lab[(flab == C) & ~roofish] = "glass"

    share = {k: round(100 * float(np.mean(out_lab == k)), 1)
             for k in ("body", "glass", "wheel", "interior", "lamp")}
    print("face share:", share)
    if share["glass"] < 2.0:
        sys.exit(f"REFUSING TO WRITE: glass is {share['glass']}% of faces — "
                 "the transfer did not find the glazing. Same guard, same "
                 "reason as partcrafter_materials: do not relax it.")

    scene = trimesh.Scene()
    for lab in ("body", "glass", "wheel", "interior", "lamp"):
        mask = out_lab == lab
        if not mask.any():
            continue
        sub = m.submesh([np.where(mask)[0]], append=True)
        sub.visual = trimesh.visual.TextureVisuals(material=MATS[lab])
        scene.add_geometry(sub, node_name=lab, geom_name=lab)
    scene.export(out_glb)
    print(f"WROTE {out_glb}")
    if report:
        json.dump({"parts": parts_glb, "mesh": mesh_glb, "out": out_glb,
                   "alignment_nn": fit, "share": share}, open(report, "w"), indent=1)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--parts", required=True, help="PartCrafter object.glb (all parts)")
    ap.add_argument("--mesh", required=True, help="target mesh GLB (e.g. Hunyuan shape)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--report")
    a = ap.parse_args()
    transfer(a.parts, a.mesh, a.out, a.report)
