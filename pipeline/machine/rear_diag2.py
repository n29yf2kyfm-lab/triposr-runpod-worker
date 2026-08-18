#!/usr/bin/env python3
"""rear_diag2.py — rear diagnostic for an ASSEMBLED car + four-lamp kit.

Reviewer-specified colour language: lamps RED, hatch CYAN, bumper YELLOW,
body neutral grey, plus a wireframe pass. Works straight from the shipped
car GLB (no labels needed — hatch/bumper split is the geometric height cut)
so it survives losing every intermediate.

Views: straight rear (az 270 — the end-on azimuth on this rig), both rear
three-quarters, wireframe.

Run: python3 rear_diag2.py <car.glb> <kit.npz> <outdir>
"""
import os
import subprocess
import sys
import numpy as np
import trimesh
from trimesh.visual.material import PBRMaterial

CAR, KIT, OUTD = sys.argv[1], sys.argv[2], sys.argv[3]
os.makedirs(OUTD, exist_ok=True)


def mat(name, col, rough=0.85):
    return PBRMaterial(name=name, baseColorFactor=col + [255],
                       metallicFactor=0.0, roughnessFactor=rough)


GREY = [150, 150, 152]; CYAN = [45, 200, 220]; YELL = [232, 210, 45]
RED = [220, 32, 32]; DARK = [70, 70, 73]

sc = trimesh.load(CAR, force="scene")
out = trimesh.Scene()
for name, g in sc.geometry.items():
    if name.startswith("Tail_Lens"):
        continue                                    # kit replaces these
    if "carpaint" in name:
        # hatch/bumper split by height cut on the rear zone
        c = g.triangles_center
        x, y = c[:, 0], c[:, 1]
        L0, L1 = x.min(), x.max()
        xf = (x - L0) / (L1 - L0)
        H0 = y.min(); H = y.max() - H0
        rear = xf < 0.18
        groups = {"bumper_yellow": (rear & (y < H0 + 0.33 * H), YELL),
                  "hatch_cyan": (rear & (y >= H0 + 0.33 * H), CYAN),
                  "body_grey": (~rear, GREY)}
        for nm, (sel, col) in groups.items():
            if not sel.any():
                continue
            sub = trimesh.Trimesh(vertices=g.vertices, faces=g.faces[sel],
                                  process=True)
            sub.visual = trimesh.visual.TextureVisuals(material=mat(nm, col))
            out.add_geometry(sub, node_name=nm, geom_name=nm)
    else:
        gm = g.copy()
        gm.visual = trimesh.visual.TextureVisuals(material=mat(f"d_{name}", DARK))
        out.add_geometry(gm, node_name=name, geom_name=name)

rz = np.load(KIT)
for vk, fk, nm in (("ro_v", "ro_f", "lamp_RO"), ("rh_v", "rh_f", "lamp_RH"),
                   ("lo_v", "lo_f", "lamp_LO"), ("lh_v", "lh_f", "lamp_LH"),
                   ("lens_v", "lens_f", "lamp_legacy")):
    if vk not in rz:
        continue
    part = trimesh.Trimesh(vertices=rz[vk], faces=rz[fk], process=True)
    part.visual = trimesh.visual.TextureVisuals(material=mat(nm, RED, 0.35))
    out.add_geometry(part, node_name=nm, geom_name=nm)
    print(f"  {nm}: {len(part.faces)} faces")

glb = os.path.join(OUTD, "rear_diag2.glb")
out.export(glb)

script = os.path.join(OUTD, "_rd2.py")
open(script, "w").write("""
import bpy, sys, math, mathutils
argv = sys.argv[sys.argv.index("--")+1:]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=argv[0])
meshes=[o for o in bpy.data.objects if o.type=='MESH']
mn=mathutils.Vector((1e9,)*3); mx=mathutils.Vector((-1e9,)*3)
for o in meshes:
    for c in o.bound_box:
        w=o.matrix_world@mathutils.Vector(c)
        mn=mathutils.Vector(map(min,mn,w)); mx=mathutils.Vector(map(max,mx,w))
ctr=(mn+mx)/2; size=max(mx-mn)
scn=bpy.context.scene
scn.render.engine='CYCLES'; scn.cycles.device='CPU'; scn.cycles.samples=40
scn.cycles.use_denoising=False; scn.view_settings.view_transform='Standard'
scn.render.resolution_x=1100; scn.render.resolution_y=700
w=bpy.data.worlds.new("w"); w.use_nodes=True
w.node_tree.nodes["Background"].inputs[0].default_value=(0.85,0.85,0.87,1); scn.world=w
sun=bpy.data.objects.new("s",bpy.data.lights.new("s","SUN")); scn.collection.objects.link(sun)
sun.data.energy=3.5; sun.rotation_euler=(math.radians(50),0,math.radians(210))
cam=bpy.data.objects.new("c",bpy.data.cameras.new("c")); scn.collection.objects.link(cam); scn.camera=cam
def wire():
    m=bpy.data.materials.new("wire"); m.use_nodes=True
    nt=m.node_tree; nt.nodes.clear()
    wf=nt.nodes.new("ShaderNodeWireframe"); wf.inputs[0].default_value=0.0015
    e1=nt.nodes.new("ShaderNodeEmission"); e1.inputs["Color"].default_value=(1,1,1,1)
    e2=nt.nodes.new("ShaderNodeEmission"); e2.inputs["Color"].default_value=(0,0,0,1)
    mixn=nt.nodes.new("ShaderNodeMixShader"); o=nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(wf.outputs[0],mixn.inputs[0]); nt.links.new(e1.outputs[0],mixn.inputs[1])
    nt.links.new(e2.outputs[0],mixn.inputs[2]); nt.links.new(mixn.outputs[0],o.inputs[0])
    return m
for name,az,el,ovr in [("straight",270,8,None),("r34_L",215,12,None),
                       ("r34_R",305,12,None),("wireframe",270,8,wire())]:
    a,e=math.radians(az),math.radians(el); d=size*1.55
    cam.location=(ctr.x+d*math.cos(e)*math.sin(a),ctr.y-d*math.cos(e)*math.cos(a),ctr.z+d*math.sin(e))
    cam.rotation_euler=(mathutils.Vector(ctr)-cam.location).to_track_quat('-Z','Y').to_euler()
    scn.view_layers[0].material_override=ovr
    scn.render.filepath=argv[1]+f"/rd2_{name}.png"
    bpy.ops.render.render(write_still=True)
print("REAR_DIAG2_DONE")
""")
subprocess.run(["blender", "-b", "--python", script, "--", glb, OUTD], check=True)
print("RENDERS_DONE")
