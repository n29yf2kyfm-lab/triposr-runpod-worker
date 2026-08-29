#!/usr/bin/env python3
"""pillar_material.py — the B-pillar is GLOSS BLACK, not body paint.

WHY THIS EXISTS. pillar_recover takes the B-pillar back off the glazing
label, which is correct — the faces stop being transparent. But it hands
them to `carpaint`, so they render in body colour, and the owner's reaction
to that was immediate: "the b pillar is too wide, out of proportion".

Width was the obvious suspect and it was the wrong one. The first pass took
a whole 128 mm detector column, which was its own resolution rather than a
measurement; measuring properly off a 20 mm profile gives 160 mm on the
right flank and 180 mm on the left — WIDER than the thing being complained
about. So narrowing cannot be the fix.

The band is that wide because it is the pillar PLUS the black window frame
of each door, and on a real Golf every bit of it is gloss black. A 170 mm
black band between two panes reads as a normal pillar and recedes. The same
band in body paint reads as a fat painted post interrupting the glasshouse
— which is exactly what "out of proportion" describes. It is a MATERIAL
error presenting as a proportion error.

IT SELECTS BY GEOMETRY, NOT BY FACE INDEX. blender_finish welds and
re-indexes, so indices from the label stage mean nothing here. The bands
come from pillar_recover's report (x range per flank, plus the DLO height
band) and faces are picked by position, which survives any amount of
re-indexing.

The material name deliberately contains no "glass", "window" or "screen":
the render worker force-overrides transmission onto anything whose name
matches its glazing regex, and a transparent B-pillar would be a worse bug
than the one being fixed.

Run: python3 pillar_material.py <in.glb> <out.glb> <pillar.json>
                                [--luma 0.045] [--rough 0.22]
"""
import argparse
import json

import numpy as np
import trimesh

NAME = "Pillar_Gloss"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("inp")
    ap.add_argument("out")
    ap.add_argument("report")
    ap.add_argument("--luma", type=float, default=0.045)
    ap.add_argument("--rough", type=float, default=0.22)
    ap.add_argument("--margin", type=float, default=0.010)
    a = ap.parse_args()

    rep = json.load(open(a.report))
    bands = rep.get("bands") or []
    if not bands:
        raise SystemExit("REFUSED: no pillar bands in the report — nothing "
                         "to re-material, and inventing a position is the "
                         "assumption this whole stage exists to avoid")
    ylo = rep["y_lo"] - a.margin
    yhi = rep["y_hi"] + a.margin

    sc = trimesh.load(a.inp, force="scene")
    node_cp = [n for n in sc.graph.nodes_geometry
               if sc.graph[n][1] == "carpaint"]
    if not node_cp:
        raise SystemExit(f"REFUSED: no carpaint geometry in {a.inp}")
    node = node_cp[0]
    T, _ = sc.graph[node]
    cp = sc.geometry["carpaint"]
    world = trimesh.transform_points(cp.triangles_center, T)

    sel = np.zeros(len(cp.faces), bool)
    for b in bands:
        sgn = 1 if b["side"] == "R" else -1
        k = ((world[:, 0] >= b["x0"] - a.margin) &
             (world[:, 0] <= b["x1"] + a.margin) &
             (world[:, 1] >= ylo) & (world[:, 1] <= yhi) &
             (sgn * world[:, 2] > 0.25))
        sel |= k
        print(f"  {b['side']}: x {b['x0']:.3f}..{b['x1']:.3f} "
              f"({b['width_mm']} mm), y {ylo:.3f}..{yhi:.3f} "
              f"-> {int(k.sum())} faces")

    print(f"total {int(sel.sum())} of {len(cp.faces)} carpaint faces "
          f"({100*sel.sum()/len(cp.faces):.2f}%)")
    if sel.sum() < 200:
        raise SystemExit(f"REFUSED: only {int(sel.sum())} faces in the pillar "
                         f"bands — writing an unchanged copy would be a no-op "
                         f"dressed as a fix")
    if sel.sum() > 0.06 * len(cp.faces):
        raise SystemExit(f"REFUSED: {100*sel.sum()/len(cp.faces):.1f}% of the "
                         f"body is not a pillar")

    mat = trimesh.visual.material.PBRMaterial(
        name=NAME, baseColorFactor=[a.luma, a.luma, a.luma + 0.004, 1.0],
        metallicFactor=0.0, roughnessFactor=a.rough)
    pil = cp.submesh([np.where(sel)[0]], append=True)
    pil.visual = trimesh.visual.TextureVisuals(material=mat)
    rest = cp.submesh([np.where(~sel)[0]], append=True)
    rest.visual = trimesh.visual.TextureVisuals(
        uv=getattr(rest.visual, "uv", None), material=cp.visual.material)

    out = trimesh.Scene()
    for n in sc.graph.nodes_geometry:
        Tn, gname = sc.graph[n]
        if gname == "carpaint":
            out.add_geometry(rest, geom_name="carpaint", node_name=n,
                             transform=Tn)
        elif gname not in out.geometry:
            out.add_geometry(sc.geometry[gname], geom_name=gname, node_name=n,
                             transform=Tn)
    out.add_geometry(pil, geom_name=NAME, node_name=NAME, transform=T)
    out.export(a.out, include_normals=True)

    chk = trimesh.load(a.out, force="scene")
    if NAME not in chk.geometry:
        raise SystemExit(f"REFUSED: {NAME} is not in the written file")
    print(f"wrote {a.out} — {NAME} carries {len(chk.geometry[NAME].faces)} "
          f"faces at baseColor {a.luma}")


if __name__ == "__main__":
    main()
