#!/usr/bin/env python3
"""label_smooth.py — de-fringe the glass/body boundary on the MESH GRAPH.

THE DEFECT. Every window on the Tripo cars carries a torn rim: body teeth
biting into the glazing and glass teeth biting into the pillar, interlocking
at triangle scale. It is worst around the rear quarter window and the
backlight, which is what the owner reported as "clean the back glass", and
it is the same thing as the A-pillar fringe.

TWO ROUTES HAVE ALREADY FAILED, MEASURED, AND THIS IS DELIBERATELY NEITHER:

  pane_edge.py       downstream, on the assembled primitives. Refused twice
                     by its own guard (+110%, +59% open boundary). Moving a
                     face between two unwelded shells creates as much free
                     rim as it fills.
  GLASS_STENCIL=1    upstream, but a 2D plane-and-raster stencil. A/B on
                     identical labels: 4,484 edges / 25.26 m against
                     3,297 / 21.31 m with it off. It LOSES.

The third route is the one neither of those is: smooth the labels on the
mesh's own ADJACENCY GRAPH. A face flips only if a clear majority of its
neighbours disagree with it, iterated a few times. Nothing moves in space,
no primitive is split, no rim can be created — the operation is defined
entirely on labels. It is morphological opening/closing, but on the surface
graph instead of a projected plane, so it has no plane to be wrong about
and it follows a curved screen and a wrapped corner without any fitting.

WHY A MAJORITY FILTER AND NOT A BLUR. A tooth one or two triangles wide is
a minority everywhere along its length, so it flips. A genuine pane edge
has a whole pane behind it and never is, so it holds. That asymmetry is the
entire mechanism, and it is why the threshold is a MAJORITY of neighbours
rather than a tuned distance.

MEASURED ON THE MESH, NOT ON A RENDER: the boundary is the set of adjacent
face pairs whose labels differ, and its length is the sum of those shared
edges. On one mesh that is exact and free — no welding, no shells, none of
the ambiguity that made the downstream metric unreadable.

REFUSES if the boundary does not fall, or if a class changes area by more
than MAX_CLASS_DELTA — a filter that dissolves a small class is not
smoothing it.

Run: python3 label_smooth.py <mesh.glb> <labels.npy> <out.npy>
                             [--iters 3] [--majority 0.60] [--report r.json]
"""
import argparse
import json

import numpy as np
import trimesh

MAX_CLASS_DELTA = 0.15        # of a class's own face count


