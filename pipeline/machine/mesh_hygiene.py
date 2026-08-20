#!/usr/bin/env python3
"""mesh_hygiene.py — remove zero-area and stretched faces, and rebuild the
NORMAL attribute, without touching the shape of the surface.

This is the half of Gate 5's acceptance list that is about the MESH rather than
about the surface: "no zero-area or stretched faces", and — by way of the glTF
validator — no zero-length normals. Measured on the Golf Mk8 master, per glTF
primitive, straight out of the binary chunk:

    carpaint   242,915 faces   30 zero-length NORMAL    6 zero-area   7 aspect>50
    interior   660,134 faces    0                      17 zero-area  22 aspect>50
    (Rim_Alloy, glass, Tyre_Rubber, Lamp_Lens all clean)

The 30 zero-length normals ARE the master's 30 glTF validator errors and the 17
repeated-index triangles in `interior` are its 17 reported degenerate triangles.

THREE OPERATIONS, EACH OF WHICH CANNOT CHANGE THE RENDERED SHAPE, and that
property is the reason each one was chosen over the obvious alternative:

  1. DROP ZERO-AREA FACES. A face with no area contributes no pixels, so
     removing it cannot open a hole. This is the only face removal in this file
     that is safe by construction, and it is the only unconditional one.
  2. COLLAPSE SHORT EDGES (--min-edge, default 0.20 mm). A sliver with a
     2500:1 aspect ratio is a real triangle with real area and DELETING it
     would open a real hole. Merging its two nearly-coincident corners removes
     it and moves the surface by at most --min-edge — a fifth of a millimetre,
     which is below the 2.5 mm voxel the geometry was generated on and far
     below anything the gate can see. Every face that degenerates as a result
     of the merge is then dropped by rule 1.
  3. REBUILD NORMALS from the welded topology, averaged only across edges
     softer than --smooth-deg. A zero-length normal is not repairable by
     normalising it — there is no direction in it to keep — so it must be
     recomputed from geometry.

WHAT THIS FILE IS NOT ALLOWED TO DO. The owner's gate says smooth shading and
weighted normals may SUPPORT good geometry and may not CORRECT bad geometry.
Rule 3 is therefore run for validator conformance only, and the surface claim
in the accompanying report is made from FLAT-SHADED renders, which carry no
vertex normals at all. Nothing here moves a vertex except rule 2, and rule 2 is
bounded by a stated distance.

Run:
  python3 mesh_hygiene.py <in.glb> <out.glb> [--min-edge 0.20] [--smooth-deg 35]
        [--report out.json] [--dry-run]
"""
import argparse
import json
import os
import struct
import sys

import numpy as np
import trimesh

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def face_stats(V, F):
    tri = V[F]
    cr = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    area = np.linalg.norm(cr, axis=1) * 0.5
    e = np.stack([np.linalg.norm(tri[:, 1] - tri[:, 0], axis=1),
                  np.linalg.norm(tri[:, 2] - tri[:, 1], axis=1),
                  np.linalg.norm(tri[:, 0] - tri[:, 2], axis=1)], axis=1)
    asp = e.max(1) / e.min(1).clip(1e-15)
    return area, e, asp


