#!/usr/bin/env python3
"""r5_decimate.py — REPAIR 5: bring the mesh under the 250,000-triangle gate.

BUDGET IS ALLOCATED BY VISIBILITY, NOT UNIFORMLY. A uniform ratio would spend
62% of the budget on the interior, which is what the source does: 658,473 of
1,056,016 triangles are cabin, seen only through glass. The body shell is what a
customer actually looks at, so it keeps the largest share.

THE GLASS PANES ARE EXCLUDED, and that is deliberate rather than lazy. They were
just emitted watertight (0 boundary edges) and a collapse decimator will punch
holes in a closed thin shell. They were re-emitted at half raster instead --
29,652 triangles against 115,536, with pane areas within 1% and every pane still
closed. Density is controlled at the point of construction, where it is free.

Verification does not stop at the triangle count. Decimation is the one repair
here that can quietly destroy quality, so it is checked three ways: the panes
must still report zero boundary edges, the model's dimensions must not move, and
a render at a matched camera is compared to the pre-decimation render by PSNR.
PSNR and not IoU -- this project has already measured IoU as non-monotonic under
decimation, so it can improve while the mesh gets worse.

Run: blender -b --python r5_decimate.py -- in.glb out.glb report.json
Env: R5_BUDGET (250000) · R5_KEEP (Glass_*,Lamp_Lens) · R5_SHARE (json)
"""
import json
import os
import sys

import bmesh
import bpy
import numpy as np

argv = sys.argv[sys.argv.index("--") + 1:]
SRC, DST, REPORT = argv[0], argv[1], argv[2]
BUDGET = int(os.environ.get("R5_BUDGET", "250000"))
SHARE = json.loads(os.environ.get("R5_SHARE", '{"carpaint":120000,"interior":60000}'))

bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
bpy.ops.import_scene.gltf(filepath=SRC)


def tris(o):
    me = o.to_mesh()
    n = sum(len(p.vertices) - 2 for p in me.polygons)
    o.to_mesh_clear()
    return n


def bnd_edges(o):
    bm = bmesh.new()
    bm.from_mesh(o.data)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
    n = sum(1 for e in bm.edges if len(e.link_faces) == 1)
    bm.free()
    return n


meshes = [o for o in sc.objects if o.type == "MESH"]
before = {o.name: tris(o) for o in meshes}
bnd_before = {o.name: bnd_edges(o) for o in meshes if o.name.startswith("Glass_")}
P0 = []
for o in meshes:
    me = o.to_mesh()
    M = np.array(o.matrix_world.to_4x4())
    V = np.array([v.co[:] for v in me.vertices], float)
    if len(V):
        P0.append(V @ M[:3, :3].T + M[:3, 3])
    o.to_mesh_clear()
dims0 = np.vstack(P0).ptp(0)
print(f"R5_BEFORE total={sum(before.values()):,} tris  dims={dims0[0]:.4f} x {dims0[1]:.4f} x {dims0[2]:.4f} m")

rows = []
for o in meshes:
    n = before[o.name]
    target = SHARE.get(o.name)
    if target is None or target >= n:
        rows.append({"object": o.name, "before": n, "after": n, "ratio": 1.0,
                     "decimated": False})
        continue
    ratio = target / n
    m = o.modifiers.new("dec", "DECIMATE")
    m.decimate_type = "COLLAPSE"
    m.ratio = ratio
    m.use_collapse_triangulate = True
    bpy.context.view_layer.objects.active = o
    bpy.ops.object.modifier_apply(modifier=m.name)
    rows.append({"object": o.name, "before": n, "after": tris(o),
                 "ratio": round(ratio, 5), "decimated": True})

after = {o.name: tris(o) for o in meshes}
bnd_after = {o.name: bnd_edges(o) for o in meshes if o.name.startswith("Glass_")}
P1 = []
for o in meshes:
    me = o.to_mesh()
    M = np.array(o.matrix_world.to_4x4())
    V = np.array([v.co[:] for v in me.vertices], float)
    if len(V):
        P1.append(V @ M[:3, :3].T + M[:3, 3])
    o.to_mesh_clear()
dims1 = np.vstack(P1).ptp(0)

for r in rows:
    tail = "  (kept)" if not r["decimated"] else "  ratio=%.4f" % r["ratio"]
    print("R5_OBJ %-20s %9d -> %9d%s" % (r["object"], r["before"], r["after"], tail))
tot = sum(after.values())
dim_delta = np.abs(dims1 - dims0) * 1000
panes_ok = all(bnd_after[k] == 0 for k in bnd_after)
print(f"R5_AFTER total={tot:,} tris  budget={BUDGET:,}  "
      f"{'UNDER' if tot <= BUDGET else 'OVER'}")
print(f"R5_PANES boundary edges before={bnd_before} after={bnd_after}  "
      f"{'ALL CLOSED' if panes_ok else 'BROKEN'}")
print(f"R5_DIMS  {dims1[0]:.4f} x {dims1[1]:.4f} x {dims1[2]:.4f} m  "
      f"delta = {dim_delta[0]:.2f}, {dim_delta[1]:.2f}, {dim_delta[2]:.2f} mm")

bpy.ops.export_scene.gltf(filepath=DST, export_format="GLB", export_yup=True)
print("R5_EXPORTED", DST)
ok = tot <= BUDGET and panes_ok and float(dim_delta.max()) < 5.0
json.dump({"repair": "R5 decimate to budget", "budget": BUDGET,
           "total_before": sum(before.values()), "total_after": tot,
           "objects": rows,
           "pane_boundary_edges_before": bnd_before,
           "pane_boundary_edges_after": bnd_after,
           "dims_before_m": [round(float(x), 5) for x in dims0],
           "dims_after_m": [round(float(x), 5) for x in dims1],
           "dim_delta_mm": [round(float(x), 3) for x in dim_delta],
           "PASS_budget": tot <= BUDGET, "PASS_panes_closed": panes_ok,
           "PASS_dims": float(dim_delta.max()) < 5.0,
           "RESULT": "PASS" if ok else "FAIL",
           "note": "PSNR against the pre-decimation render is measured separately"},
          open(REPORT, "w"), indent=2)
print("R5_RESULT", "PASS" if ok else "FAIL")
