#!/usr/bin/env python3
"""matid_glb.py -- one distinct EMISSIVE colour per source mesh.
Emission removes lighting from the answer, so a pixel's colour names exactly
which mesh won the ray at that pixel.  This is how the fighting PAIR is
identified without guessing.
"""
import sys, json, colorsys
import numpy as np, trimesh
CAR, OUT = sys.argv[1], sys.argv[2]
sc = trimesh.load(CAR, process=False, force='scene')
# graph-preserving loop: a multi-primitive GLB names its NODES differently
# from its geometries, so sc.graph.get(geom_name) raises "No path from world".
# CLAUDE.md's instance-collapse rule: iterate graph.nodes_geometry.
nodes = list(sc.graph.nodes_geometry)
names = [sc.graph[nd][1] for nd in nodes]
out = trimesh.Scene(); leg = {}
for i, nd in enumerate(nodes):
    T, n = sc.graph[nd]; m = sc.geometry[n]
    r, g, b = colorsys.hsv_to_rgb((i * 0.379) % 1.0, 0.55 + 0.45 * ((i % 3) / 2), 1.0)
    leg[nd] = [round(r, 4), round(g, 4), round(b, 4)]
    mat = trimesh.visual.material.PBRMaterial(
        name=f"ID_{nd}", baseColorFactor=[0, 0, 0, 1], metallicFactor=0.0,
        roughnessFactor=1.0, emissiveFactor=[r, g, b], doubleSided=True)
    gm = trimesh.Trimesh(vertices=m.vertices.copy(), faces=m.faces.copy(), process=False)
    gm.visual = trimesh.visual.TextureVisuals(material=mat)
    out.add_geometry(gm, node_name=nd, geom_name=nd, transform=T)
out.export(OUT)
json.dump(leg, open(OUT + '.legend.json', 'w'), indent=1)
print("[matid_glb]", OUT, len(names), "meshes")
