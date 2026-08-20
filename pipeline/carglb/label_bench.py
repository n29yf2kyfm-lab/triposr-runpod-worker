#!/usr/bin/env python3
"""label_bench.py — measure the QUALITY of a car's material labels, whichever
route produced them (PartCrafter parts, the 2D-seg chain, a hybrid transfer).

Written 2026-08-20 for the PartCrafter-vs-2D-seg glazing bake-off. Every metric
here exists because a cheaper one gave the wrong answer first; read the notes
before replacing any of them.

  parts     - vertex share / bbox / watertightness of a PartCrafter part dir.
  dup       - duplication vs eps. THE test for "is this a partition or a pile
              of overlapping shells". At a LOOSE eps (1% of car length) it
              cannot tell a duplicate shell from two genuinely adjacent
              surfaces -- glass sitting 4cm in front of an interior shell
              scored 47%, which reads as duplication and is not. Sweep it: a
              real partition's curve COLLAPSES as eps tightens (0.7% at 0.1%
              of extent), overlapping shells stay high (3.5-5.5%).
  glazing   - anatomy of one label. The headline is COMPONENTS HOLDING 90% OF
              THE AREA: a real car's glazing is 8-10 panes separated by
              pillars, so ~9 is right and 1 means the pillars were swallowed.
              Count components on a COORDINATE-QUANTISED weld -- trimesh's
              merge_vertices keeps split verts when normals differ, and a GLB
              stores 3 unique verts per face, so the naive count is ~1
              component per face and reads as total fragmentation (measured:
              190k "components" for a surface that is actually one piece).

NOT a verdict on its own. Every number here is a candidate finder; the
label render is what decides (see bl_label_render.py).
"""
import argparse
import glob
import os

import numpy as np
import trimesh


# --------------------------------------------------------------- helpers ---
def weld_index(v, tol_frac=1e-5):
    """Vertex index after quantising coordinates -- see the docstring note."""
    L = float((v.max(0) - v.min(0)).max())
    q = np.round(v / (L * tol_frac)).astype(np.int64)
    _, inv = np.unique(q, axis=0, return_inverse=True)
    return inv


