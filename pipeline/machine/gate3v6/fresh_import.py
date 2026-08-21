"""fresh_import.py -- FRESH-IMPORT test of an exported GLB, in a NEW Blender.

Independent verification: this process never sees the builder's scene.  It
starts from factory settings, imports the exported GLB, records what actually
arrived (objects, hierarchy, materials, world-space dimensions, orientation,
transforms) and renders it.

It also provides the COMPONENTS-OFF render that corroborates the hidden-fascia
ray probe: `--drop built` deletes every object that is not one of the six
original shell labels, and renders what is left.  If the old melt was deleted
there is a HOLE where the fascia was.  If it was merely covered, the melt is
still sitting there in plain view.

Blender here is 4.0.2: CYCLES only (no EGL), NO OpenImageDenoiser -- so
use_denoising must stay False or the render raises AFTER "Blender quit" prints
and leaves a stale frame behind.  Wait on FRESH_IMPORT_DONE, never on Blender's
own exit line.

Azimuth for THIS file (nose at -X, verified independently by two agents):
  az 270 = straight front, az 215 / 305 = front three-quarters, az 90 = rear.
That is the INVERSE of the canon mapping in CLAUDE.md -- do not "correct" it.

Run:
  blender -b --python fresh_import.py -- IN.glb OUTDIR TAG [views] [drop]
    views : csv from front,f34r,f34l,side,rear,topq   (default front,f34r,f34l)
    drop  : "" | "built" | csv of substrings to delete before rendering
"""
import json
import math
import os
import sys

import bpy
import mathutils

argv = sys.argv[sys.argv.index("--") + 1:]
INP, OUT, TAG = argv[0], argv[1], argv[2]
VIEWS = (argv[3] if len(argv) > 3 else "front,f34r,f34l").split(",")
DROP = argv[4] if len(argv) > 4 else ""
os.makedirs(OUT, exist_ok=True)

SHELL = {"carpaint", "interior", "glass", "Tyre_Rubber", "Rim_Alloy", "Lamp_Lens"}

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=INP)

REP = {"file": INP, "tag": TAG, "blender": bpy.app.version_string, "objects": {},
       "materials": {}, "dropped": [], "views": {}}

for o in bpy.data.objects:
    if o.type != 'MESH':
        continue
    m = o.data
    sc = o.matrix_world.to_scale()
    REP["objects"][o.name] = {
        "parent": o.parent.name if o.parent else None,
        "vertices": len(m.vertices), "polygons": len(m.polygons),
        "materials": [ms.material.name if ms.material else None for ms in o.material_slots],
        "world_scale": [round(v, 6) for v in sc],
        "negative_scale": bool(sc.x * sc.y * sc.z < 0),
        "matrix_is_identity": bool(o.matrix_world == mathutils.Matrix.Identity(4)),
        "has_custom_normals": bool(m.has_custom_normals),
        "loose_verts": int(sum(1 for v in m.vertices if not any(
            v.index in e.vertices for e in m.edges[:0]))) if False else None,
    }

for mat in bpy.data.materials:
    d = {"use_nodes": mat.use_nodes}
    if mat.use_nodes:
        b = mat.node_tree.nodes.get("Principled BSDF")
        if b:
            d["base_color"] = [round(v, 4) for v in b.inputs["Base Color"].default_value]
            for k in ("Metallic", "Roughness", "Alpha", "IOR"):
                if k in b.inputs:
                    d[k.lower()] = round(b.inputs[k].default_value, 4)
            d["base_color_textured"] = bool(b.inputs["Base Color"].links)
    d["blend_method"] = getattr(mat, "blend_method", None)
    REP["materials"][mat.name] = d

if DROP:
    keys = ([k for k in bpy.data.objects.keys() if k.split(".")[0] not in SHELL]
            if DROP == "built" else None)
    for o in list(bpy.data.objects):
        if o.type != 'MESH':
            continue
        hit = (o.name in keys) if keys is not None else any(
            k.lower() in o.name.lower() for k in DROP.split(",") if k)
        if hit:
            REP["dropped"].append(o.name)
            bpy.data.objects.remove(o, do_unlink=True)

