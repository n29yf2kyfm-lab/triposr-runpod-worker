#!/usr/bin/env python3
"""fresh_import.py — import the finished GLB in a NEW Blender process and report.

Acceptance asks for a fresh import, which is a different question from "the
exporter did not raise". Prints its OWN done marker: this container's Blender
dies AFTER "Blender quit" prints when a render step fails, so Blender's exit is
not evidence (CLAUDE.md).
"""
import json, os, subprocess, sys
GLB = os.path.abspath(sys.argv[1]); OUT = os.path.abspath(sys.argv[2])
SC = OUT + ".blender.py"
open(SC, "w").write(r'''
import bpy, sys, json
argv=sys.argv[sys.argv.index("--")+1:]
GLB, OUT = argv[0], argv[1]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=GLB)
objs=[o for o in bpy.data.objects if o.type=="MESH"]
rep={"objects":len(objs),"meshes":[],"materials":sorted(m.name for m in bpy.data.materials),
     "total_tris":0,"loose_verts_total":0,"objects_without_normals":[]}
for o in objs:
    me=o.data
    me.calc_loop_triangles()
    nt=len(me.loop_triangles)
    rep["total_tris"]+=nt
    used=set()
    for p in me.polygons: used.update(p.vertices)
    loose=len(me.vertices)-len(used)
    rep["loose_verts_total"]+=loose
    has_n = any(abs(v.normal.length-1.0) < 0.5 for v in me.vertices[:200])
    if not has_n: rep["objects_without_normals"].append(o.name)
    rep["meshes"].append({"name":o.name,"verts":len(me.vertices),"tris":nt,
                          "loose_verts":loose,
                          "mats":[ms.material.name if ms.material else None for ms in o.material_slots]})
json.dump(rep, open(OUT,"w"), indent=1)
print("FRESH_IMPORT_DONE", len(objs), rep["total_tris"])
''')
r = subprocess.run(["blender", "-b", "--python", SC, "--", GLB, OUT],
                   capture_output=True, text=True)
o = r.stdout + r.stderr
if "FRESH_IMPORT_DONE" not in o:
    print(o[-3000:]); raise SystemExit("FRESH IMPORT FAILED: own marker absent")
rep = json.load(open(OUT))
print("FRESH IMPORT OK:", rep["objects"], "objects,", rep["total_tris"], "tris,",
      rep["loose_verts_total"], "loose verts,",
      "no-normal objects:", rep["objects_without_normals"] or "none")
print("materials:", rep["materials"])
