#!/usr/bin/env python3
"""rear_diag.py — rear-component clay diagnostic (review standard).

Colours the rear third by COMPONENT so separation (or its absence) is
visible before any paint goes on: lamps magenta, hatch cyan, bumper
yellow, rear glass dark blue, everything else neutral clay. The hatch/
bumper split is by height band — if the underlying geometry is one fused
blob, this render shows a fuzzy boundary, which is exactly the honest
diagnosis the review wants.

Builds the diagnostic GLB, then renders straight rear + both rear 3/4.

Run: python3 rear_diag.py <canon.glb> <labels.npy> <panes.npz> <outdir>
"""
import os
import sys
import numpy as np
import trimesh
from trimesh.visual.material import PBRMaterial

CANON, LAB, PANES, OUTD = sys.argv[1:5]
REARKIT = sys.argv[5] if len(sys.argv) > 5 else None   # parametric lamp npz
os.makedirs(OUTD, exist_ok=True)
BODY, GLASS, WHEEL, LAMP, UNSEEN = 0, 1, 2, 3, 4

sc = trimesh.load(CANON, force="scene")
m = trimesh.util.concatenate([g for g in sc.geometry.values()])
cent = m.triangles_center
label = np.load(LAB)
x, y = cent[:, 0], cent[:, 1]
L0, L1 = x.min(), x.max()
xf = (x - L0) / (L1 - L0)                    # rear = LOW x
H0 = y.min(); H = y.max() - H0

COLS = {
    "clay":   [150, 150, 152], "lamp_mag": [225, 35, 205],
    "hatch_cyan": [45, 200, 220], "bumper_yellow": [232, 210, 45],
    "glass_blue": [22, 32, 120], "dark": [60, 60, 62],
}


def mat(name):
    return PBRMaterial(name=name, baseColorFactor=COLS[name] + [255],
                       metallicFactor=0.0, roughnessFactor=0.9)


out = trimesh.Scene()
rear = xf < 0.18
label = label.copy()
if REARKIT is not None:
    # parametric build: the blob lamp label was painted body — the machine's
    # lamps ARE the designed lens units, which get the magenta below
    label[(label == LAMP) & rear] = BODY
groups = {
    "lamp_mag":  (label == LAMP) & rear,
    "bumper_yellow": (label == BODY) & (xf < 0.10) & (y < H0 + 0.33 * H),
    "hatch_cyan": (label == BODY) & (xf < 0.12) & (y >= H0 + 0.33 * H),
    "clay": ((label == BODY) | (label == LAMP)) & ~rear &
            ~((label == BODY) & (xf < 0.12)),
    "dark": (label == WHEEL) | (label == UNSEEN),
}
for name, sel in groups.items():
    idx = np.where(sel)[0]
    if not len(idx):
        continue
    sub = trimesh.Trimesh(vertices=m.vertices, faces=m.faces[idx], process=True)
    sub.visual = trimesh.visual.TextureVisuals(material=mat(name))
    out.add_geometry(sub, node_name=name, geom_name=name)

# constructed panes: rear screen dark blue, other windows neutral dark
pz = np.load(PANES)
pcent = pz["vertices"][pz["faces"]].mean(1)
pxf = (pcent[:, 0] - L0) / (L1 - L0)
for sel, name in ((pxf < 0.22, "glass_blue"), (pxf >= 0.22, "dark")):
    if not sel.any():
        continue
    part = trimesh.Trimesh(vertices=pz["vertices"], faces=pz["faces"][sel],
                           process=True)
    part.visual = trimesh.visual.TextureVisuals(material=mat(name))
    out.add_geometry(part, node_name=f"pane_{name}", geom_name=f"pane_{name}")

