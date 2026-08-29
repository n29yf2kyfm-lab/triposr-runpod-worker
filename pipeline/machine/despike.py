#!/usr/bin/env python3
"""despike.py — remove the thin blade artefacts the generator leaves behind.

THE DEFECT. Every Tripo car in this session carries thin sheets of geometry
standing off the cowl, the A-pillar top and the rear D-pillar — blades a few
faces wide and 50-150 mm long, sticking into the air. They are visible in
every side render, they are the first thing that reads as "generated", and
NOTHING in the chain removed them. CLAUDE.md has recorded this class since
the Hi3DGen work ("artefact fins on the roof (antenna class)") and it has
never had a stage.

WHY NOT A HEIGHT OR BBOX RULE. A blade off the roof and a roof aerial are
both thin things above the roofline; a wing mirror is a thin thing off the
flank. Any rule phrased in absolute position deletes real parts. The
discriminator has to be about SHAPE and ATTACHMENT, not location.

THE TEST, and both halves are needed:

  1. DISPLACEMENT UNDER SMOOTHING. Taubin-smooth a copy (volume preserving,
     so panels do not shrink) and measure how far each vertex moves. A blade
     collapses — it is supported by almost nothing — while a panel, a
     mirror shell and a spoiler barely move. This finds candidates.
  2. SMALL, ISOLATED CLUSTER. Take the faces built from those vertices and
     connect them. A blade is a cluster of a few hundred faces attached to
     the shell along a short seam. A mirror is a big cluster; a whole panel
     is enormous. Only clusters BELOW --max-cluster are deleted.

Test 1 alone deletes mirrors. Test 2 alone deletes any small detail. The
pair is what separates a fin from a feature, and it is the same shape as
the pillar rule: a cheap signal finds candidates, a structural property
gives the verdict.

IT RUNS EARLY — right after nose_fix, before the view set — so the masks,
the labels and every downstream stage see a car with no fins on it, rather
than each stage having to cope with them.

REFUSES if it would remove more than --max-frac of the mesh, because a
despiker that eats a car is worse than the fins.

Run: python3 despike.py <in.glb> <out.glb> [--iters 20] [--factor 3.0]
                        [--max-cluster 1200] [--max-frac 0.01]
"""
import argparse
import json

import numpy as np
import trimesh
import scipy.sparse as sp


