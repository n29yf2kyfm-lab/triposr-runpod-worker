#!/usr/bin/env python3
"""diag_glb.py -- write a diagnostic GLB with a face subset recoloured.

The point is to test whether the DETECTED doubled set coincides with the
SPECKLE seen in the render.  A detector that flags a set nobody can see, or
that misses the visible defect, is not measuring the defect.

Usage: diag_glb.py <car.glb> <mask.npy(bool, world face order)> <out.glb>
                   [--colour 1,0,1] [--rest 0.55]
Face order is the concatenation order of scene.geometry, same as dbl.py.
"""
import sys
import numpy as np
import trimesh

CAR, MASK, OUT = sys.argv[1], sys.argv[2], sys.argv[3]


def opt(f, d):
    return sys.argv[sys.argv.index(f) + 1] if f in sys.argv else d


COL = [float(x) for x in opt("--colour", "1,0,1").split(",")]
REST = float(opt("--rest", "0.55"))

sc = trimesh.load(CAR, process=False, force="scene")
mask = np.load(MASK)
names = list(sc.geometry.keys())
out = trimesh.Scene()
off = 0
hot = trimesh.visual.material.PBRMaterial(
    name="DBL_HOT", baseColorFactor=[COL[0], COL[1], COL[2], 1.0],
    metallicFactor=0.0, roughnessFactor=1.0, emissiveFactor=[c * 0.6 for c in COL],
    doubleSided=True)
cold = trimesh.visual.material.PBRMaterial(
    name="DBL_COLD", baseColorFactor=[REST, REST, REST, 1.0],
    metallicFactor=0.0, roughnessFactor=0.85, doubleSided=True)

nhot = 0
for n in names:
    m = sc.geometry[n]
    T, _ = sc.graph.get(n)
    nf = len(m.faces)
    sub = mask[off:off + nf]
    off += nf
    for tag, sel, mat in (("hot", sub, hot), ("cold", ~sub, cold)):
        if not sel.any():
            continue
        g = trimesh.Trimesh(vertices=m.vertices.copy(), faces=m.faces[sel], process=True)
        g.visual = trimesh.visual.TextureVisuals(material=mat)
        out.add_geometry(g, node_name=f"{n}__{tag}", geom_name=f"{n}__{tag}",
                         transform=T)
        if tag == "hot":
            nhot += int(sel.sum())
assert off == len(mask), (off, len(mask))
out.export(OUT)
print(f"[diag_glb] {OUT}: {nhot} hot faces of {len(mask)} ({100*nhot/len(mask):.3f}%)")
