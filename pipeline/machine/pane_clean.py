#!/usr/bin/env python3
"""pane_clean.py — straighten ragged glazing perimeters, PER PANE.

THE DEFECT, measured on the Tripo v3.1 Golf (2026-08-29) after the owner
photographed the B-pillar: "fix the steam and clean the window". Two
separate faults live in that one crop.

  1. RAGGED PANE PERIMETERS. The panes are topologically fine — a
     coordinate-weld finds 6 real components (windscreen, backlight, four
     side windows), no fragment soup. It is their OUTLINES that zigzag.
     Shape factor P/sqrt(A), where a clean quad-ish pane sits near 4.5:

         pane 0 windscreen   4.64   clean
         pane 1 backlight    4.54   clean
         pane 4 rear-right   5.00   ok
         pane 5 front-right  6.10   ragged
         pane 3 rear-left    6.48   ragged
         pane 2 front-left   7.21   worst

     The clean/ragged split falls exactly on windscreen+backlight vs the
     DOOR glass, which is the view the owner photographed.

  2. "STEAM" — 2,603 carpaint faces inside the glazing band whose texels
     are bright (luma>130), 6x enriched over door skin below the beltline
     (3.8% vs 0.64%). These are baked window-reflection texels sitting on
     body faces that poke into the aperture, and they read as smeared
     light streaks across the glass and down the pillar.

WHY PER PANE. seg_boundary already has a stencil pass for this and it is
DISABLED on this car for a recorded reason: it recomputes regions from the
LABEL ALONE, so windscreen + both flanks + backlight merge into one
1,113-face mega-region spanning 3.692m — longer than the car is tall — and
a single plane fitted through that throws the windscreen out (5 stamped in,
262 out). This tool takes the SIX REAL COMPONENTS from a coordinate-weld
instead, so every stencil is fitted to one actual window and the
mega-region failure cannot occur by construction.

METHOD, per pane: fit the pane's own plane, project its face centroids into
it, rasterise, morphologically CLOSE (fills the notches that make the
zigzag) then OPEN (removes the spurs), and restamp. Body faces whose
centroid falls inside the cleaned outline AND within the pane's plane band
become glass; glass faces outside every outline revert to body. The bright
"steam" faces are swept up by the same operation when they lie inside an
aperture, and are reported separately when they do not.

*** THIS TOOL DOES NOT WORK. KEPT AS AN EVIDENCE RECORDER. ***

Measured on the car it was written for, shape factor before -> after:

    pane 0 windscreen  4.64 -> 5.24   WORSE
    pane 1 backlight   4.54 -> 4.80   WORSE
    pane 2 front-left  7.21 -> 7.11   flat
    pane 3 rear-left   6.48 -> 5.95   better
    pane 4 rear-right  5.00 -> 5.76   WORSE
    pane 5 front-right 6.10 -> 7.62   MUCH WORSE

Four of six panes got worse. THE PREMISE IS WRONG: filling notches in a 2D
raster annexes EXISTING BODY TRIANGLES whose edges do not align with the
pane's, so the perimeter stays ragged and simply moves outward. You cannot
clean a boundary by absorbing more jagged triangles into it — the boundary
is made of triangle edges, and relabelling never changes an edge.

THE FIX THAT CAN WORK IS CONSTRUCTION, NOT RELABELLING: glass_panes.py
builds a FRESH GRID MESH per window on the fitted quadric and clips it to
the stencil outline, so the perimeter is clean by construction. That is the
route for this defect. This file exists so the relabelling route is not
attempted a third time (seg_boundary's stencil was the first).

--dry-run reports every number and writes nothing, because a boundary
operation that silently eats a windscreen is exactly this project's
recorded failure mode. It earned its keep: the first cut of this tool would
have discarded 20,404 glass faces (17.38%) because panes are CURVED and a
plane-band keep-test throws their edge faces away.

Run: python3 pane_clean.py <in.glb> <out.glb> [--dry-run] [--close 5] [--band 0.02]
"""
import argparse

import numpy as np
import trimesh
from scipy import ndimage


def weld_components(g, tol=1e-5):
    V = np.round(g.vertices / tol).astype(np.int64)
    uniq, inv = np.unique(V, axis=0, return_inverse=True)
    F = inv[g.faces]
    keep = (F[:, 0] != F[:, 1]) & (F[:, 1] != F[:, 2]) & (F[:, 0] != F[:, 2])
    w = trimesh.Trimesh(vertices=uniq * tol, faces=F[keep], process=False)
    # map welded faces back to original face indices
    orig = np.where(keep)[0]
    comps = w.split(only_watertight=False)
    out = []
    for c in comps:
        if len(c.faces) < 200:
            continue
        # match by centroid — cheap and unambiguous at this scale
        out.append(c)
    return out, w, orig


def shape_factor(c):
    e = c.edges_sorted
    uniq, cnt = np.unique(e, axis=0, return_counts=True)
    b = uniq[cnt == 1]
    if not len(b):
        return float("nan"), 0.0
    P = np.linalg.norm(c.vertices[b[:, 0]] - c.vertices[b[:, 1]], axis=1).sum()
    return P / np.sqrt(c.area), P


