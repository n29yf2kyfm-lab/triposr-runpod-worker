#!/usr/bin/env python3
"""surf_quality.py — measure panel surface quality in millimetres.

The owner's "shit paint job" is a GEOMETRY complaint, not a material one: the
blotchy reflections across the doors and quarters are the specular image of a
rippled panel. There is no point adjusting a material to fix that.

Two metrics, because one of them is a trap.

The umbrella-operator residual (distance from a vertex to the mean of its
one-ring) is reported in mm and is intuitive -- but it SCALES WITH EDGE LENGTH.
A coarse mesh over a genuinely smooth curved panel produces large residuals for
no other reason than that its neighbours are far away, so decimating a car makes
this number worse without making the car worse. It is reported normalised by
mean edge length as well, which removes that.

DIHEDRAL ANGLE between adjacent faces is the honest witness and is scale-free.
A smooth panel holds a few degrees between neighbouring faces regardless of
tessellation; ripples, faceting and dents show up directly.

Run: blender -b --python surf_quality.py -- in.glb [obj1,obj2,...]
"""
import json
import sys

import bmesh
import bpy
import numpy as np

argv = sys.argv[sys.argv.index("--") + 1:]
SRC = argv[0]
ONLY = set(argv[1].split(",")) if len(argv) > 1 else {"carpaint"}

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=SRC)

out = {}
for o in bpy.context.scene.objects:
    if o.type != "MESH" or o.name not in ONLY:
        continue
    bm = bmesh.new()
    bm.from_mesh(o.data)
    bm.transform(o.matrix_world)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    bm.verts.ensure_lookup_table()
    P = np.array([v.co[:] for v in bm.verts], dtype=float)
    lap = np.zeros(len(bm.verts))
    for i, v in enumerate(bm.verts):
        nb = v.link_edges
        if len(nb) < 3:
            continue
        m = np.mean([[c.other_vert(v).co[k] for k in range(3)] for c in nb], axis=0)
        lap[i] = np.linalg.norm(P[i] - m)
    L = lap[lap > 0] * 1000.0
    if not len(L):
        continue
    elen = np.mean([e.calc_length() for e in bm.edges]) * 1000.0
    dih = np.array([np.degrees(e.calc_face_angle_signed(0.0))
                    for e in bm.edges if len(e.link_faces) == 2])
    dih = np.abs(dih)
    out[o.name] = {
        "verts": int(len(L)),
        "mean_mm": round(float(L.mean()), 4),
        "median_mm": round(float(np.median(L)), 4),
        "p90_mm": round(float(np.percentile(L, 90)), 4),
        "p99_mm": round(float(np.percentile(L, 99)), 4),
        "max_mm": round(float(L.max()), 3),
        "frac_over_0p5mm": round(float((L > 0.5).mean()), 5),
        "frac_over_1mm": round(float((L > 1.0).mean()), 5),
        "frac_over_2mm": round(float((L > 2.0).mean()), 5),
        "mean_edge_mm": round(float(elen), 3),
        "residual_over_edge": round(float(L.mean() / elen), 4),
        "dihedral_mean_deg": round(float(dih.mean()), 3),
        "dihedral_median_deg": round(float(np.median(dih)), 3),
        "dihedral_p90_deg": round(float(np.percentile(dih, 90)), 3),
        "dihedral_p99_deg": round(float(np.percentile(dih, 99)), 3),
        "frac_dihedral_over_10deg": round(float((dih > 10).mean()), 5),
        "frac_dihedral_over_30deg": round(float((dih > 30).mean()), 5),
    }
    bm.free()
print("SURFQ=" + json.dumps(out))
