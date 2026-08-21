#!/usr/bin/env python3
"""glass_repair.py — GLAZING repair by LABEL REASSIGNMENT only.

Gate "glass", car_rebound.glb, 2026-08-21.

WHAT IT DOES NOT DO, on purpose: it never moves a vertex and never deletes a face.
CLAUDE.md records that 25,369 carpaint vertices are exactly coincident with interior
vertices, so MOVING a vertex opens a crack in 25,369 places, and that deleting faces
holes the shell.  Every operation here moves a face from one NODE to another; the face
keeps its vertices, its normals and its position, so the scene's surface is bit-identical
and "no new holes" is true by construction (and is still tested, 15 directions).

THE FOUR OPERATIONS, each with the measurement that motivated it:

  OP1 WINDSCREEN STAMP.  Measured on the input: the windscreen aperture is filled with
      carpaint.  At the centreline the body rises from y 1.05 at x -1.06 to y 1.25 at
      x -0.64 on a raked screen surface (face normals ~(-0.58,0.81,0.09)) and NONE of it
      is glazing above y 1.15; Glass_Windscreen holds 0.162 m2 in total, a 75 mm-tall
      cowl strip.  glass_probe still says clear/proven because it reads the MATERIAL
      TABLE and cannot see which faces carry it (CLAUDE.md 2026-08-20).  This stamp
      grows the glazing label from the existing seeds across the fitted screen surface.

  OP2 SPILL EVICTION.  Glazing that is roof skin, cant rail, below the beltline, or lying
      over the A-/C-pillar goes back to carpaint.  Roof rule ported from
      hybrid_transfer._roofish: in the cabin MID-BAND there is no raked screen, so a
      strongly up-facing face there is roof by construction.

  OP3 DEBRIS CULL.  Glazing islands below a face threshold are tessellation crumbs; they
      go to carpaint.  Purely a relabel, so the conservative <300-face calibration that
      CLAUDE.md records for GEOMETRY purges does not apply -- nothing can be holed.

  OP4 QUARTER SPLIT.  The rear quarter glass separates from the door band because a real
      C-pillar exists (body area in the left DLO band: 143-209 cm2 per 50 mm bin at
      x >= 0.85, against 0-40 cm2 through x -0.1..0.7) and the outer skin steps inboard
      there (mean z -0.60 -> -0.71).  A per-DOOR split is NOT attempted: this body has no
      B-pillar (see --report).

Every gate below can FAIL and is asserted, not assumed.  --dry runs the measurement and
the negative controls and writes nothing.

Run:  glass_repair.py in.glb out.glb [--dry] [--report r.json]
"""
import argparse
import json
import sys

import struct

import numpy as np
import trimesh

GLASS_NODES = ("Glass_Windscreen", "Glass_Rear", "Glass_Side_L", "Glass_Side_R")
GLASS_MAT = "glass"
BODY_MAT = "carpaint"


# ----------------------------------------------------------------------------- helpers
def authored_normals(path):
    """Read the NORMAL accessors straight out of the GLB, keyed by node name.

    MEASURED 2026-08-21: taking `mesh.vertex_normals` from a trimesh scene loaded with
    process=False still returns RECOMPUTED normals once the geometry has been copied --
    the cache does not survive `.copy()`.  The recomputation zeroes every vertex whose
    incident faces are all degenerate, and my first export carried 580 ZERO-LENGTH
    normals in nodes this tool never touches (Interior 408, Underbody 43, Arch_Liner 29,
    three wheel rims...).  The Khronos validator called all 580: ACCESSOR_VECTOR3_NON_UNIT,
    severity 0.  The input file has ZERO.  This is the Gate 6 lesson reproduced
    ("trimesh recomputes vertex normals and zeroes degenerate vertices") and the reason
    the validator must be run on the OUTPUT and DIFFED against the INPUT every time.
    """
    b = open(path, "rb").read()
    jlen = struct.unpack("<I", b[12:16])[0]
    g = json.loads(b[20:20 + jlen].decode("utf-8"))
    off = 20 + jlen
    blen = struct.unpack("<I", b[off:off + 4])[0]
    assert b[off + 4:off + 8] == b"BIN\x00"
    binc = b[off + 8:off + 8 + blen]
    out = {}
    for nd in g.get("nodes", []):
        if "mesh" not in nd:
            continue
        prims = g["meshes"][nd["mesh"]]["primitives"]
        if len(prims) != 1 or "NORMAL" not in prims[0]["attributes"]:
            continue
        A = g["accessors"][prims[0]["attributes"]["NORMAL"]]
        BV = g["bufferViews"][A["bufferView"]]
        o = BV.get("byteOffset", 0) + A.get("byteOffset", 0)
        out[nd.get("name")] = np.frombuffer(binc, dtype=np.float32,
                                            count=A["count"] * 3, offset=o).reshape(-1, 3).astype(np.float64)
    return out