def weld(m, tol=1e-5):
    q = np.round(m.vertices / tol).astype(np.int64)
    uq, inv = np.unique(q, axis=0, return_inverse=True)
    f = inv[m.faces]
    f = f[(f[:, 0] != f[:, 1]) & (f[:, 1] != f[:, 2]) & (f[:, 0] != f[:, 2])]
    return trimesh.Trimesh(vertices=uq * tol, faces=f, process=False), inv


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inp")
    ap.add_argument("out")
    ap.add_argument("--iters", type=int, default=20)
    ap.add_argument("--factor", type=float, default=3.0)
    ap.add_argument("--max-cluster", type=int, default=1200)
    ap.add_argument("--max-frac", type=float, default=0.01)
    ap.add_argument("--aspect", type=float, default=3.0,
                    help="longest extent / next longest. A blade is >=3; "
                         "surface noise is roughly isotropic.")
    ap.add_argument("--min-len", type=float, default=0.030,
                    help="metres. Below this it is speckle, not a fin.")
    ap.add_argument("--report", default=None)
    a = ap.parse_args()

    sc = trimesh.load(a.inp, force="scene")
    src = trimesh.util.concatenate(
        [g for g in sc.geometry.values()]) if len(sc.geometry) > 1 \
        else list(sc.geometry.values())[0]
    w, inv = weld(src)
    print(f"{len(src.faces)} faces, welded to {len(w.faces)}")

    sm = w.copy()
    trimesh.smoothing.filter_taubin(sm, lamb=0.6, nu=-0.62, iterations=a.iters)
    d = np.linalg.norm(w.vertices - sm.vertices, axis=1)
    med = float(np.median(d))
    thr = max(a.factor * med, 1e-6)
    high = d > thr
    print(f"displacement under smoothing: median {1000*med:.3f} mm, "
          f"cut at {1000*thr:.3f} mm -> {int(high.sum())} vertices "
          f"({100*high.sum()/len(d):.2f}%)")

    fh = high[w.faces].sum(axis=1) >= 2
    print(f"candidate faces (>=2 high vertices): {int(fh.sum())}")
    if fh.sum() == 0:
        raise SystemExit("REFUSED: no candidates — writing an unchanged copy "
                         "would be a no-op dressed as a fix")

    idx = np.where(fh)[0]
    sub = w.faces[idx]
    # connect candidate faces that share a vertex
    nv = len(w.vertices)
    rows = np.repeat(np.arange(len(idx)), 3)
    inc = sp.coo_matrix((np.ones(len(rows), np.int8), (rows, sub.ravel())),
                        shape=(len(idx), nv)).tocsr()
    ncomp, lab = sp.csgraph.connected_components(inc @ inc.T, directed=False)
    sizes = np.bincount(lab)
    # A FIN IS LONG AND THIN. Displacement alone found 1,028 clusters on the
    # white Golf and would have deleted 1.07% of the mesh - it was catching
    # ordinary surface noise, which is small and BLOBBY, not just the blades,
    # which are long and flat. Measure each cluster's oriented extents: a
    # blade has one extent much longer than the next, and a real length. A
    # noise speckle is roughly isotropic and tiny.
    keepc, killc, shapes = [], [], []
    for ci in range(ncomp):
        loc = np.where(lab == ci)[0]
        if sizes[ci] > a.max_cluster:
            keepc.append(ci); continue
        v = w.vertices[np.unique(sub[loc])]
        ext = np.sort(v.max(axis=0) - v.min(axis=0))[::-1]
        longest = float(ext[0])
        aspect = longest / max(float(ext[1]), 1e-9)
        shapes.append((ci, sizes[ci], longest, aspect))
        if longest >= a.min_len and aspect >= a.aspect:
            killc.append(ci)
        else:
            keepc.append(ci)
    if shapes:
        top = sorted(shapes, key=lambda t: -t[2])[:6]
        print("  largest candidate clusters (faces, length mm, aspect):")
        for ci, n, L, asp in top:
            mark = "FIN" if ci in killc else "keep"
            print(f"    {n:5d} faces  {1000*L:7.1f} mm  aspect {asp:5.2f}  {mark}")
    small = np.array(killc, dtype=int)
    kill_local = np.isin(lab, small) if len(small) else np.zeros(len(idx), bool)
    kill = idx[kill_local]
    print(f"candidate clusters: {ncomp}; {len(small)} judged FINS -> "
          f"{len(kill)} faces to remove ({100*len(kill)/max(len(w.faces),1):.3f}%)")

    if len(kill) == 0:
        raise SystemExit("REFUSED: no cluster is both long and thin — those "
                         "are parts or speckle, not fins")
    if len(kill) > a.max_frac * len(w.faces):
        raise SystemExit(f"REFUSED: {len(kill)} faces is more than "
                         f"{100*a.max_frac:.1f}% of the mesh — a despiker "
                         f"that eats a car is worse than the fins")

    keep_w = np.ones(len(w.faces), bool)
    keep_w[kill] = False
    # map the decision back onto the ORIGINAL (unwelded) faces so UVs and
    # material bindings survive: an original face dies iff its welded twin did
    ow = inv[src.faces]
    ow = np.sort(ow, axis=1)
    kw = np.sort(w.faces[kill], axis=1)
    kills = set(map(tuple, kw))
    keep_o = np.array([tuple(t) not in kills for t in map(tuple, ow)])
    print(f"original faces kept {int(keep_o.sum())} of {len(keep_o)} "
          f"({int((~keep_o).sum())} removed)")

    out = src.submesh([np.where(keep_o)[0]], append=True)
    out.export(a.out)
    chk = trimesh.load(a.out, force="mesh", process=False)
    print(f"wrote {a.out}: {len(chk.faces)} faces")
    if a.report:
        json.dump({"faces_in": int(len(src.faces)),
                   "faces_out": int(len(chk.faces)),
                   "removed": int((~keep_o).sum()),
                   "clusters_removed": int(len(small)),
                   "median_disp_mm": 1000 * med}, open(a.report, "w"), indent=1)


if __name__ == "__main__":
    main()
