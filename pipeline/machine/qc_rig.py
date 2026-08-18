#!/usr/bin/env python3
"""qc_rig.py — LOCKED comparison render rig for the V41+ repair mission.

Every before/after in the evidence chain renders through THIS rig with
THIS config, so comparisons are camera-identical by construction:
identical camera transforms, resolution, focal length, environment, sun,
exposure, colour management, ground plane and engine settings. The
camera transforms are ABSOLUTE: computed once from the locked baseline's
bounding box and frozen into the config file — later edits to the car
can never move the cameras.

Ground: y=0 checker grid, 0.25 m squares — a measurable reference the
wheel/ground gates can be read against.

Config: qc_rig.json next to the output (created on first run, then
reused verbatim). This Blender has no OIDN — denoising stays OFF.

Run: blender -b --python qc_rig.py -- <in.glb> <outdir> <config.json> [only:cam1,cam2]
"""
import bpy
import json
import math
import os
import sys
import mathutils

argv = sys.argv[sys.argv.index("--") + 1:]
GLB, OUTD, CFG = argv[0], argv[1], argv[2]
ONLY, WIRE = None, False
for a in argv[3:]:
    if a.startswith("only:"):
        ONLY = a.split(":", 1)[1].split(",")
    elif a == "wire":
        WIRE = True
os.makedirs(OUTD, exist_ok=True)

DEFAULT = {
    "resolution": [1280, 800], "samples": 48, "engine": "CYCLES",
    "view_transform": "Standard", "exposure": 0.0,
    "world_rgb": [0.72, 0.72, 0.74],
    "sun": {"energy": 3.0, "angle_deg": 0.5, "euler_deg": [45, 0, 160]},
    "ground": {"y": 0.0, "size": 14.0, "check_m": 0.25,
               "c1": [0.62, 0.62, 0.64], "c2": [0.52, 0.52, 0.54]},
    "cameras": {}          # filled with ABSOLUTE transforms on first run
}
CAMSPEC = [  # name, az, el, ortho_scale (None = persp 50mm)
    ("front_ortho", 90, 2, 2.8), ("rear_ortho", 270, 2, 2.8),
    ("left_ortho", 180, 2, 5.2), ("right_ortho", 0, 2, 5.2),
    ("top_ortho", 0, 89.9, 5.2),
    ("f34_L", 145, 14, None), ("f34_R", 35, 14, None),
    ("r34_L", 215, 14, None), ("r34_R", 305, 14, None),
]

cfg = json.load(open(CFG)) if os.path.exists(CFG) else dict(DEFAULT)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=GLB)
meshes = [o for o in bpy.data.objects if o.type == 'MESH']

if not cfg["cameras"]:
    mn = mathutils.Vector((1e9,) * 3); mx = mathutils.Vector((-1e9,) * 3)
    for o in meshes:
        for c in o.bound_box:
            w = o.matrix_world @ mathutils.Vector(c)
            mn = mathutils.Vector(map(min, mn, w))
            mx = mathutils.Vector(map(max, mx, w))
    ctr = (mn + mx) / 2; size = max(mx - mn)
    for name, az, el, osc in CAMSPEC:
        a, e = math.radians(az), math.radians(el); d = size * 1.6
        loc = (ctr.x + d * math.cos(e) * math.sin(a),
               ctr.y - d * math.cos(e) * math.cos(a),
               ctr.z + d * math.sin(e))
        rot = (mathutils.Vector(ctr) - mathutils.Vector(loc)
               ).to_track_quat('-Z', 'Y').to_euler()
        cfg["cameras"][name] = {"loc": list(loc), "rot": [rot.x, rot.y, rot.z],
                                "ortho": osc}
    json.dump(cfg, open(CFG, "w"), indent=1)
    print("RIG_LOCKED: absolute camera transforms written to", CFG)

scn = bpy.context.scene
scn.render.engine = cfg["engine"]
scn.cycles.device = 'CPU'; scn.cycles.samples = cfg["samples"]
scn.cycles.use_denoising = False
scn.view_settings.view_transform = cfg["view_transform"]
scn.view_settings.exposure = cfg["exposure"]
scn.render.resolution_x, scn.render.resolution_y = cfg["resolution"]

w = bpy.data.worlds.new("w"); w.use_nodes = True
w.node_tree.nodes["Background"].inputs[0].default_value = tuple(cfg["world_rgb"]) + (1,)
scn.world = w
sun = bpy.data.objects.new("s", bpy.data.lights.new("s", "SUN"))
scn.collection.objects.link(sun)
sun.data.energy = cfg["sun"]["energy"]
sun.data.angle = math.radians(cfg["sun"]["angle_deg"])
sun.rotation_euler = [math.radians(a) for a in cfg["sun"]["euler_deg"]]

g = cfg["ground"]
mesh = bpy.data.meshes.new("ground"); gobj = bpy.data.objects.new("QC_GROUND", mesh)
import bmesh
bm = bmesh.new(); bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=g["size"] / 2)
bm.to_mesh(mesh); bm.free()
scn.collection.objects.link(gobj)
gobj.location = (0, 0, g["y"])          # glTF y=0 ground -> Blender z=0
gm = bpy.data.materials.new("gm"); gm.use_nodes = True
nt = gm.node_tree
ck = nt.nodes.new("ShaderNodeTexChecker")
ck.inputs["Color1"].default_value = tuple(g["c1"]) + (1,)
ck.inputs["Color2"].default_value = tuple(g["c2"]) + (1,)
ck.inputs["Scale"].default_value = g["size"] / g["check_m"]
tc = nt.nodes.new("ShaderNodeTexCoord")
nt.links.new(tc.outputs["Object"], ck.inputs["Vector"])
bsdf = nt.nodes["Principled BSDF"]
nt.links.new(ck.outputs["Color"], bsdf.inputs["Base Color"])
bsdf.inputs["Roughness"].default_value = 0.9
gobj.data.materials.append(gm)

cam = bpy.data.objects.new("c", bpy.data.cameras.new("c"))
scn.collection.objects.link(cam); scn.camera = cam
ovr = None
if WIRE:
    m = bpy.data.materials.new("wire"); m.use_nodes = True
    nt = m.node_tree; nt.nodes.clear()
    wf = nt.nodes.new("ShaderNodeWireframe"); wf.inputs[0].default_value = 0.0012
    e1 = nt.nodes.new("ShaderNodeEmission"); e1.inputs["Color"].default_value = (0.05, 0.05, 0.05, 1)
    e2 = nt.nodes.new("ShaderNodeEmission"); e2.inputs["Color"].default_value = (1, 1, 1, 1)
    mixn = nt.nodes.new("ShaderNodeMixShader"); o2 = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(wf.outputs[0], mixn.inputs[0]); nt.links.new(e2.outputs[0], mixn.inputs[1])
    nt.links.new(e1.outputs[0], mixn.inputs[2]); nt.links.new(mixn.outputs[0], o2.inputs[0])
    ovr = m
for name, c in cfg["cameras"].items():
    if ONLY and name not in ONLY:
        continue
    cam.location = c["loc"]; cam.rotation_euler = c["rot"]
    scn.view_layers[0].material_override = ovr
    if c["ortho"]:
        cam.data.type = 'ORTHO'; cam.data.ortho_scale = c["ortho"]
    else:
        cam.data.type = 'PERSP'; cam.data.lens = 50
    scn.render.filepath = os.path.join(OUTD, f"{name}.png")
    bpy.ops.render.render(write_still=True)
print("QC_RIG_DONE", GLB, "->", OUTD)
