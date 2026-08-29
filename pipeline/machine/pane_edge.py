#!/usr/bin/env python3
"""pane_edge.py — make the window aperture ONE smooth outline, not two torn ones.

THE DEFECT, measured on the four-image Golf before anything was changed:

    glass shell      133,392 faces   3,783 open-boundary edges   24.01 m
    carpaint shell   779,924 faces  15,248 open-boundary edges  108.59 m
    glass rim -> body surface        p50 0.09 mm, p95 0.19 mm

Four glass panes whose outlines ought to total roughly 12 m carry 24 m of
open edge, and the body's aperture rim is torn in the same way. The two
rims sit 0.1 mm apart and interlock, so along every A-pillar, header and
beltline the eye sees an alternating fringe of body and glass. That is the
"A-pillar problem" — not a hole, not a missing pillar, and not a shading
bug: a shared outline that is about twice as long as it should be.

WHY THE OBVIOUS DIAGNOSIS IS WRONG. This looks like the recorded k-NN
label dither, and the recorded answer to that is the 2D stencil stamp in
seg_boundary. But the two shells share ZERO edges — measured, 0 of 913,316
faces — so at the point the defect exists there is no single labelled mesh
left to re-stamp. seg_assemble has already split the labels into separate
primitives. The stencil has to be re-applied downstream, across two
meshes, by MOVING FACES BETWEEN THEM.

RESULT: THIS ROUTE DOES NOT WORK, AND THE FILE IS KEPT AS THAT EVIDENCE.
Both variants were run on the Golf and both were REFUSED by the tool's own
guard, which is the outcome the guard exists for:

    two-sided (annex + evict)   24.01 -> 50.38 m   +110%
    additive only (annex)       24.00 -> 38.06 m    +59%

The reason is structural, not a tuning problem. Moving a face out of a
shell creates open boundary in BOTH shells, and it can only pay for itself
if the moved set exactly plugs a hole in the other one. Here it cannot:
glass and carpaint share ZERO edges, so the annexed teeth arrive as
free-floating patches carrying their own rim, and eviction additionally
punches interior holes because a glass face can sit outside this pane's
mask simply by belonging to the next pane.

SO THE FIX BELONGS UPSTREAM, at seg_boundary, where the car is still ONE
labelled mesh and moving a label moves no geometry at all. The chain runs
that stage with GLASS_STENCIL=0. Turning it on is the recorded answer to
exactly this dither. Do not spend another pass down here.

WHY THIS IS NOT pane_clean.py, WHICH FAILED. pane_clean was ADDITIVE ONLY:
it annexed body triangles into the pane, which moves the ragged edge
outward instead of removing it, and it scored itself with the perimeter
shape factor P/sqrt(A) — a measure of whether an outline is tidy, not of
whether the edge is torn. It made four of six panes worse. This tool is
TWO-SIDED (body faces inside the smoothed outline become glass AND glass
faces outside it become body) and it scores itself on OPEN-BOUNDARY EDGE
LENGTH, which is the thing the eye is actually reacting to.

THE OUTLINE IS SMOOTHED, NOT REDRAWN. Rasterise the pane, close the bites,
fill, open away the spurs, then blur and re-threshold — the standard
morphological sequence — and re-stamp both shells against that one mask.
A quadric height field over the pane basis carries windscreen curvature,
so the "near this pane" test does not lose the top and bottom of a raked
screen the way a flat plane does.

REFUSES rather than shipping a worse file: if it would move more than
MAX_MOVE_FRAC of the body, if pane area moves more than MAX_AREA_DELTA, or
if the boundary length does not actually fall.

Run: python3 pane_edge.py <in.glb> <out.glb> [--res 0.006] [--close 7]
                          [--blur 2.0] [--band 0.035] [--report r.json]
"""
import argparse
import json
from collections import defaultdict

import numpy as np
import trimesh
from scipy import ndimage

MIN_PANE_FACES = 400
MAX_MOVE_FRAC = 0.05          # of the body's faces
MAX_AREA_DELTA = 0.30         # of the glass area


def weld(m, tol=5e-4):
    q = np.round(m.vertices / tol).astype(np.int64)
    uq, inv = np.unique(q, axis=0, return_inverse=True)
    f = inv[m.faces]
    f = f[(f[:, 0] != f[:, 1]) & (f[:, 1] != f[:, 2]) & (f[:, 0] != f[:, 2])]
    return trimesh.Trimesh(vertices=uq * tol, faces=f, process=False)