def summarise(V, F, tag):
    area, e, asp = face_stats(V, F)
    rep = dict(faces=int(len(F)),
               zero_area=int((area <= 1e-12).sum()),
               repeated_index=int(((F[:, 0] == F[:, 1]) | (F[:, 1] == F[:, 2]) |
                                   (F[:, 0] == F[:, 2])).sum()),
               min_area_mm2=float(area.min() * 1e6),
               aspect_p99=round(float(np.percentile(asp, 99)), 2),
               aspect_max=round(float(asp.max()), 1),
               aspect_over_50=int((asp > 50).sum()),
               min_edge_um=round(float(e.min()) * 1e6, 3))
    print(f"    {tag:8s} faces={rep['faces']:7d} zeroArea={rep['zero_area']:4d} "
          f"repIdx={rep['repeated_index']:4d} asp_p99={rep['aspect_p99']:6.2f} "
          f"asp_max={rep['aspect_max']:12.1f} asp>50={rep['aspect_over_50']:4d} "
          f"minEdge={rep['min_edge_um']:9.3f}um")
    return rep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inp")
    ap.add_argument("out")
    ap.add_argument("--min-edge", type=float, default=0.20,
                    help="millimetres; edges shorter than this are collapsed")
    ap.add_argument("--smooth-deg", type=float, default=35.0)
    ap.add_argument("--report", default=None)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    import body_surface as bs
    car = bs.Car(a.inp)
    print(f"{a.inp}: {len(car.names)} geometries, {len(car.V_all)} verts")

    rep = dict(input=os.path.basename(a.inp), min_edge_mm=a.min_edge,
               smooth_deg=a.smooth_deg, geoms={})

    # ---- 1+2: decide the vertex merge on the WELDED surface, so a collapse is
    # consistent across the label submeshes that share the edge. Deciding it
    # per-geometry would merge a vertex in carpaint and not its coincident twin
    # in interior, which is the crack this project already paid for once.
    Vw, Fw = car.Vw, car.Fw
    print("  welded surface:")
    before_w = summarise(Vw, Fw, "before")

    tol = a.min_edge / 1000.0
    # union-find over short edges
    E = np.sort(np.concatenate([Fw[:, [0, 1]], Fw[:, [1, 2]], Fw[:, [2, 0]]]),
                axis=1)
    E = np.unique(E, axis=0)
    L = np.linalg.norm(Vw[E[:, 0]] - Vw[E[:, 1]], axis=1)
    short = E[L < tol]
    parent = np.arange(len(Vw))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for u, v in short:
        ru, rv = find(u), find(v)
        if ru != rv:
            parent[max(ru, rv)] = min(ru, rv)
    root = np.array([find(i) for i in range(len(Vw))])
    nmerged = int((root != np.arange(len(Vw))).sum())
    print(f"  short edges (<{a.min_edge}mm): {len(short)}, "
          f"merging {nmerged} vertices")

    # merged vertices take the mean of their group: a collapse to one endpoint
    # would move the surface by the full edge length in one direction, the mean
    # moves it by half and keeps the patch centred.
    if nmerged:
        acc = np.zeros_like(Vw)
        cnt = np.zeros(len(Vw))
        np.add.at(acc, root, Vw)
        np.add.at(cnt, root, 1.0)
        merged_pos = acc / cnt[:, None].clip(1)
        Vw_new = merged_pos[root]
        moved = np.linalg.norm(Vw_new - Vw, axis=1)
        print(f"  merge moved surface by max {moved.max()*1000:.4f}mm "
              f"(bounded by --min-edge {a.min_edge}mm)")
        rep["merge_max_move_mm"] = round(float(moved.max()) * 1000, 5)
    else:
        Vw_new = Vw
        rep["merge_max_move_mm"] = 0.0
    rep["short_edges"] = int(len(short))
    rep["verts_merged"] = nmerged

    # ---- apply to every geometry's own arrays
    V_all_new = car.scatter(Vw_new)
    root_all = root[car.inv]                    # per original vertex -> group
    sc = car.scene
    kept_total = dropped_total = 0
    for gn, (s, e, gi, T) in car.slices.items():
        g = sc.geometry[gn]
        F = np.asarray(g.faces, dtype=np.int64)
        Vg = V_all_new[s:e]
        rg = root_all[s:e]
        area, _, asp = face_stats(Vg, F)
        bad = (area <= 1e-12) | (rg[F[:, 0]] == rg[F[:, 1]]) | \
              (rg[F[:, 1]] == rg[F[:, 2]]) | (rg[F[:, 0]] == rg[F[:, 2]])
        keep = ~bad
        before = summarise(np.asarray(g.vertices, dtype=np.float64), F,
                           gn[:8] + " in")
        if not a.dry_run:
            Ti = np.linalg.inv(T)
            g.vertices = trimesh.transform_points(Vg, Ti)
            g.faces = F[keep]
        after = summarise(Vg, F[keep], gn[:8] + " out")
        rep["geoms"][gn] = dict(before=before, after=after,
                                dropped=int(bad.sum()))
        kept_total += int(keep.sum())
        dropped_total += int(bad.sum())
    print(f"  dropped {dropped_total} faces total, kept {kept_total}")
    rep["faces_dropped"] = dropped_total

    if a.dry_run:
        print("DRY RUN — nothing written")
        return

    # ---- 3: rebuild normals on the cleaned surface
    import panel_reform as pr
    car2 = bs.Car(a.out) if False else None
    # rebuild from the cleaned geometry directly
    tmpV, tmpF, offs = [], [], {}
    off = 0
    for gn, (s, e, gi, T) in car.slices.items():
        g = sc.geometry[gn]
        Vg = trimesh.transform_points(np.asarray(g.vertices, dtype=np.float64), T)
        Fg = np.asarray(g.faces, dtype=np.int64)
        offs[gn] = (off, len(Vg))
        tmpV.append(Vg)
        tmpF.append(Fg + off)
        off += len(Vg)
    Vc = np.concatenate(tmpV)
    Fc = np.concatenate(tmpF)
    s_ = float(np.ptp(Vc, axis=0).max())
    key = np.round(Vc / (1e-6 * s_)).astype(np.int64)
    _, first2, inv2 = np.unique(key, axis=0, return_index=True,
                                return_inverse=True)
    Fw2 = inv2[Fc]
    keep2 = ((Fw2[:, 0] != Fw2[:, 1]) & (Fw2[:, 1] != Fw2[:, 2]) &
             (Fw2[:, 0] != Fw2[:, 2]))
    wm = trimesh.Trimesh(vertices=Vc[first2], faces=Fw2[keep2], process=False)
    accn, ui, ngrp = pr.smooth_normals(wm, a.smooth_deg, None, len(Vc))
    corner = Fc[keep2].ravel()
    nrm = np.zeros((len(Vc), 3))
    np.add.at(nrm, corner, accn[ui])
    ln = np.linalg.norm(nrm, axis=1, keepdims=True)
    bad = ln[:, 0] < 1e-9
    nrm = nrm / ln.clip(1e-12)
    if bad.any():
        # ORPHAN VERTICES: referenced by no surviving face, so nothing
        # accumulated into them. Filling these from the WELDED vertex normal
        # does not work and silently makes things worse -- a welded vertex with
        # no faces has a zero normal too, so the zero is copied straight back.
        # That regression took this file from the master's 30 zero-length
        # normals to 797 while printing "996 filled" and looking successful.
        # A zero-length normal is a hard glTF validator error even on a vertex
        # nothing draws, so the value must be a real unit vector: take the
        # nearest REFERENCED vertex's normal, which is already unit.
        good = ~bad
        if good.any():
            from scipy.spatial import cKDTree
            _, kk = cKDTree(Vc[good]).query(Vc[bad], k=1, workers=-1)
            nrm[bad] = nrm[good][kk]
        else:
            nrm[bad] = np.array([0.0, 1.0, 0.0])
    ln2 = np.linalg.norm(nrm, axis=1)
    still = int((np.abs(ln2 - 1.0) > 1e-4).sum())
    if still:
        raise SystemExit(f"REFUSED: {still} normals are still not unit length "
                         f"-- shipping these is the validator error this file "
                         f"exists to remove")
    rep["orphan_normals_filled"] = int(bad.sum())
    print(f"  normals: {ngrp} smoothing groups at {a.smooth_deg:.0f}deg, "
          f"{int(bad.sum())} orphan vertices filled from the nearest "
          f"referenced vertex; all {len(nrm)} normals verified unit")
    for gn, (s, n) in offs.items():
        g = sc.geometry[gn]
        Ti = np.linalg.inv(car.slices[gn][3])
        v = nrm[s:s + n] @ Ti[:3, :3].T
        g.vertex_normals = v / np.linalg.norm(v, axis=1, keepdims=True).clip(1e-12)

    sc.export(a.out, include_normals=True)

    # ---- verify the written FILE, never the in-memory scene
    with open(a.out, "rb") as fh:
        fh.seek(12)
        ln_, _ = struct.unpack("<II", fh.read(8))
        jj = json.loads(fh.read(ln_))
    miss = [m.get("name") for m in jj["meshes"]
            if any("NORMAL" not in p["attributes"] for p in m["primitives"])]
    if miss:
        raise SystemExit(f"REFUSED: NORMAL missing on {miss}")
    rep["output_bytes"] = os.path.getsize(a.out)
    print(f"wrote {a.out} ({rep['output_bytes']} bytes)")
    if a.report:
        with open(a.report, "w") as fh:
            json.dump(rep, fh, indent=1)
        print("report ->", a.report)


if __name__ == "__main__":
    main()
