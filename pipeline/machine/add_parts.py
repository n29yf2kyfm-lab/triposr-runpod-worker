#!/usr/bin/env python3
"""add_parts.py — add/replace named component kits inside an assembled car.

Generic component installer: reads a kit npz whose `manifest` (JSON) lists
parts with their mesh keys and PBR params, strips any existing nodes with
the same names, and installs the new ones. The staged-assembly contract:
every component independently replaceable in the finished car.

Run: python3 add_parts.py <car.glb> <kit.npz> <out.glb>
"""
import json
import sys
import numpy as np
import trimesh
from trimesh.visual.material import PBRMaterial

CAR, KIT, OUT = sys.argv[1], sys.argv[2], sys.argv[3]

rz = np.load(KIT)
manifest = json.loads(bytes(rz["manifest"]).decode())
names = {p["name"] for p in manifest}

sc = trimesh.load(CAR, force="scene")
out = trimesh.Scene()
kept = 0
# GRAPH-PRESERVING copy (forensic fix 2026-08-19, same class as swap_rear):
# a geometry-items rebuild collapses instanced nodes — wheel_stage's four
# wheel transforms on one master mesh became a single origin node and
# three wheels vanished. Copy the node graph.
for node in sc.graph.nodes_geometry:
    T, gn = sc.graph[node]
    if node in names or gn in names:
        continue
    if gn not in out.geometry:
        out.add_geometry(sc.geometry[gn], geom_name=gn, node_name=node,
                         transform=T)
    else:
        out.graph.update(frame_to=node, matrix=T, geometry=gn)
    kept += 1

for p in manifest:
    m = trimesh.Trimesh(vertices=rz[p["v"]], faces=rz[p["f"]], process=True)
    mat = PBRMaterial(name=p["name"], baseColorFactor=list(p["color"]) + [255],
                      metallicFactor=p.get("metallic", 0.0),
                      roughnessFactor=p.get("rough", 0.8),
                      doubleSided=bool(p.get("doubleSided", False)))
    m.visual = trimesh.visual.TextureVisuals(material=mat)
    out.add_geometry(m, node_name=p["name"], geom_name=p["name"])

out.export(OUT)
import os
print(f"kept {kept}, installed {len(manifest)} parts -> {OUT} "
      f"({os.path.getsize(OUT)} bytes)")
