#!/usr/bin/env python3
"""paint_lock.py — Stage 3: one physically consistent automotive paint.

The baseline carpaint carries a PHOTO-PROJECTION BAKED texture: capture
lighting is embedded in base colour, which is exactly what the brief
forbids ("no baked showroom illumination in base colour"). It is why
broad panels read saturated red in one view and blown-out white in
another — the highlight is painted INTO the albedo, so no exposure
setting can equalise it.

This stage:
  * measures the paint colour FROM the texture (median of red-dominant
    texels — value source: calculated, not an OEM code)
  * converts sRGB -> linear and writes it as a flat baseColorFactor
  * metallic 0, roughness 0.24 (clearcoat is re-applied afterwards by
    materials_pass — trimesh cannot write KHR_materials_clearcoat)
  * drops the texture from the export entirely

Trade recorded, not hidden: the photo bake also carried badge and grille
detail. That identity now lives only in component geometry. This is the
respray-base variant and the correct base for the colour system.

Run: python3 paint_lock.py <in.glb> <out.glb>
"""
import json
import os
import struct
import sys
import numpy as np
import trimesh
from trimesh.visual.material import PBRMaterial

INP, OUT = sys.argv[1], sys.argv[2]

sc = trimesh.load(INP, force="scene")
cp = sc.geometry["carpaint"]
tex = getattr(cp.visual.material, "baseColorTexture", None)
if tex is None:
    raise SystemExit("carpaint has no texture — nothing to lock")
img = np.asarray(tex.convert("RGB")).reshape(-1, 3).astype(float)
red = (img[:, 0] > img[:, 1] + 25) & (img[:, 0] > img[:, 2] + 25)
if red.sum() < 1000:
    raise SystemExit(f"only {red.sum()} red-dominant texels — refusing to guess a colour")
med = np.median(img[red], axis=0)
p95 = np.percentile(img[red][:, 0], 95)
print(f"paint sample: {red.sum()} red-dominant texels of {len(img)}; "
      f"median sRGB {med.round(1)}; R p95 {p95:.0f}")


def s2l(c):
    c = c / 255.0
    return float(c / 12.92) if c <= 0.04045 else float(((c + 0.055) / 1.055) ** 2.4)


lin = [round(s2l(v), 5) for v in med]
print(f"baseColorFactor (linear) = {lin}")

cp.visual = trimesh.visual.TextureVisuals(material=PBRMaterial(
    name="carpaint", baseColorFactor=lin + [1.0],
    metallicFactor=0.0, roughnessFactor=0.24))

out = trimesh.Scene()
for node in sc.graph.nodes_geometry:
    T, gn = sc.graph[node]
    if gn not in out.geometry:
        out.add_geometry(sc.geometry[gn], geom_name=gn, node_name=node, transform=T)
    else:
        out.graph.update(frame_to=node, matrix=T, geometry=gn)
out.export(OUT, include_normals=True)

with open(OUT, "rb") as fh:
    fh.seek(12); ln, _ = struct.unpack("<II", fh.read(8)); j = json.loads(fh.read(ln))
cpm = [m for m in j["materials"] if m.get("name") == "carpaint"][0]
if "baseColorTexture" in cpm.get("pbrMetallicRoughness", {}):
    raise SystemExit("REFUSED: baked texture survived the export")
missing = [m2.get("name") for m2 in j["meshes"]
           if any("NORMAL" not in p["attributes"] for p in m2["primitives"])]
if missing:
    raise SystemExit(f"REFUSED: NORMAL missing on {missing[:4]}")
print(f"wrote {OUT} ({os.path.getsize(OUT)} bytes); images left: {len(j.get('images', []))}; "
      f"carpaint factor {cpm['pbrMetallicRoughness'].get('baseColorFactor')}")