def face_components(m, tol_frac=1e-5):
    """Connected components over faces, welding by quantised coordinate."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    v, f = np.asarray(m.vertices), np.asarray(m.faces)
    fw = weld_index(v, tol_frac)[f]
    e = np.concatenate([fw[:, [0, 1]], fw[:, [1, 2]], fw[:, [2, 0]]])
    fid = np.tile(np.arange(len(f)), 3)
    key = np.sort(e, axis=1)
    order = np.lexsort((key[:, 1], key[:, 0]))
    key, fid = key[order], fid[order]
    idx = np.where(np.all(key[:-1] == key[1:], axis=1))[0]
    n = len(f)
    g = coo_matrix((np.ones(len(idx)), (fid[idx], fid[idx + 1])), shape=(n, n))
    ncomp, lab = connected_components(g, directed=False)
    sizes = np.bincount(lab, weights=m.area_faces, minlength=ncomp)
    return ncomp, -np.sort(-sizes)


def load_parts(d):
    return [(os.path.basename(p)[:-4], trimesh.load(p, force="mesh"))
            for p in sorted(glob.glob(os.path.join(d, "part_*.glb")))]


def load_labelled(path, wanted=None):
    """{material name -> mesh} from a GLB whose labels are separate prims."""
    s = trimesh.load(path)
    out = {}
    for n, g in s.geometry.items():
        mat = (g.visual.material.name
               if getattr(g.visual, "material", None) is not None else n)
        if wanted and mat not in wanted and n not in wanted:
            continue
        out.setdefault(mat, []).append(g)
    return {k: (trimesh.util.concatenate(v) if len(v) > 1 else v[0])
            for k, v in out.items()}


# --------------------------------------------------------------- metrics ---
def cmd_parts(a):
    parts = load_parts(a.dir)
    allv = np.vstack([m.vertices for _, m in parts])
    lo, hi = allv.min(0), allv.max(0)
    tot = sum(len(m.vertices) for _, m in parts)
    print(f"{len(parts)} parts, {tot:,} verts, bbox ext "
          f"{np.round(hi - lo, 3)}")
    print(f"{'part':10s} {'verts':>9s} {'v%':>6s} {'watertight':>11s}  ext")
    for n, m in sorted(parts, key=lambda kv: -len(kv[1].vertices)):
        e = np.round(m.vertices.max(0) - m.vertices.min(0), 3)
        print(f"{n:10s} {len(m.vertices):9d} {100*len(m.vertices)/tot:6.2f} "
              f"{str(m.is_watertight):>11s}  {list(e)}")


def cmd_dup(a):
    from scipy.spatial import cKDTree
    items = (load_parts(a.dir) if a.dir
             else list(load_labelled(a.glb).items()))
    P = []
    for n, m in items:
        q, _ = trimesh.sample.sample_surface(m, a.samples)
        r, _ = trimesh.sample.sample_surface(m, a.samples * 10)
        P.append((n, m, np.asarray(q), cKDTree(np.asarray(r))))
    allv = np.vstack([m.vertices for _, m, _, _ in P])
    L = float((allv.max(0) - allv.min(0)).max())
    EPS = [0.001, 0.0025, 0.005, 0.01, 0.02]
    tot = sum(len(m.vertices) for _, m, _, _ in P)
    print(f"extent {L:.3f}; duplication = share of a label's surface lying on "
          f"ANOTHER label's surface")
    print(f"{'label':12s} {'v%':>6s} " + " ".join(f"{100*e:>6.2f}%" for e in EPS))
    acc = {e: 0.0 for e in EPS}
    rows = []
    for i, (ni, mi, qi, _) in enumerate(P):
        dmin = np.full(len(qi), np.inf)
        for j, (_, _, _, tj) in enumerate(P):
            if i == j:
                continue
            dd, _ = tj.query(qi, workers=-1)
            dmin = np.minimum(dmin, dd)
        rows.append((ni, len(mi.vertices), dmin / L))
    for ni, v, dn in sorted(rows, key=lambda r: -r[1]):
        vals = [float((dn < e).mean()) for e in EPS]
        for e, x in zip(EPS, vals):
            acc[e] += x * v
        print(f"{ni:12s} {100*v/tot:6.2f} " + " ".join(f"{100*x:6.1f}"
                                                      for x in vals))
    print(f"{'WEIGHTED':12s} {100.0:6.2f} " +
          " ".join(f"{100*acc[e]/tot:6.1f}" for e in EPS))
    print("\na true partition collapses toward 0 as eps tightens; overlapping "
          "shells stay high at 0.10%")


def cmd_glazing(a):
    g = load_labelled(a.glb, wanted={a.material})
    if not g:
        raise SystemExit(f"no material named {a.material!r} in {a.glb}")
    m = list(g.values())[0]
    whole = trimesh.load(a.glb)
    allv = np.vstack([x.vertices for x in whole.geometry.values()])
    lo, hi = allv.min(0), allv.max(0)
    UP = a.up
    H = hi[UP] - lo[UP]
    fa, fn = m.area_faces, m.face_normals
    hz = (m.triangles_center[:, UP] - lo[UP]) / H
    ncomp, sizes = face_components(m)
    tot = sizes.sum()
    n90 = int(np.searchsorted(np.cumsum(sizes) / tot, 0.90) + 1)
    print(f"{a.glb}  material={a.material}")
    print(f"  faces {len(m.faces):,}   area {tot:.4f}")
    print(f"  components {ncomp}; largest {100*sizes[0]/tot:.2f}% of area; "
          f"COMPONENTS HOLDING 90% OF AREA = {n90}")
    print(f"     (a real car's glazing is 8-10 panes -> ~9. 1 means the "
          f"pillars were swallowed into one canopy.)")
    print(f"  area in components < 1% : {100*sizes[sizes<0.01*tot].sum()/tot:.2f}%")
    print(f"  height band 5th-95th pct: {np.percentile(hz,5):.2f} - "
          f"{np.percentile(hz,95):.2f}   (greenhouse ~0.62-0.95)")
    print(f"  area below 45% of car height: "
          f"{100*fa[hz<0.45].sum()/fa.sum():.1f}%  (spill onto the doors)")
    up = np.abs(fn[:, UP])
    print(f"  area with |n_up| > 0.85 : {100*fa[up>0.85].sum()/fa.sum():.1f}%")
    print("     (NOT a roof detector on its own: a raked windscreen reaches "
          "n_up 0.87, so a high value can be a legitimate screen and a 0.0% "
          "means a normal-split has already carved the flat parts out.)")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("parts"); p.add_argument("dir"); p.set_defaults(fn=cmd_parts)
    p = sub.add_parser("dup")
    p.add_argument("--dir"); p.add_argument("--glb")
    p.add_argument("--samples", type=int, default=15000)
    p.set_defaults(fn=cmd_dup)
    p = sub.add_parser("glazing")
    p.add_argument("glb"); p.add_argument("--material", default="glass")
    p.add_argument("--up", type=int, default=1)
    p.set_defaults(fn=cmd_glazing)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
