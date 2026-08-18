#!/usr/bin/env python3
"""swap_rear.py — replace the rear kit inside an ALREADY ASSEMBLED car GLB.

Re-running the whole chain to change one component is wasteful and, after a
container rollback, often impossible (the intermediates are scratch files;
the shipped car is bucket-backed). This stage swaps the rear kit's nodes —
Tail_Lens, Number_Plate, Plate_Frame — in place, leaving every other
component byte-identical.

That is the staged-assembly promise made good: components are independently
replaceable in the finished car.

Run: python3 swap_rear.py <car.glb> <rear_kit.npz> <out.glb>
"""
import sys
import numpy as np
import trimesh
from trimesh.visual.material import PBRMaterial

CAR, KIT, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
REPLACED = ("Tail_Lens", "Number_Plate", "Plate_Frame")

sc = trimesh.load(CAR, force="scene")
out = trimesh.Scene()
kept = 0
for name, g in sc.geometry.items():
    if any(name.startswith(r) for r in REPLACED):
        continue
    out.add_geometry(g, node_name=name, geom_name=name)
    kept += 1
print(f"kept {kept} components untouched, replacing {REPLACED}")

rz = np.load(KIT)
for vk, fk, name, mat in (
        ("lens_v", "lens_f", "Tail_Lens", PBRMaterial(
            name="Tail_Lens", baseColorFactor=[52, 7, 9, 255],
            metallicFactor=0.0, roughnessFactor=0.12, doubleSided=True)),
        ("frame_v", "frame_f", "Plate_Frame", PBRMaterial(
            name="Plate_Frame", baseColorFactor=[12, 12, 13, 255],
            metallicFactor=0.0, roughnessFactor=0.6, doubleSided=True)),
        ("plate_v", "plate_f", "Number_Plate", PBRMaterial(
            name="Number_Plate", baseColorFactor=[228, 228, 220, 255],
            metallicFactor=0.0, roughnessFactor=0.55, doubleSided=True))):
    if vk not in rz:
        continue
    part = trimesh.Trimesh(vertices=rz[vk], faces=rz[fk], process=True)
    part.visual = trimesh.visual.TextureVisuals(material=mat)
    out.add_geometry(part, node_name=name, geom_name=name)
    print(f"  + {name}: {len(part.faces)} faces")

out.export(OUT)
import os
print("wrote", OUT, os.path.getsize(OUT), "bytes")