def open_boundary(m):
    """(edge count, total length) of the shell's own open rim."""
    w = weld(m)
    cnt = defaultdict(int)
    for tri in w.faces:
        for a, b in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
            cnt[(min(a, b), max(a, b))] += 1
    bnd = [e for e, c in cnt.items() if c == 1]
    L = float(sum(np.linalg.norm(w.vertices[a] - w.vertices[b])
                  for a, b in bnd))
    return len(bnd), L


def basis(pts):
    ctr = pts.mean(0)
    _, _, vt = np.linalg.svd(pts - ctr, full_matrices=False)
    n, e1 = vt[2], vt[0]
    e2 = np.cross(n, e1)
    return ctr, e1, e2, n


def quadric(uv, h):
    """Least-squares z = a u^2 + b uv + c v^2 + d u + e v + f."""
    u, v = uv[:, 0], uv[:, 1]
    A = np.stack([u * u, u * v, v * v, u, v, np.ones_like(u)], 1)
    coef, *_ = np.linalg.lstsq(A, h, rcond=None)
    return coef


def evaluate(coef, uv):
    u, v = uv[:, 0], uv[:, 1]
    A = np.stack([u * u, u * v, v * v, u, v, np.ones_like(u)], 1)
    return A @ coef


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inp")
    ap.add_argument("out")
    ap.add_argument("--res", type=float, default=0.006)
    ap.add_argument("--close", type=int, default=7)
    ap.add_argument("--blur", type=float, default=2.0)
    ap.add_argument("--band", type=float, default=0.035)
    ap.add_argument("--evict", action="store_true",
                    help="also push glass faces outside the outline back to "
                         "the body. OFF by default: measured on the Golf it "
                         "punched interior holes and DOUBLED the open "
                         "boundary (24.01 -> 50.38 m), because a glass face "
                         "can be outside this pane's mask simply by "
                         "belonging to a neighbouring pane.")
    ap.add_argument("--report", default=None)
    a = ap.parse_args()

    sc = trimesh.load(a.inp, force="scene")
    if "glass" not in sc.geometry or "carpaint" not in sc.geometry:
        raise SystemExit("REFUSED: need both a 'glass' and a 'carpaint' "
                         f"geometry; this file has {sorted(sc.geometry)}")
    gl, cp = sc.geometry["glass"], sc.geometry["carpaint"]
    nb0, L0 = open_boundary(gl)
    area0 = float(gl.area)
    print(f"BEFORE  glass open boundary {nb0} edges, {L0:.2f} m; "
          f"area {area0:.4f} m2")

    panes = [c for c in weld(gl).split(only_watertight=False)
             if len(c.faces) >= MIN_PANE_FACES]
    panes.sort(key=lambda c: -c.area)
    print(f"panes: {len(panes)}")

    gc, cc = gl.triangles_center, cp.triangles_center
    to_glass = np.zeros(len(cp.faces), bool)     # body -> glass
    to_body = np.zeros(len(gl.faces), bool)      # glass -> body
    per = []

    for pi, pane in enumerate(panes):
        pts = pane.triangles_center
        ctr, e1, e2, n = basis(pts)
        d = pts - ctr
        uv = np.stack([d @ e1, d @ e2], 1)
        h = d @ n
        coef = quadric(uv, h)

        lo = uv.min(0) - a.res * 4
        gw = np.ceil((uv.max(0) + a.res * 4 - lo) / a.res).astype(int) + 1
        if gw.max() > 6000:
            print(f"  pane {pi}: grid {gw} too large — skipped")
            per.append({"pane": pi, "skipped": "grid"})
            continue
        ij = ((uv - lo) / a.res).astype(int)
        msk = np.zeros(gw[::-1], bool)
        msk[ij[:, 1], ij[:, 0]] = True
        k = np.ones((a.close, a.close), bool)
        msk = ndimage.binary_fill_holes(ndimage.binary_closing(msk, k))
        msk = ndimage.binary_opening(msk, np.ones((3, 3), bool))
        # blur + re-threshold: this is what actually straightens the outline;
        # closing alone fills the bites but keeps their jagged rim
        msk = ndimage.gaussian_filter(msk.astype(float), a.blur) > 0.5
        msk = ndimage.binary_fill_holes(msk)

        def classify(cs):
            dd = cs - ctr
            uu = np.stack([dd @ e1, dd @ e2], 1)
            hh = dd @ n
            near = np.abs(hh - evaluate(coef, uu)) < a.band
            jj = ((uu - lo) / a.res).astype(int)
            ok = ((jj[:, 0] >= 0) & (jj[:, 0] < gw[0]) &
                  (jj[:, 1] >= 0) & (jj[:, 1] < gw[1]))
            inside = np.zeros(len(cs), bool)
            sel = near & ok
            inside[sel] = msk[jj[sel, 1], jj[sel, 0]]
            return inside, near & ok

        b_in, _ = classify(cc)
        g_in, g_near = classify(gc)
        to_glass |= b_in
        if a.evict:
            to_body |= g_near & ~g_in
            per.append({"pane": pi, "faces": int(len(pane.faces)),
                    "body_in": int(b_in.sum()),
                    "glass_out": int((g_near & ~g_in).sum())})
        print(f"  pane {pi}: {len(pane.faces):6d} faces -> "
              f"annex {int(b_in.sum()):5d} body, evict "
              f"{int((g_near & ~g_in).sum()):5d} glass")

    # a face cannot be both annexed and kept out
    moved = int(to_glass.sum() + to_body.sum())
    print(f"total moved: {moved} faces "
          f"({int(to_glass.sum())} in, {int(to_body.sum())} out)")
    if to_glass.sum() > MAX_MOVE_FRAC * len(cp.faces):
        raise SystemExit(
            f"REFUSED: would move {int(to_glass.sum())} body faces "
            f"({100*to_glass.sum()/len(cp.faces):.1f}%) — the outlines are "
            f"wrong, not the edge")
    if moved == 0:
        raise SystemExit("REFUSED: nothing to move — writing an unchanged "
                         "copy would be a no-op dressed as a fix")

    new_glass = trimesh.util.concatenate([
        gl.submesh([np.where(~to_body)[0]], append=True),
        cp.submesh([np.where(to_glass)[0]], append=True)])
    new_body = trimesh.util.concatenate([
        cp.submesh([np.where(~to_glass)[0]], append=True),
        gl.submesh([np.where(to_body)[0]], append=True)])

    da = (new_glass.area - area0) / area0
    print(f"glass area {area0:.4f} -> {new_glass.area:.4f} m2 ({100*da:+.1f}%)")
    if abs(da) > MAX_AREA_DELTA:
        raise SystemExit(f"REFUSED: glass area moved {100*da:+.1f}% — that is "
                         f"a different window, not a tidier edge")

    nb1, L1 = open_boundary(new_glass)
    print(f"AFTER   glass open boundary {nb1} edges, {L1:.2f} m "
          f"({100*(L1-L0)/L0:+.1f}%)")
    if L1 >= L0:
        raise SystemExit(f"REFUSED: boundary length did not fall "
                         f"({L0:.2f} -> {L1:.2f} m). pane_clean.py failed in "
                         f"exactly this way and was shipped anyway; not again")

    # keep the ORIGINAL materials — a fresh TextureVisuals, because
    # reassigning one whose uv length no longer matches silently drops the
    # binding on export (recorded trap)
    new_glass.visual = trimesh.visual.TextureVisuals(material=gl.visual.material)
    new_body.visual = trimesh.visual.TextureVisuals(
        uv=getattr(new_body.visual, "uv", None), material=cp.visual.material)

    out = trimesh.Scene()
    for node in sc.graph.nodes_geometry:
        T, gname = sc.graph[node]
        if gname == "glass":
            out.add_geometry(new_glass, geom_name="glass", node_name=node,
                             transform=T)
        elif gname == "carpaint":
            out.add_geometry(new_body, geom_name="carpaint", node_name=node,
                             transform=T)
        elif gname not in out.geometry:
            out.add_geometry(sc.geometry[gname], geom_name=gname,
                             node_name=node, transform=T)
    out.export(a.out, include_normals=True)
    print(f"wrote {a.out}")

    if a.report:
        json.dump({"before": {"edges": nb0, "length_m": L0, "area": area0},
                   "after": {"edges": nb1, "length_m": L1,
                             "area": float(new_glass.area)},
                   "moved_to_glass": int(to_glass.sum()),
                   "moved_to_body": int(to_body.sum()),
                   "panes": per}, open(a.report, "w"), indent=1)


if __name__ == "__main__":
    main()
