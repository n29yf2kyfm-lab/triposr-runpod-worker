#!/usr/bin/env python3
"""hole_attrib.py — attribute every LOST / DEEPER pixel to the NODE that used to
own it, and re-run the same test over the PAINTED EXTERIOR only.

hole_test.py answers "did the car's opaque silhouette change". It reports a small
non-zero LOST count outside the glazing panes, and that number lumps two very
different things together:

  * a lost pixel that used to be `Interior` — the inner skin was the outermost
    surface there, and removing it across an UNGLAZED part of the aperture is
    the intended effect of this gate (the glazing panes on this car are partial,
    so "not covered by a pane" is not the same as "not an opening");
  * a lost pixel that used to be `Body_Shell` or a bumper — that would be a real
    hole in the paint, and is the thing that must be zero.

So this reports per-node, and separately runs the whole test over the PAINTED
EXTERIOR set (everything except Interior and glazing), where the claim is
LOST == 0 and DEEPER == 0.

Run: python3 hole_attrib.py <before.glb> <after.glb>
"""
import json
import sys
import numpy as np
import trimesh
import raster

BEF, AFT = sys.argv[1], sys.argv[2]
GLAZE = {"Glass_Rear", "Glass_Windscreen", "Glass_Side_L", "Glass_Side_R"}
SKIN = GLAZE | {"Interior"}
THRESH = 0.05
import os
ELS = tuple(int(v) for v in os.environ.get("HA_ELS", "-18,0,18").split(","))
DIRS = [(az, el) for el in ELS for az in (0, -22, 22, -40, 40)]


def gather(path, drop):
    sc = trimesh.load(path, force="scene", process=False)
    V, F, ids, names = [], [], [], []
    for node in sc.graph.nodes_geometry:
        if node in drop:
            continue
        T, gn = sc.graph[node]
        g = sc.geometry[gn]
        f = np.asarray(g.faces)
        F.append(f + sum(len(x) for x in V))
        V.append(trimesh.transform_points(g.vertices, T))
        ids.append(np.full(len(f), len(names)))
        names.append(node)
    return (raster.gltf_to_blender(np.vstack(V)), np.vstack(F),
            np.concatenate(ids), names)


def cams(Vb):
    lo, hi = Vb.min(0), Vb.max(0)
    ctr = (lo + hi) / 2
    diag = float(np.linalg.norm(hi - lo))
    out = {}
    for az, el in DIRS:
        a, e = np.radians(az), np.radians(el)
        r = diag * 2.2
        out[f"az{az:+04d}_el{el:+03d}"] = raster.Cam(
            [ctr[0] + r * np.cos(a) * np.cos(e),
             ctr[1] + r * np.sin(a) * np.cos(e), ctr[2] + r * np.sin(e)],
            ctr, 62.0, (1100, 720))
    return out


def glaze(path):
    sc = trimesh.load(path, force="scene", process=False)
    V, F = [], []
    for node in sc.graph.nodes_geometry:
        if node not in GLAZE:
            continue
        T, gn = sc.graph[node]
        g = sc.geometry[gn]
        F.append(np.asarray(g.faces) + sum(len(x) for x in V))
        V.append(trimesh.transform_points(g.vertices, T))
    return raster.gltf_to_blender(np.vstack(V)), np.vstack(F)


out = {}
for tag, drop, claim in (("ALL_OPAQUE", GLAZE, "attribution only"),
                         ("PAINTED_EXTERIOR", SKIN, "LOST and DEEPER must be 0")):
    Vb, Fb, ib_, nb = gather(BEF, drop)
    Va, Fa, ia_, na = gather(AFT, drop)
    Vg, Fg = glaze(AFT)
    C = cams(Vb)
    lostn = {}
    deepn = {}
    tot = {"before_px": 0, "lost_out": 0, "deeper_out": 0, "gained_out": 0}
    for name, cam in C.items():
        idb, zb = raster.rasterise(cam, Vb, Fb, ib_)
        ida, za = raster.rasterise(cam, Va, Fa, ia_)
        _, zg = raster.rasterise(cam, Vg, Fg)
        AP = np.isfinite(zg)
        hb, ha = idb > 0, ida > 0
        lost = hb & ~ha & ~AP
        deeper = hb & ha & (za > zb + THRESH) & ~AP
        gained = ha & ~hb & ~AP
        tot["before_px"] += int(hb.sum())
        tot["lost_out"] += int(lost.sum())
        tot["deeper_out"] += int(deeper.sum())
        tot["gained_out"] += int(gained.sum())
        for m, acc in ((lost, lostn), (deeper, deepn)):
            v, c = np.unique(idb[m], return_counts=True)
            for vv, cc in zip(v, c):
                acc[nb[vv - 1]] = acc.get(nb[vv - 1], 0) + int(cc)
        # what OWNS the gained pixels in the after car
        v, c = np.unique(ida[gained], return_counts=True)
        for vv, cc in zip(v, c):
            k = "GAINED:" + na[vv - 1]
            lostn[k] = lostn.get(k, 0) + int(cc)
    print(f"\n=== {tag}  ({claim})")
    print(f"  before px {tot['before_px']}  lost_out {tot['lost_out']} "
          f"({100*tot['lost_out']/tot['before_px']:.5f}%)  deeper_out "
          f"{tot['deeper_out']} ({100*tot['deeper_out']/tot['before_px']:.5f}%)"
          f"  gained_out {tot['gained_out']}")
    print("  LOST/GAINED attributed by node:")
    for k, v in sorted(lostn.items(), key=lambda x: -x[1]):
        print(f"    {k:28s} {v}")
    print("  DEEPER attributed by node:")
    for k, v in sorted(deepn.items(), key=lambda x: -x[1])[:8]:
        print(f"    {k:28s} {v}")
    out[tag] = {"totals": tot, "lost_by_node": lostn, "deeper_by_node": deepn}

json.dump(out, open("hole_attrib.json", "w"), indent=1)
print("\nwrote hole_attrib.json")
