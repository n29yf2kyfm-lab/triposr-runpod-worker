#!/usr/bin/env python3
"""r7_remesh.py — REPAIR 7: REJECTED. DO NOT USE. Kept as evidence.

VERDICT, measured at 10 mm and 6 mm voxels and confirmed by render:
  * it does NOT produce one surface -- 4,194 components became 1,213, i.e. 1,213
    separate closed BLOBS, because each fragment gets sealed into its own volume
    rather than joined to its neighbours;
  * it loses 134 mm of vehicle HEIGHT (bbox z 1.4263 -> 1.2926 m);
  * it destroys the UVs and therefore the paint -- the rendered car comes back
    grey, not red;
  * the surface is scabbed with shell-within-shell crust;
  * triangles explode 120k -> 376k (10 mm) or 1.33M (6 mm), against a 250k gate.

Voxel remeshing closes boundaries only in the trivial sense of sealing each
fragment separately. It cannot bridge a 7 mm gap between two fragments that
belong to the same panel, because the SDF has no way to know they are the same
panel.

--- original intent, retained below ---

REPAIR 7: rebuild the shell as ONE CLOSED SURFACE by remeshing.

WHY THIS AND NOT WELDING. gap_survey measured the shell's 4,194 components and
76,968 boundary vertices: the median distance from a boundary vertex to the
nearest boundary vertex of a DIFFERENT component is 6.99 mm, only 1.64% are truly
coincident, and 46% have no different-component neighbour within 10 mm at all.
The gaps are REAL MISSING SURFACE, not a bookkeeping artefact, so no weld
tolerance fixes them: 1 mm merges 19%, and 7 mm would deform the car.

Voxel remeshing is the one in-place operation that closes real gaps -- it
resamples the whole shell onto a signed-distance field and emits a single closed
manifold. That is exactly what the paint, the A-pillar crease and the front end
all need, because every one of them is a symptom of the surface being open.

THE COST IS KNOWN IN ADVANCE AND IS THE WHOLE RISK. Voxel size sets the finest
feature that survives, and this project has already measured the ceiling: a
1024-cube over a 4.5 m car is 4.4 mm per voxel, while real shut lines are 2-4 mm,
so they cannot be resolved. This shell's shut lines are already torn, so little
is lost there -- but grille slats, lamp internals and badge relief are the same
scale and WILL soften. The sweep therefore reports, per voxel size, both what is
gained (components -> 1, boundary edges -> 0) and what is paid (triangle count,
dihedral, and a render for the eye).

Run: blender -b --python r7_remesh.py -- in.glb out.glb report.json
Env: R7_VOXEL_MM (6) · R7_OBJ (carpaint) · R7_SMOOTH (1)
"""
import json
import os
import sys

import bmesh
import bpy
import numpy as np

argv = sys.argv[sys.argv.index("--") + 1:]
SRC, DST, REPORT = argv[0], argv[1], argv[2]
VOX = float(os.environ.get("R7_VOXEL_MM", "6")) / 1000.0
OBJ = os.environ.get("R7_OBJ", "carpaint")
SMOOTH = os.environ.get("R7_SMOOTH", "1") == "1"

bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
bpy.ops.import_scene.gltf(filepath=SRC)
o = next((x for x in sc.objects if x.name == OBJ), None)
if o is None:
    raise SystemExit(f"R7_FAIL: no object {OBJ}")


def stats(ob):
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bm.transform(ob.matrix_world)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
    bm.faces.ensure_lookup_table()
    seen, comps = set(), 0
    for f in bm.faces:
        if f.index in seen:
            continue
        comps += 1
        st = [f]
        seen.add(f.index)
        while st:
            c = st.pop()
            for e in c.edges:
                for nf in e.link_faces:
                    if nf.index not in seen:
                        seen.add(nf.index)
                        st.append(nf)
    bnd = sum(1 for e in bm.edges if len(e.link_faces) == 1)
    d = np.abs(np.array([np.degrees(e.calc_face_angle_signed(0.0))
                         for e in bm.edges if len(e.link_faces) == 2]))
    tris = sum(len(p.vertices) - 2 for p in ob.data.polygons)
    P = np.array([v.co[:] for v in bm.verts], float)
    bb = P.max(0) - P.min(0)
    bm.free()
    return {"triangles": tris, "components": comps, "boundary_edges": bnd,
            "dihedral_mean_deg": round(float(d.mean()), 3),
            "dihedral_p90_deg": round(float(np.percentile(d, 90)), 3),
            "bbox_m": [round(float(x), 4) for x in bb]}


before = stats(o)
print(f"R7_BEFORE {OBJ} {before}")

m = o.modifiers.new("remesh", "REMESH")
m.mode = "VOXEL"
m.voxel_size = VOX
m.use_smooth_shade = SMOOTH
bpy.context.view_layer.objects.active = o
bpy.ops.object.modifier_apply(modifier=m.name)

after = stats(o)
print(f"R7_AFTER  {OBJ} {after}")
db = [round(a - b, 4) for a, b in zip(after["bbox_m"], before["bbox_m"])]
print(f"R7_VOXEL  {VOX*1000:.1f} mm   bbox delta {db} m")
print(f"R7_CLOSED components {before['components']} -> {after['components']}, "
      f"boundary edges {before['boundary_edges']:,} -> {after['boundary_edges']:,}")

bpy.ops.export_scene.gltf(filepath=DST, export_format="GLB", export_yup=True)
print("R7_EXPORTED", DST)
closed = after["components"] == 1 and after["boundary_edges"] == 0
json.dump({"repair": "R7 voxel remesh", "object": OBJ, "voxel_mm": VOX * 1000,
           "before": before, "after": after, "bbox_delta_m": db,
           "PASS_single_closed_surface": closed,
           "note": "a PASS here is topological only; the render decides quality"},
          open(REPORT, "w"), indent=2)
print("R7_RESULT", "CLOSED" if closed else "NOT-CLOSED")