meshes = [o for o in bpy.data.objects if o.type == 'MESH']
mn = mathutils.Vector((1e9,) * 3)
mx = mathutils.Vector((-1e9,) * 3)
for o in meshes:
    for c in o.bound_box:
        w = o.matrix_world @ mathutils.Vector(c)
        mn = mathutils.Vector(map(min, mn, w))
        mx = mathutils.Vector(map(max, mx, w))
ctr = (mn + mx) / 2
size = max(mx - mn)
REP["world_bbox_min"] = [round(v, 5) for v in mn]
REP["world_bbox_max"] = [round(v, 5) for v in mx]
REP["dimensions_m"] = {"length_x": round(mx.x - mn.x, 5),
                       "width_y": round(mx.y - mn.y, 5),
                       "height_z": round(mx.z - mn.z, 5)}
REP["ground_min_z_mm"] = round(mn.z * 1000, 2)
nose = mathutils.Vector((mn.x + 0.45, ctr.y, mn.z + 0.36 * (mx.z - mn.z)))

scn = bpy.context.scene
scn.render.engine = 'CYCLES'
scn.cycles.device = 'CPU'
scn.cycles.samples = int(os.environ.get("G3V6_SAMPLES", "36"))
scn.cycles.use_denoising = False           # NO OIDN here -- leave it off
scn.view_settings.view_transform = 'Standard'   # never AgX: it has clipped to white
scn.render.resolution_x = 1100
scn.render.resolution_y = 760
scn.render.film_transparent = False

world = bpy.data.worlds.new("w")
world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (0.62, 0.62, 0.64, 1)
world.node_tree.nodes["Background"].inputs[1].default_value = 0.55
scn.world = world
sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
scn.collection.objects.link(sun)
sun.data.energy = 2.0
sun.data.angle = math.radians(8)
sun.rotation_euler = (math.radians(48), 0, math.radians(40))
fill = bpy.data.objects.new("fill", bpy.data.lights.new("fill", "SUN"))
scn.collection.objects.link(fill)
fill.data.energy = 0.6
fill.rotation_euler = (math.radians(60), 0, math.radians(-120))

cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
scn.collection.objects.link(cam)
scn.camera = cam
cam.data.type = 'ORTHO'

ALLVIEWS = {                      # name: (az, elev, ortho width m, aim)
    "front": (270, 4, 2.30, "nose"),
    "f34r": (305, 10, 2.60, "nose"),
    "f34l": (215, 10, 2.60, "nose"),
    "lowq": (285, -8, 2.20, "nose"),
    "side": (0, 2, 4.70, "ctr"),
    "rear": (90, 8, 2.60, "ctr"),
    "topq": (280, 45, 2.40, "nose"),
}

for name in VIEWS:
    if name not in ALLVIEWS:
        continue
    az, el, ow, aim = ALLVIEWS[name]
    a, e = math.radians(az), math.radians(el)
    target = {"nose": nose, "ctr": ctr}[aim]
    cam.data.ortho_scale = ow
    d = size * 2.2
    cam.location = (target.x + d * math.cos(e) * math.sin(a),
                    target.y - d * math.cos(e) * math.cos(a),
                    target.z + d * math.sin(e))
    cam.rotation_euler = (mathutils.Vector(target) - cam.location
                          ).to_track_quat('-Z', 'Y').to_euler()
    fp = os.path.join(OUT, f"{TAG}_{name}.png")
    scn.render.filepath = fp
    bpy.ops.render.render(write_still=True)
    REP["views"][name] = {"file": fp, "az": az, "el": el, "ortho_m": ow}
    print("WROTE", fp)

with open(os.path.join(OUT, f"{TAG}_import.json"), "w") as fh:
    json.dump(REP, fh, indent=1)
print("OBJECTS:", sorted(REP["objects"]))
print("DIMS:", REP["dimensions_m"])
print("FRESH_IMPORT_DONE")
