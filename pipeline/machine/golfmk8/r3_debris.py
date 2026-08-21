#!/usr/bin/env python3
"""r3_debris.py — REPAIR 3: find and remove floating debris.

A spike protrudes from the roof in 6 of the 8 baseline views. This locates it
and everything like it by MEASUREMENT rather than by eye, then removes only what
survives three independent tests, because deleting car geometry is unrecoverable
and 'small and detached' alone is not evidence of junk (a badge, a door handle
and a wiper are all small and may be detached).

A component is debris only if ALL of:
  * it is DISCONNECTED from its object's main body,
  * its surface area is below AREA_CM2, and
  * it is an OUTLIER -- outside the car's own silhouette envelope, measured as
    the convex profile of the largest component per object, with a margin.

The third test is what stops it eating trim. A roof aerial that genuinely sits
proud of the roofline is exactly what we want removed here; a door handle sits
INSIDE the envelope and survives.

Run: blender -b --python r3_debris.py -- in.glb out.glb report.json
Env: R3_AREA_CM2 (60) · R3_MARGIN_MM (12) · R3_DRYRUN (0)
"""
import json
import os
import sys

import bmesh
import bpy
import numpy as np

argv = sys.argv[sys.argv.index("--") + 1:]
SRC, DST, REPORT = argv[0], argv[1], argv[2]
AREA_CM2 = float(os.environ.get("R3_AREA_CM2", "60"))
MARGIN = float(os.environ.get("R3_MARGIN_MM", "12")) / 1000.0
DRY = os.environ.get("R3_DRYRUN", "0") == "1"

bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
bpy.ops.import_scene.gltf(filepath=SRC)

meshes = [o for o in sc.objects if o.type == "MESH"]
# envelope = the union silhouette of every object's LARGEST component, which is
# the car proper. Built once, in world space, as a coarse z-by-x height field so
# a spike above the roof is detectable without a convex hull library.
NX, NY = 96, 48
allP = []
for o in meshes:
    me = o.to_mesh()
    M = np.array(o.matrix_world.to_4x4())
    V = np.array([v.co[:] for v in me.vertices], dtype=float)
    if len(V):
        allP.append(V @ M[:3, :3].T + M[:3, 3])
    o.to_mesh_clear()
P = np.vstack(allP)
lo, hi = P.min(0), P.max(0)


def cells(Q):
    ix = np.clip(((Q[:, 0] - lo[0]) / max(hi[0] - lo[0], 1e-9) * (NX - 1)).astype(int), 0, NX - 1)
    iy = np.clip(((Q[:, 1] - lo[1]) / max(hi[1] - lo[1], 1e-9) * (NY - 1)).astype(int), 0, NY - 1)
    return ix, iy


report = {"repair": "R3 floating debris", "objects": [], "removed": [], "kept_suspicious": []}
main_pts = []
per_obj = {}
for o in meshes:
    bm = bmesh.new()
    bm.from_mesh(o.data)
    bm.transform(o.matrix_world)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    bm.faces.ensure_lookup_table()
    seen, comps = set(), []
    for f in bm.faces:
        if f.index in seen:
            continue
        st, fs = [f], []
        seen.add(f.index)
        while st:
            c = st.pop()
            fs.append(c)
            for e in c.edges:
                for nf in e.link_faces:
                    if nf.index not in seen:
                        seen.add(nf.index)
                        st.append(nf)
        area = sum(x.calc_area() for x in fs)
        pts = np.array([[v.co[0], v.co[1], v.co[2]] for x in fs for v in x.verts])
        comps.append({"faces": [x.index for x in fs], "area": area, "pts": pts})
    comps.sort(key=lambda c: -c["area"])
    if comps:
        main_pts.append(comps[0]["pts"])
    per_obj[o.name] = (bm, comps)
    report["objects"].append({"object": o.name, "components": len(comps),
                              "largest_area_cm2": round(comps[0]["area"] * 1e4, 1) if comps else 0})

# height envelope from the main bodies only
Z = np.full((NX, NY), -1e18)
Q = np.vstack(main_pts)
ix, iy = cells(Q)
np.maximum.at(Z, (ix, iy), Q[:, 2])
Zf = np.where(np.isfinite(Z) & (Z > -1e17), Z, np.nan)

total_removed = 0
for o in meshes:
    bm, comps = per_obj[o.name]
    kill = []
    for c in comps[1:]:
        a_cm2 = c["area"] * 1e4
        cx, cy = cells(c["pts"])
        env = Zf[cx, cy]
        above = c["pts"][:, 2] - env
        outlier = np.nanmax(above) if np.isfinite(env).any() else 0.0
        is_small = a_cm2 < AREA_CM2
        is_out = outlier > MARGIN
        rec = {"object": o.name, "area_cm2": round(a_cm2, 2),
               "protrudes_above_envelope_mm": round(float(outlier) * 1000, 1),
               "centroid": [round(float(x), 3) for x in c["pts"].mean(0)]}
        if is_small and is_out:
            kill += c["faces"]
            report["removed"].append(rec)
            total_removed += 1
        elif is_out:
            report["kept_suspicious"].append(dict(rec, reason="protrudes but area >= cap"))
    if kill and not DRY:
        bm.faces.ensure_lookup_table()
        geom = [bm.faces[i] for i in kill if i < len(bm.faces)]
        bmesh.ops.delete(bm, geom=geom, context="FACES")
        bm.transform(o.matrix_world.inverted())
        bm.to_mesh(o.data)
    bm.free()

for r in report["removed"]:
    print(f"R3_REMOVE {r['object']:14s} area={r['area_cm2']:8.2f}cm2 "
          f"protrudes={r['protrudes_above_envelope_mm']:7.1f}mm at {r['centroid']}")
for r in report["kept_suspicious"]:
    print(f"R3_KEEP   {r['object']:14s} area={r['area_cm2']:8.2f}cm2 "
          f"protrudes={r['protrudes_above_envelope_mm']:7.1f}mm  ({r['reason']})")
print(f"R3_TOTAL removed {total_removed} components"
      f"{' (DRY RUN, nothing written)' if DRY else ''}")

if not DRY:
    bpy.ops.export_scene.gltf(filepath=DST, export_format="GLB", export_yup=True)
    print("R3_EXPORTED", DST)
report["removed_count"] = total_removed
report["dry_run"] = DRY
json.dump(report, open(REPORT, "w"), indent=2)
print("R3_DONE")