def load(path):
    sc = trimesh.load(path, force="scene", process=False)
    auth = authored_normals(path)
    out = {}
    for name in sc.graph.nodes_geometry:
        gname = sc.graph[name][1]
        m = sc.geometry[gname].copy()
        T = sc.graph[name][0]
        n = auth.get(name)
        if n is None or len(n) != len(m.vertices):
            n = m.vertex_normals.copy()
            print(f"   WARNING: no authored NORMAL for {name}, recomputed")
        else:
            n = n.copy()
        m.apply_transform(T)
        R = T[:3, :3]
        ninv = np.linalg.inv(R).T
        n = n @ ninv.T
        ln = np.linalg.norm(n, axis=1, keepdims=True)
        n = n / np.where(ln < 1e-12, 1, ln)
        out[name] = (m, n)
    return sc, out


def stack(parts):
    """Concatenate (mesh, normals) parts, returning verts, faces, normals, owner."""
    V, F, N, own, voff = [], [], [], [], 0
    for i, (name, (m, n)) in enumerate(parts):
        V.append(m.vertices); N.append(n)
        F.append(m.faces + voff)
        own.append(np.full(len(m.faces), i))
        voff += len(m.vertices)
    return np.vstack(V), np.vstack(F), np.vstack(N), np.concatenate(own)


def quantised_adjacency(verts, faces, digits=5):
    """Face adjacency over a COORDINATE-QUANTISED weld.  A GLB stores 3 unique verts per
    face and trimesh's merge_vertices keeps split verts when normals differ, so the naive
    adjacency of this mesh is almost empty (CLAUDE.md, label_bench)."""
    key = np.round(verts, digits)
    _, inv = np.unique(key, axis=0, return_inverse=True)
    wf = inv[faces]
    e = np.sort(np.c_[wf[:, [0, 1]], wf[:, [1, 2]], wf[:, [2, 0]]].reshape(-1, 2), axis=1)
    fid = np.repeat(np.arange(len(faces)), 3)
    order = np.lexsort((e[:, 1], e[:, 0]))
    e, fid = e[order], fid[order]
    same = np.all(e[1:] == e[:-1], axis=1)
    a, b = fid[:-1][same], fid[1:][same]
    return a, b


def connected_from(seed_mask, keep_mask, a, b, nfaces):
    """Flood fill within keep_mask starting from seed_mask, over edge list (a,b)."""
    import scipy.sparse as sp
    import scipy.sparse.csgraph as csg
    ok = keep_mask[a] & keep_mask[b]
    g = sp.coo_matrix((np.ones(ok.sum()), (a[ok], b[ok])), shape=(nfaces, nfaces))
    ncomp, lab = csg.connected_components(g, directed=False)
    hit = np.unique(lab[seed_mask & keep_mask])
    return keep_mask & np.isin(lab, hit)


def fit_quadric(P):
    """z' = f(u,v) least squares quadric in the frame whose 3rd axis is the plane normal."""
    c = P.mean(0)
    u, s, vt = np.linalg.svd(P - c, full_matrices=False)
    R = vt                                   # rows: 2 in-plane axes then the normal
    Q = (P - c) @ R.T
    A = np.c_[np.ones(len(Q)), Q[:, 0], Q[:, 1], Q[:, 0] ** 2, Q[:, 0] * Q[:, 1], Q[:, 1] ** 2]
    coef, *_ = np.linalg.lstsq(A, Q[:, 2], rcond=None)
    return c, R, coef