if REARKIT is not None:
    rz = np.load(REARKIT)
    lens = trimesh.Trimesh(vertices=rz["lens_v"], faces=rz["lens_f"],
                           process=True)
    lens.visual = trimesh.visual.TextureVisuals(material=mat("lamp_mag"))
    out.add_geometry(lens, node_name="lens_mag", geom_name="lens_mag")
    for vk, fk in (("plate_v", "plate_f"), ("frame_v", "frame_f")):
        p = trimesh.Trimesh(vertices=rz[vk], faces=rz[fk], process=True)
        p.visual = trimesh.visual.TextureVisuals(material=mat("dark"))
        out.add_geometry(p, node_name=fk, geom_name=fk)

glb = os.path.join(OUTD, "rear_diag.glb")
out.export(glb)
print("diag glb:", glb)

# render straight rear + both rear 3/4 (az 270 = rear end-on on this rig)
import subprocess
script = os.path.join(OUTD, "_rd_render.py")
open(script, "w").write("""
import bpy, sys, math, mathutils
argv = sys.argv[sys.argv.index("--")+1:]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=argv[0])
meshes = [o for o in bpy.data.objects if o.type == 'MESH']
mn = mathutils.Vector((1e9,)*3); mx = mathutils.Vector((-1e9,)*3)
for o in meshes:
    for c in o.bound_box:
        w = o.matrix_world @ mathutils.Vector(c)
        mn = mathutils.Vector(map(min, mn, w)); mx = mathutils.Vector(map(max, mx, w))
ctr = (mn+mx)/2; size = max(mx-mn)
scn = bpy.context.scene
scn.render.engine = 'CYCLES'; scn.cycles.device = 'CPU'
scn.cycles.samples = 40; scn.cycles.use_denoising = False
scn.view_settings.view_transform = 'Standard'
scn.render.resolution_x = 1100; scn.render.resolution_y = 700
w = bpy.data.worlds.new("w"); w.use_nodes = True
w.node_tree.nodes["Background"].inputs[0].default_value = (0.82, 0.82, 0.84, 1)
scn.world = w
sun = bpy.data.objects.new("s", bpy.data.lights.new("s", "SUN"))
scn.collection.objects.link(sun); sun.data.energy = 3.5
sun.rotation_euler = (math.radians(50), 0, math.radians(210))
cam = bpy.data.objects.new("c", bpy.data.cameras.new("c"))
scn.collection.objects.link(cam); scn.camera = cam
def wire_mat():
    m = bpy.data.materials.new("wire"); m.use_nodes = True
    nt = m.node_tree; nt.nodes.clear()
    wf = nt.nodes.new("ShaderNodeWireframe"); wf.inputs[0].default_value = 0.0015
    e1 = nt.nodes.new("ShaderNodeEmission"); e1.inputs["Color"].default_value = (1, 1, 1, 1)
    e2 = nt.nodes.new("ShaderNodeEmission"); e2.inputs["Color"].default_value = (0, 0, 0, 1)
    mix = nt.nodes.new("ShaderNodeMixShader")
    outn = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(wf.outputs[0], mix.inputs[0])
    nt.links.new(e1.outputs[0], mix.inputs[1])
    nt.links.new(e2.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], outn.inputs[0])
    return m

views = [("rear_straight", 270, 8, None), ("rear34_L", 215, 12, None),
         ("rear34_R", 305, 12, None), ("wireframe", 270, 8, wire_mat())]
for name, az, el, ovr in views:
    a, e = math.radians(az), math.radians(el); d = size*1.6
    cam.location = (ctr.x + d*math.cos(e)*math.sin(a), ctr.y - d*math.cos(e)*math.cos(a), ctr.z + d*math.sin(e))
    cam.rotation_euler = (mathutils.Vector(ctr)-cam.location).to_track_quat('-Z','Y').to_euler()
    scn.view_layers[0].material_override = ovr
    scn.render.filepath = argv[1] + f"/diag_{name}.png"
    bpy.ops.render.render(write_still=True)
print("REAR_DIAG_DONE")
""")
subprocess.run(["blender", "-b", "--python", script, "--", glb, OUTD], check=True)
print("RENDERS_DONE")