def boundary(mesh, lab, adj):
    """(pairs, length) of adjacency pairs whose two faces disagree."""
    d = lab[adj[:, 0]] != lab[adj[:, 1]]
    if not d.any():
        return 0, 0.0
    # shared-edge length via the two faces' shared vertices
    tri = mesh.faces
    tot = 0.0
    for a, b in adj[d]:
        shared = np.intersect1d(tri[a], tri[b], assume_unique=False)
        if len(shared) == 2:
            v = mesh.vertices[shared]
            tot += float(np.linalg.norm(v[0] - v[1]))
    return int(d.sum()), tot


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mesh")
    ap.add_argument("labels")
    ap.add_argument("out")
    ap.add_argument("--iters", type=int, default=3)
    ap.add_argument("--majority", type=float, default=0.60)
    ap.add_argument("--ring", type=int, default=2, choices=(1, 2, 3),
                    help="neighbourhood size. RING 1 IS TOO WEAK and the "
                         "reason is arithmetic: a triangle has three "
                         "neighbours, and along a one-face-wide tooth two of "
                         "them are usually IN the tooth, so the tooth is "
                         "never outvoted. Measured on the Golf, ring 1 at "
                         "majority 0.60 moved the boundary only -4.3% and "
                         "converged. The 2-ring gives each face ~9-12 "
                         "neighbours, which is the first neighbourhood wider "
                         "than the defect it has to dissolve.")
    ap.add_argument("--report", default=None)
    a = ap.parse_args()

    m = trimesh.load(a.mesh, force="mesh", process=False)
    lab = np.load(a.labels).astype(np.int32)
    if len(lab) != len(m.faces):
        raise SystemExit(f"REFUSED: {len(lab)} labels for {len(m.faces)} faces")

    adj = m.face_adjacency
    print(f"{len(m.faces)} faces, {len(adj)} adjacency pairs")
    nbr = adj
    if a.ring >= 2:
        nf_ = len(m.faces)
        import scipy.sparse as sp
        A = sp.coo_matrix(
            (np.ones(2 * len(adj), np.int8),
             (np.concatenate([adj[:, 0], adj[:, 1]]),
              np.concatenate([adj[:, 1], adj[:, 0]]))),
            shape=(nf_, nf_)).tocsr()
        P = (A + A @ A) > 0
        if a.ring >= 3:
            # RING 3 IS BUILT ONLY NEAR THE BOUNDARY. A full 3-ring over
            # 1.46M faces is ~27 neighbours each, ~39M pairs, and this
            # container OOM-kills a single process well below free RAM (a
            # recorded limit — a proximity query over ~1M centroids was
            # killed at 12.7 GB). The filter can only ever change faces at
            # a label boundary anyway, so restrict the wide neighbourhood
            # to faces within a few rings of one and leave the rest at
            # ring 2. Same answer, a fraction of the memory.
            d0 = lab[adj[:, 0]] != lab[adj[:, 1]]
            seed = np.zeros(nf_, bool)
            seed[adj[d0].ravel()] = True
            grow = seed.copy()
            for _ in range(4):
                grow = grow | (A @ grow.astype(np.int8) > 0)
            keepf = np.where(grow)[0]
            print(f"  boundary neighbourhood: {len(keepf)} faces "
                  f"({100*len(keepf)/nf_:.1f}% of the mesh)")
            mask = sp.diags(grow.astype(np.int8))
            P = (P + (mask @ (P @ A) @ mask)) > 0
        P = P.tocoo()
        keep = P.row < P.col
        nbr = np.stack([P.row[keep], P.col[keep]], 1)
        print(f"  {a.ring}-ring neighbourhood: {len(nbr)} pairs "
              f"({2*len(nbr)/nf_:.1f} neighbours per face)")
    n0, L0 = boundary(m, lab, adj)
    before = {int(k): int(v) for k, v in
              zip(*np.unique(lab, return_counts=True))}
    print(f"BEFORE  boundary {n0} pairs, {L0:.2f} m   classes {before}")

    nf = len(m.faces)
    # neighbour lists as a flat CSR-ish structure, built once
    src = np.concatenate([nbr[:, 0], nbr[:, 1]])
    dst = np.concatenate([nbr[:, 1], nbr[:, 0]])
    order = np.argsort(src, kind="stable")
    src, dst = src[order], dst[order]
    starts = np.searchsorted(src, np.arange(nf))
    ends = np.searchsorted(src, np.arange(nf), side="right")
    deg = ends - starts

    cur = lab.copy()
    nclass = int(cur.max()) + 1
    for it in range(a.iters):
        # count neighbour labels per face
        counts = np.zeros((nf, nclass), np.int32)
        np.add.at(counts, (src, cur[dst]), 1)
        best = counts.argmax(axis=1)
        bestn = counts.max(axis=1)
        own = counts[np.arange(nf), cur]
        # flip only where a clear majority of neighbours disagree
        flip = (best != cur) & (bestn >= np.ceil(a.majority * np.maximum(deg, 1)))
        # and never where the face already agrees with most of its neighbours
        flip &= own < bestn
        if not flip.any():
            print(f"  iter {it+1}: nothing to flip — converged")
            break
        cur[flip] = best[flip]
        n, L = boundary(m, cur, adj)
        print(f"  iter {it+1}: flipped {int(flip.sum()):6d}  "
              f"boundary {n} pairs, {L:.2f} m")

    n1, L1 = boundary(m, cur, adj)
    after = {int(k): int(v) for k, v in
             zip(*np.unique(cur, return_counts=True))}
    print(f"AFTER   boundary {n1} pairs, {L1:.2f} m ({100*(L1-L0)/max(L0,1e-9):+.1f}%)"
          f"   classes {after}")

    for k, v in before.items():
        nv = after.get(k, 0)
        if abs(nv - v) > MAX_CLASS_DELTA * v:
            raise SystemExit(f"REFUSED: class {k} moved {v} -> {nv} "
                             f"({100*(nv-v)/v:+.1f}%) — that is dissolving a "
                             f"class, not smoothing its edge")
    if L1 >= L0:
        raise SystemExit(f"REFUSED: boundary did not fall ({L0:.2f} -> "
                         f"{L1:.2f} m)")

    np.save(a.out, cur)
    print(f"wrote {a.out}")
    if a.report:
        json.dump({"before": {"pairs": n0, "length_m": L0, "classes": before},
                   "after": {"pairs": n1, "length_m": L1, "classes": after},
                   "iters": a.iters, "majority": a.majority},
                  open(a.report, "w"), indent=1)


if __name__ == "__main__":
    main()