def quadric_dist(P, c, R, coef):
    Q = (P - c) @ R.T
    A = np.c_[np.ones(len(Q)), Q[:, 0], Q[:, 1], Q[:, 0] ** 2, Q[:, 0] * Q[:, 1], Q[:, 1] ** 2]
    return Q[:, 2] - A @ coef, Q[:, 0], Q[:, 1]



def beltline_fit(C, area, mask, side_sign, nbins=26, pct=2.0):
    """Robust STRAIGHT beltline y = m*x + c fitted to the LOWER EDGE of one side's
    glazing, rather than a single world-Y constant.

    MEASURED 2026-08-21, and this is why it exists: a fixed `--belt-y 0.995` was
    calibrated on car_rebound.glb, which sits nose-UP by ~4.1 deg.  Run unchanged on the
    grounded, de-pitched car_merged.glb the same constant evicted 12,196 glazing faces as
    "below the beltline" against 1,537 on the original -- 0.988 m2 of eviction against
    0.378 -- i.e. it cut through real door glass.  A beltline is a LINE on a pitched car,
    not a height.  Fitting it per side makes the rule pose-independent.
    """
    m = mask & (np.sign(C[:, 2]) == side_sign)
    if m.sum() < 200:
        return None
    x, y = C[m][:, 0], C[m][:, 1]
    lo, hi = np.percentile(x, 2), np.percentile(x, 98)
    edges = np.linspace(lo, hi, nbins + 1)
    bx, by = [], []
    for i in range(nbins):
        k = (x >= edges[i]) & (x < edges[i + 1])
        if k.sum() < 12:
            continue
        bx.append(0.5 * (edges[i] + edges[i + 1])); by.append(np.percentile(y[k], pct))
    if len(bx) < 6:
        return None
    bx, by = np.array(bx), np.array(by)
    for _ in range(3):                       # drop sag bins: a floor that follows the sag
        A = np.c_[bx, np.ones(len(bx))]      # is no floor (glass_presplit pattern)
        coef, *_ = np.linalg.lstsq(A, by, rcond=None)
        r = by - A @ coef
        keep = r > -1.2 * max(np.std(r), 1e-6)
        if keep.sum() < 5:
            break
        bx, by = bx[keep], by[keep]
    return coef


