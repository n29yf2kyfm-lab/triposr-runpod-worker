#!/usr/bin/env python3
"""rear_separate.py — Stage 4: the rear becomes separate NAMED assemblies.

The brief requires the hatch, bumper, lamps, glass and trim to be
separate nodes, not one fused shell. The four lamp lenses, plate, frame
and rear glass are already separate; this stage adds:

  * Rear_Hatch    — carpaint faces in the rear zone at/above the bumper
                    cut (the same geometric cut rear_diag2 validated)
  * Rear_Bumper   — the rear zone below the cut
  * Tail_Housing_RO/RH/LO/LH — dark housing solids INBOARD of each lens
    (duplicate lens geometry pushed 15mm toward the body, so every lens
    has a housing behind it instead of floating over paint)
  * Rear_Diffuser — constructed lower trim slab under the bumper

carpaint keeps the identical paint parameters on hatch and bumper (the
stage-3 rule: one physical paint everywhere) — they are separate NODES,
same material values.

Run: python3 rear_separate.py <in.glb> <out.glb>
"""
import json
import struct
import sys
import numpy as np
import trimesh
from trimesh.visual.material import PBRMaterial

INP, OUT = sys.argv[1], sys.argv[2]

sc = trimesh.load(INP, force="scene")
cp = sc.geometry["carpaint"]
cent = cp.triangles_center
v = cp.vertices
L0, L1 = v[:, 0].min(), v[:, 0].max()
H0 = v[:, 1].min()
H = v[:, 1].max() - H0
xf = (cent[:, 0] - L0) / (L1 - L0)
rear = xf < 0.18
bumper = rear & (cent[:, 1] < H0 + 0.33 * H)
hatch = rear & ~bumper
print(f"rear split: hatch {hatch.sum()} faces, bumper {bumper.sum()} faces, "
      f"body keeps {(~rear).sum()}")

paint_mat = cp.visual.material


def submesh(mask, name):
    m = cp.copy()
    m.update_faces(mask)
    # drop zero-area faces: they produce zero-length vertex normals and
    # validator ACCESSOR_VECTOR3_NON_UNIT errors (273 found in the shell)
    tri = m.triangles
    area = np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1)
    if (area < 1e-10).any():
        m.update_faces(area >= 1e-10)
        print(f"  {name}: dropped {(area < 1e-10).sum()} degenerate faces")
    m.remove_unreferenced_vertices()
    # residual zero-length vertex normals (validator ACCESSOR_VECTOR3_NON_UNIT):
    # give them a unit fallback rather than shipping zeros
    vn = np.array(m.vertex_normals)
    bad = np.linalg.norm(vn, axis=1) < 1e-6
    if bad.any():
        vn[bad] = [0.0, 1.0, 0.0]
        m.vertex_normals = vn
        print(f"  {name}: {bad.sum()} zero normals replaced with unit fallback")
    m.visual = trimesh.visual.TextureVisuals(material=PBRMaterial(
        name=name, baseColorFactor=list(paint_mat.baseColorFactor),
        metallicFactor=float(paint_mat.metallicFactor),
        roughnessFactor=float(paint_mat.roughnessFactor)))
    return m


hatch_m = submesh(hatch, "carpaint_hatch")
# intersection gate: hatch melt pokes INSIDE the closed opaque lens solids
# (measured 42-518 verts per lens). Everything strictly enclosed by a
# watertight opaque solid is invisible by construction — cut it.
for tag in ("RO", "RH", "LO", "LH"):
    raw = sc.geometry[f"Tail_Lens_{tag}"]
    lens = trimesh.Trimesh(vertices=raw.vertices, faces=raw.faces, process=True)
    if not lens.is_watertight:
        print(f"  Tail_Lens_{tag}: not watertight after merge — cut skipped")
        continue
    hv = hatch_m.vertices
    c = lens.vertices.mean(0); ext = lens.vertices.max(0) - lens.vertices.min(0)
    cand = (np.abs(hv - c) < ext / 2 + 0.01).all(1)
    inside_v = np.zeros(len(hv), bool)
    if cand.any():
        inside_v[cand] = lens.contains(hv[cand])
    fin = inside_v[hatch_m.faces].all(1)
    if fin.any():
        hatch_m.update_faces(~fin)
        hatch_m.remove_unreferenced_vertices()
        print(f"  Tail_Lens_{tag}: cut {fin.sum()} hatch faces fully enclosed by the lens")
bump_m = submesh(bumper, "carpaint_bumper")
body_m = submesh(~rear, "carpaint")

out = trimesh.Scene()
housings = []
for node in sc.graph.nodes_geometry:
    T, gn = sc.graph[node]
    if gn == "carpaint":
        continue
    g = sc.geometry[gn]
    if gn.startswith("Tail_Lens_"):
        h = g.copy()
        c = h.vertices.mean(0)
        # push toward the body: forward (+x) and toward centreline
        d = np.array([+1.0, 0.0, -np.sign(c[2]) * 0.4])
        d /= np.linalg.norm(d)
        h.vertices = h.vertices + d * 0.015
        h.visual = trimesh.visual.TextureVisuals(material=PBRMaterial(
            name="Tail_Housing", baseColorFactor=[18, 18, 20, 255],
            metallicFactor=0.0, roughnessFactor=0.85))
        hname = gn.replace("Tail_Lens_", "Tail_Housing_")
        housings.append((hname, h))
    if gn not in out.geometry:
        out.add_geometry(g, geom_name=gn, node_name=node, transform=T)
    else:
        out.graph.update(frame_to=node, matrix=T, geometry=gn)

out.add_geometry(body_m, geom_name="carpaint", node_name="carpaint")
out.add_geometry(hatch_m, geom_name="Rear_Hatch", node_name="Rear_Hatch")
out.add_geometry(bump_m, geom_name="Rear_Bumper", node_name="Rear_Bumper")
for hname, h in housings:
    out.add_geometry(h, geom_name=hname, node_name=hname)
    print(f"  {hname}: {len(h.faces)} faces (lens copy offset 15mm inboard)")

# constructed diffuser: slab under the bumper, rear face
xr = L0 + 0.10 * (L1 - L0)
dif = trimesh.creation.box(extents=[0.10, 0.070, 1.10])
dif.apply_translation([L0 + 0.10, H0 + 0.085, 0.0])
dif.visual = trimesh.visual.TextureVisuals(material=PBRMaterial(
    name="Rear_Diffuser", baseColorFactor=[22, 22, 24, 255],
    metallicFactor=0.0, roughnessFactor=0.9))
out.add_geometry(dif, geom_name="Rear_Diffuser", node_name="Rear_Diffuser")

out.export(OUT, include_normals=True)
with open(OUT, "rb") as fh:
    fh.seek(12); ln, _ = struct.unpack("<II", fh.read(8)); j = json.loads(fh.read(ln))
missing = [m2.get("name") for m2 in j["meshes"]
           if any("NORMAL" not in p["attributes"] for p in m2["primitives"])]
if missing:
    raise SystemExit(f"REFUSED: NORMAL missing on {missing[:4]}")
names = [m2.get("name") for m2 in j["meshes"]]
need = ["Rear_Hatch", "Rear_Bumper", "Rear_Diffuser", "Tail_Housing_RO",
        "Tail_Housing_RH", "Tail_Housing_LO", "Tail_Housing_LH"]
absent = [n for n in need if n not in names]
if absent:
    raise SystemExit(f"REFUSED: nodes missing from export: {absent}")
import os
print(f"wrote {OUT} ({os.path.getsize(OUT)} bytes); rear nodes verified present")