def plane_basis(pts):
    ctr = pts.mean(0)
    u, s, vt = np.linalg.svd(pts - ctr, full_matrices=False)
    n = vt[2]
    e1 = vt[0]
    e2 = np.cross(n, e1)
    return ctr, n, e1, e2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inp")
    ap.add_argument("out")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--close", type=int, default=5)
    ap.add_argument("--band", type=float, default=0.02,
                    help="max distance from a pane's plane for a body face "
                         "to be absorbed into it (m)")
    ap.add_argument("--res", type=float, default=0.006,
                    help="stencil cell size (m)")
    a = ap.parse_args()

    sc = trimesh.load(a.inp, force="scene")
    gl = sc.geometry["glass"]
    cp = sc.geometry["carpaint"]
    comps, _, _ = weld_components(gl)
    comps = sorted(comps, key=lambda c: -c.area)
    print(f"glazing: {len(comps)} substantial panes")

    cc = cp.triangles_center
    gc = gl.triangles_center
    absorb = np.zeros(len(cp.faces), bool)
    inside_any = np.zeros(len(gl.faces), bool)

    for i, c in enumerate(comps):
        sf0, P0 = shape_factor(c)
        pts = c.triangles_center
        ctr, n, e1, e2 = plane_basis(pts)
        # pane-local 2D coords
        d2 = np.stack([(pts - ctr) @ e1, (pts - ctr) @ e2], 1)
        lo = d2.min(0) - a.res * 4
        gridw = np.ceil((d2.max(0) + a.res * 4 - lo) / a.res).astype(int) + 1
        if gridw.max() > 4000:
            print(f"  pane {i}: grid too large ({gridw}) — skipped")
            continue
        ij = ((d2 - lo) / a.res).astype(int)
        mask = np.zeros(gridw[::-1], bool)
        mask[ij[:, 1], ij[:, 0]] = True
        st = np.ones((a.close, a.close), bool)
        cleaned = ndimage.binary_closing(mask, st)
        cleaned = ndimage.binary_fill_holes(cleaned)
        cleaned = ndimage.binary_opening(cleaned, np.ones((3, 3), bool))
        gained = int(cleaned.sum() - mask.sum())

        # body faces near this plane and inside the cleaned outline
        dist = np.abs((cc - ctr) @ n)
        near = dist < a.band
        if near.any():
            b2 = np.stack([(cc[near] - ctr) @ e1, (cc[near] - ctr) @ e2], 1)
            bij = ((b2 - lo) / a.res).astype(int)
            ok = ((bij[:, 0] >= 0) & (bij[:, 0] < gridw[0]) &
                  (bij[:, 1] >= 0) & (bij[:, 1] < gridw[1]))
            sel = np.zeros(len(b2), bool)
            sel[ok] = cleaned[bij[ok, 1], bij[ok, 0]]
            idx = np.where(near)[0][sel]
            absorb[idx] = True
        # NOTE the operation is deliberately ADDITIVE ONLY. The first cut
        # also tested each GLASS face against the cleaned stencil and kept
        # only those inside — and the dry run showed that would discard
        # 20,404 faces, 17.38% of the glazing. The cause is curvature: a
        # windscreen is not planar, so its edge faces sit well beyond any
        # sane plane band, and a plane-based keep-test throws them away.
        # Discarding a sixth of the glazing to tidy an outline is the
        # mega-region failure wearing a different hat. Existing glass is
        # therefore never removed here; the stencil only FILLS the notches
        # that make the perimeter zigzag.

        print(f"  pane {i}: {len(c.faces):6d} faces  P/sqrt(A) {sf0:5.2f}  "
              f"stencil cells {int(mask.sum()):6d} -> {int(cleaned.sum()):6d} "
              f"(+{gained})")

    print(f"\nbody faces absorbed into panes : {int(absorb.sum())} "
          f"({100*absorb.sum()/len(cp.faces):.2f}% of carpaint)")
    print("glass faces removed            : 0 (additive-only by design)")
    if absorb.sum() > 0.08 * len(cp.faces):
        raise SystemExit(f"REFUSED: the stencils would absorb "
                         f"{int(absorb.sum())} body faces "
                         f"({100*absorb.sum()/len(cp.faces):.1f}% of carpaint) "
                         f"— that is a stencil eating the bodywork, not "
                         f"cleaning an edge")
    if a.dry_run:
        print("\nDRY RUN — nothing written")
        return

    new_glass = gl.copy()
    new_glass.visual = trimesh.visual.TextureVisuals(material=gl.visual.material)
    add = cp.submesh([np.where(absorb)[0]], append=True)
    add.visual = trimesh.visual.TextureVisuals(material=gl.visual.material)
    merged = trimesh.util.concatenate([new_glass, add])
    merged.visual = trimesh.visual.TextureVisuals(material=gl.visual.material)
    body = cp.submesh([np.where(~absorb)[0]], append=True)
    body.visual = trimesh.visual.TextureVisuals(
        uv=getattr(body.visual, "uv", None), material=cp.visual.material)

    out = trimesh.Scene()
    for node in sc.graph.nodes_geometry:
        T, gn = sc.graph[node]
        if gn == "glass":
            out.add_geometry(merged, geom_name="glass", node_name=node, transform=T)
        elif gn == "carpaint":
            out.add_geometry(body, geom_name="carpaint", node_name=node, transform=T)
        elif gn not in out.geometry:
            out.add_geometry(sc.geometry[gn], geom_name=gn, node_name=node,
                             transform=T)
    out.export(a.out, include_normals=True)

    # re-measure: the whole point is that the number moves the right way
    g2 = trimesh.load(a.out, force="scene").geometry["glass"]
    c2, _, _ = weld_components(g2)
    c2 = sorted(c2, key=lambda c: -c.area)
    print("\nAFTER:")
    for i, c in enumerate(c2):
        sf, _ = shape_factor(c)
        print(f"  pane {i}: {len(c.faces):6d} faces  P/sqrt(A) {sf:5.2f}")
    print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