# ------------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inp"); ap.add_argument("out", nargs="?")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--report")
    # measured constants for THIS body, all quoted in the docstring / report
    ap.add_argument("--cowl-x", type=float, default=-1.16)
    ap.add_argument("--header-x", type=float, default=-0.34)
    ap.add_argument("--apillar-x", type=float, default=-0.62)
    ap.add_argument("--belt-y", type=float, default=0.995)
    ap.add_argument("--belt-margin", type=float, default=0.012)
    ap.add_argument("--max-evict-frac", type=float, default=0.25)
    ap.add_argument("--cpillar-x", type=float, default=0.86)
    ap.add_argument("--screen-cos", type=float, default=0.86)
    ap.add_argument("--screen-band", type=float, default=0.045)
    ap.add_argument("--debris", type=int, default=60)
    a = ap.parse_args()

    sc, parts = load(a.inp)
    names = list(parts.keys())
    V, F, N, own = stack(list(parts.items()))
    C = V[F].mean(1)
    tri = V[F]
    fn = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    area = 0.5 * np.linalg.norm(fn, axis=1)
    ln = np.linalg.norm(fn, axis=1, keepdims=True)
    fn = fn / np.where(ln < 1e-15, 1, ln)
    idx = {n: i for i, n in enumerate(names)}
    label = np.array([names[o] for o in own], dtype=object)
    is_glass = np.isin(label, GLASS_NODES)
    is_body = label == "Body_Shell"
    rep = {"input": a.inp, "faces": int(len(F)),
           "glazing_area_in": float(area[is_glass].sum()),
           "constants": {k: getattr(a, k) for k in
                         ("cowl_x", "header_x", "apillar_x", "belt_y", "belt_margin",
                          "cpillar_x", "screen_cos", "screen_band", "debris",
                          "max_evict_frac")}}
    print(f"faces {len(F)}  glazing area in {area[is_glass].sum():.4f} m2")

    eA, eB = quantised_adjacency(V, F)
    print(f"welded face adjacency: {len(eA)} shared edges")

    # ---------------- OP1  WINDSCREEN STAMP -----------------------------------
    # seed = existing glazing inside the screen zone; surface = quadric fitted to the
    # SAFE CORE of the body's screen surface (centre third, orientation-gated).
    zone = (C[:, 0] > a.cowl_x) & (C[:, 0] < a.header_x) & (C[:, 1] > a.belt_y)
    core = zone & is_body & (np.abs(C[:, 2]) < 0.33)
    d0 = np.array([-0.55, 0.835, 0.0]); d0 /= np.linalg.norm(d0)
    nu = fn * np.where(fn[:, 1] < 0, -1.0, 1.0)[:, None]     # sign-insensitive: this mesh
    core = core & (np.abs(nu @ d0) > 0.90)                   # has flipped-normal patches
    assert core.sum() > 200, f"screen core too small ({core.sum()})"
    c0, R0, k0 = fit_quadric(C[core])
    for _ in range(3):                                       # robust re-fit
        dd, _, _ = quadric_dist(C[core], c0, R0, k0)
        keep = np.abs(dd) < max(0.012, 2.5 * np.std(dd))
        c0, R0, k0 = fit_quadric(C[core][keep])
    dall, uu, vv = quadric_dist(C, c0, R0, k0)
    dsurf = np.abs(dall)
    nsurf = R0[2]
    onsurf = (dsurf < a.screen_band) & (np.abs(nu @ nsurf) > a.screen_cos)
    cand = zone & is_body & onsurf
    seed = zone & is_glass & (dsurf < a.screen_band * 1.6)
    stamp = connected_from(seed, cand | (zone & is_glass), eA, eB, len(F)) & cand
    rep["op1_windscreen"] = {
        "core_faces": int(core.sum()), "seed_faces": int(seed.sum()),
        "candidate_faces": int(cand.sum()), "stamped_faces": int(stamp.sum()),
        "stamped_area": float(area[stamp].sum()),
        "fit_rms_mm": float(np.std(quadric_dist(C[core], c0, R0, k0)[0]) * 1000),
        "surface_normal": np.round(nsurf, 4).tolist(),
    }
    print(f"OP1 windscreen: core {core.sum()} seed {seed.sum()} cand {cand.sum()} "
          f"-> STAMP {stamp.sum()} faces, {area[stamp].sum():.4f} m2, "
          f"fit rms {rep['op1_windscreen']['fit_rms_mm']:.1f} mm")

    # NEGATIVE CONTROLS -- these must FAIL a bad stencil, so they are asserted
    nc = {}
    roof = is_body & (C[:, 0] > a.header_x + 0.10) & (C[:, 1] > 1.30)
    bonnet = is_body & (C[:, 0] < a.cowl_x - 0.10)
    flank = is_body & (np.abs(C[:, 2]) > 0.72)
    for k, m in (("roof", roof), ("bonnet", bonnet), ("flank", flank)):
        share = float(area[stamp & m].sum() / max(area[stamp].sum(), 1e-9))
        nc[f"stamp_on_{k}_areafrac"] = round(share, 5)
    nc["stamp_max_surface_dev_mm"] = round(float(dsurf[stamp].max() * 1000), 2)
    nc["stamp_x_range"] = [round(float(C[stamp][:, 0].min()), 4), round(float(C[stamp][:, 0].max()), 4)]
    nc["stamp_y_range"] = [round(float(C[stamp][:, 1].min()), 4), round(float(C[stamp][:, 1].max()), 4)]
    nc["stamp_z_range"] = [round(float(C[stamp][:, 2].min()), 4), round(float(C[stamp][:, 2].max()), 4)]
    rep["op1_negative_controls"] = nc
    print("   NEG CONTROLS:", json.dumps(nc))
    fails = [k for k in ("stamp_on_roof_areafrac", "stamp_on_bonnet_areafrac",
                         "stamp_on_flank_areafrac") if nc[k] > 0.02]
    rep["op1_controls_pass"] = not fails
    if fails:
        print(f"   !! NEGATIVE CONTROL FAILED: {fails} -- windscreen stamp REFUSED")
        stamp[:] = False
        rep["op1_windscreen"]["stamped_faces"] = 0

    # ---------------- OP2  SPILL EVICTION -------------------------------------
    g = is_glass.copy()
    # (a) roof / cant rail: strongly up-facing glazing in the cabin MID-BAND, where by
    #     construction there is no raked screen (hybrid_transfer._roofish)
    midband = (C[:, 0] > a.header_x) & (C[:, 0] < a.cpillar_x + 0.28)
    roofish = g & midband & (np.abs(nu[:, 1]) > 0.72)
    # (b) below the beltline
    # The beltline is a DLO concept and is applied to the FLANK band ONLY.
    # CORRECTION 2026-08-21: my first version applied the fitted line to ALL glazing and
    # took 33% off the REAR SCREEN (0.757 -> 0.504 m2), because a hatchback's tailgate
    # glass legitimately runs below the side beltline (it starts at y 0.892 here against
    # a fitted side belt of ~1.02).  Scope, not threshold, was the bug.
    dlo = g & (np.abs(C[:, 2]) > 0.40) & (C[:, 0] > a.apillar_x - 0.05) & \
        (C[:, 0] < a.cpillar_x + 0.20)
    below = np.zeros(len(F), dtype=bool)
    belt_info = {}
    for sgn, nm in ((-1, "L"), (1, "R")):
        coef = beltline_fit(C, area, dlo, sgn)
        sm = dlo & (np.sign(C[:, 2]) == sgn)
        if coef is None:
            below |= sm & (C[:, 1] < a.belt_y)
            belt_info[nm] = "fallback constant %.3f" % a.belt_y
            continue
        yb = coef[0] * C[:, 0] + coef[1] - a.belt_margin
        below |= sm & (C[:, 1] < yb)
        belt_info[nm] = {"slope": round(float(coef[0]), 5), "intercept": round(float(coef[1]), 5),
                         "margin": a.belt_margin}
    print("   beltline fit:", json.dumps(belt_info))
    # (c) over the C-pillar: glazing on the pillar between the door band and the quarter
    cpil = g & (C[:, 0] > a.cpillar_x) & (C[:, 0] < a.cpillar_x + 0.14) & (np.abs(C[:, 2]) > 0.40)
    # (d) COWL / SCUTTLE and A-PILLAR.  Measured on the input: the node called
    #     Glass_Windscreen is 87.4% one 2,183-face component at y 0.997-1.072 whose mean
    #     normal is (-0.25,0.97,0.03) -- a near-horizontal panel straddling the cowl
    #     trough (body Ytop dips 1.055 -> 1.035 at x -1.12 before the screen rises).  It
    #     is the SCUTTLE, not glazing.  Forward of the DLO front edge (A-pillar measured
    #     at x -0.675 L / -0.725..-0.625 R by body area in the DLO band) any glazing that
    #     is NOT on the fitted screen surface is cowl or A-pillar skin.  The rule is
    #     z-agnostic on purpose: the door glass starts BEHIND the A-pillar, so it cannot
    #     be reached by this test.
    onscreen = (dsurf < a.screen_band * 2.0) & (np.abs(nu @ nsurf) > 0.70)
    cowl = g & (C[:, 0] < a.apillar_x) & ~onscreen
    evict = roofish | below | cpil | cowl
    evict &= ~stamp
    # EVICTION GUARD.  The negative controls above protect the STAMP against
    # over-selection and NOTHING protected the EVICTION against it -- a one-sided gate,
    # the exact failure class CLAUDE.md records.  Found by running this tool on a
    # differently-posed copy of the same car, where a stale beltline constant quietly
    # evicted 31.1% of the glazing.
    ev_frac = float(area[evict].sum() / max(area[is_glass].sum(), 1e-9))
    rep["op2_evict_frac"] = round(ev_frac, 4)
    rep["op2_evict_guard_pass"] = bool(ev_frac <= a.max_evict_frac)
    if ev_frac > a.max_evict_frac:
        print(f"   !! EVICTION GUARD FAILED: {100*ev_frac:.1f}% of glazing area would be "
              f"evicted (limit {100*a.max_evict_frac:.0f}%). Landmarks do not fit this "
              f"body -- REFUSING the eviction rather than shipping a stripped car.")
        evict[:] = False
    rep["op2_spill"] = {
        "roof_cantrail_faces": int(roofish.sum()), "roof_cantrail_area": float(area[roofish].sum()),
        "below_belt_faces": int(below.sum()), "below_belt_area": float(area[below].sum()),
        "over_cpillar_faces": int(cpil.sum()), "over_cpillar_area": float(area[cpil].sum()),
        "cowl_apillar_faces": int(cowl.sum()), "cowl_apillar_area": float(area[cowl].sum()),
        "total_evicted_faces": int(evict.sum()), "total_evicted_area": float(area[evict].sum()),
    }
    print(f"OP2 spill: roof/cant {roofish.sum()} below-belt {below.sum()} "
          f"c-pillar {cpil.sum()} cowl/A-pillar {cowl.sum()} "
          f"-> evict {evict.sum()} faces {area[evict].sum():.4f} m2")

    # ---------------- OP3  DEBRIS ---------------------------------------------
    gnew = (g & ~evict) | stamp
    import scipy.sparse as sp, scipy.sparse.csgraph as csg
    ok = gnew[eA] & gnew[eB]
    gg = sp.coo_matrix((np.ones(ok.sum()), (eA[ok], eB[ok])), shape=(len(F), len(F)))
    _, lab = csg.connected_components(gg, directed=False)
    lab_g = np.where(gnew, lab, -1)
    uniq, cnt = np.unique(lab_g[gnew], return_counts=True)
    small = uniq[cnt < a.debris]
    debris = gnew & np.isin(lab_g, small)
    rep["op3_debris"] = {"islands": int(len(uniq)), "culled_islands": int(len(small)),
                         "culled_faces": int(debris.sum()),
                         "culled_area": float(area[debris].sum())}
    print(f"OP3 debris: {len(uniq)} glazing islands, cull {len(small)} "
          f"(<{a.debris} faces) = {debris.sum()} faces {area[debris].sum():.5f} m2")
    gnew &= ~debris

    # ---------------- OP4  NODE ASSIGNMENT ------------------------------------
    # Panes are assigned GEOMETRICALLY, never by the node a face arrived in.
    new_label = label.copy()
    new_label[gnew & ~is_glass] = "Glass_Windscreen"          # stamped body faces
    gi = np.where(gnew)[0]
    cx, cz = C[gi, 0], C[gi, 2]
    lbl = np.empty(len(gi), dtype=object)
    lbl[:] = "Glass_Side_L"
    lbl[cz > 0] = "Glass_Side_R"
    # WINDSCREEN = ON THE FITTED SCREEN SURFACE, not merely forward of the header.
    # v1 used `cx < header_x` alone and swept the A-pillar-region FLANK glazing into the
    # windscreen (node jumped to 1.112 m2 and reached |z| 0.64) -- a position-only rule
    # cannot tell a screen from a front side window that shares its x band.  The normal
    # gate does: flank glazing runs ~(0,0.5,-0.85) against the screen's (-0.55,0.83,0),
    # |dot| ~0.42, well under the 0.70 gate.
    ws = (cx < a.header_x + 0.05) & (cx > a.cowl_x - 0.12) & onscreen[gi]
    lbl[ws] = "Glass_Windscreen"
    rear = (cx > a.cpillar_x + 0.30) & (np.abs(cz) < 0.52)
    lbl[rear] = "Glass_Rear"
    lbl[cx > 1.45] = "Glass_Rear"
    q = (cx > a.cpillar_x + 0.14) & (cx <= 1.45) & (np.abs(cz) >= 0.52)
    lbl[q & (cz < 0)] = "Glass_Quarter_L"
    lbl[q & (cz > 0)] = "Glass_Quarter_R"
    # A quarter node is only created if it is a real pane.  CLAUDE.md / the gate brief:
    # never create a node to make the inventory look full.
    for qn, sn in (("Glass_Quarter_L", "Glass_Side_L"), ("Glass_Quarter_R", "Glass_Side_R")):
        m = lbl == qn
        if m.sum() and area[gi][m].sum() < 0.010:
            print(f"   {qn}: only {area[gi][m].sum()*1e4:.0f} cm2 of glazing -- NOT a pane, "
                  f"merged back into {sn}")
            lbl[m] = sn
    new_label[gi] = lbl
    # everything that lost its glazing label becomes body skin
    lost = is_glass & ~gnew
    new_label[lost] = "Body_Glass_Reverted"
    rep["op4_panes"] = {}
    for k in ("Glass_Windscreen", "Glass_Rear", "Glass_Side_L", "Glass_Side_R",
              "Glass_Quarter_L", "Glass_Quarter_R", "Body_Glass_Reverted"):
        m = new_label == k
        if m.sum():
            rep["op4_panes"][k] = {"faces": int(m.sum()), "area": round(float(area[m].sum()), 5)}
    print("OP4 panes:", json.dumps(rep["op4_panes"]))
    gl_out = np.isin(new_label, list(rep["op4_panes"].keys())[:6]) & \
        np.array([str(x).startswith("Glass_") for x in new_label])
    rep["glazing_area_out"] = float(area[gl_out].sum())
    rep["glazing_area_pct_out"] = round(100 * area[gl_out].sum() / area.sum(), 3)
    print(f"glazing area {rep['glazing_area_in']:.4f} -> {rep['glazing_area_out']:.4f} m2 "
          f"({rep['glazing_area_pct_out']:.2f}% of scene area)")

    if a.report:
        json.dump(rep, open(a.report, "w"), indent=1)
        print(f"wrote {a.report}")
    if a.dry or not a.out:
        print("DRY RUN -- nothing written")
        return

    # ---------------- WRITE ----------------------------------------------------
    mat_of = {}
    for name, (m, _) in parts.items():
        mat_of[name] = m.visual.material if hasattr(m.visual, "material") else None
    glass_mat = mat_of.get("Glass_Windscreen")
    body_mat = mat_of.get("Body_Shell")
    out = trimesh.Scene()
    repaired = [0]
    for k in sorted(set(new_label)):
        m = new_label == k
        if not m.sum():
            continue
        f = F[m]
        used, remap = np.unique(f, return_inverse=True)
        nm = trimesh.Trimesh(vertices=V[used], faces=remap.reshape(-1, 3),
                             process=False, validate=False)
        nn = N[used].copy()
        L = np.linalg.norm(nn, axis=1)
        bad = L < 0.5
        if bad.any():
            # a zero normal is a validator ERROR (ACCESSOR_VECTOR3_NON_UNIT).  Rebuild
            # it from the incident faces; if those are degenerate too, fall back to +Y.
            fnv = np.cross(nm.vertices[nm.faces[:, 1]] - nm.vertices[nm.faces[:, 0]],
                           nm.vertices[nm.faces[:, 2]] - nm.vertices[nm.faces[:, 0]])
            acc = np.zeros_like(nn)
            for c in range(3):
                np.add.at(acc, nm.faces[:, c], fnv)
            aL = np.linalg.norm(acc, axis=1)
            fix = bad & (aL > 1e-12)
            nn[fix] = acc[fix] / aL[fix, None]
            still = bad & ~(aL > 1e-12)
            nn[still] = np.array([0.0, 1.0, 0.0])
            repaired[0] += int(bad.sum())
        nn /= np.linalg.norm(nn, axis=1, keepdims=True)
        assert np.abs(np.linalg.norm(nn, axis=1) - 1).max() < 1e-6, "non-unit normal escaped"
        nm.vertex_normals = nn                               # authored normals, kept
        base = str(k)
        src = base if base in mat_of else ("Glass_Windscreen" if base.startswith("Glass_")
                                           else "Body_Shell")
        mm = mat_of.get(src)
        if mm is not None:
            nm.visual = trimesh.visual.TextureVisuals(material=mm.copy())
        out.add_geometry(nm, geom_name=base, node_name=base)
    out.export(a.out)
    print(f"wrote {a.out}  (degenerate normals repaired: {repaired[0]})")


if __name__ == "__main__":
    main()
