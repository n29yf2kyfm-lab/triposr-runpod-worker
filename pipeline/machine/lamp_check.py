#!/usr/bin/env python3
"""lamp_check.py — left/right lamp symmetry check (review standard).

Left lamp MAGENTA, right lamp ORANGE, body neutral grey, plus a wireframe
pass, from straight rear and both rear 3/4s. Two DIFFERENT colours is the
whole point: if the units are not mirror images the eye sees it instantly,
where a single colour hides it — which is how the v31 left unit shipped
13cm deeper than the right.

Prints a numeric symmetry assertion too (tri counts + max mirrored-X
difference), so the check does not depend on the eye alone.

Run: python3 lamp_check.py <car.glb> <rear_kit.npz> <outdir>
"""
import os
import subprocess
import sys
import numpy as np
import trimesh
from trimesh.visual.material import PBRMaterial

CAR, KIT, OUTD = sys.argv[1], sys.argv[2], sys.argv[3]
os.makedirs(OUTD, exist_ok=True)

sc = trimesh.load(CAR, force="scene")
out = trimesh.Scene()
GREY = PBRMaterial(name="body_grey", baseColorFactor=[150, 150, 152, 255],
                   metallicFactor=0.0, roughnessFactor=0.85)
for name, g in sc.geometry.items():
    if any(k in name for k in ("Tail_Lens", "lens")):
        continue                                   # replaced below, per side
    gm = g.copy()
    gm.visual = trimesh.visual.TextureVisuals(material=GREY)
    out.add_geometry(gm, node_name=name, geom_name=name)

rz = np.load(KIT)
V, F = rz["lens_v"], rz["lens_f"]
c = V[F].mean(1)
for name, sel, col in (("lamp_LEFT_magenta", c[:, 2] < 0, [225, 30, 205]),
                       ("lamp_RIGHT_orange", c[:, 2] >= 0, [245, 130, 20])):
    if not sel.any():
        print(f"{name}: EMPTY")
        continue
    part = trimesh.Trimesh(vertices=V, faces=F[sel], process=True)
    part.visual = trimesh.visual.TextureVisuals(material=PBRMaterial(
        name=name, baseColorFactor=col + [255], metallicFactor=0.0,
        roughnessFactor=0.4))
    out.add_geometry(part, node_name=name, geom_name=name)
    p = c[sel]
    print(f"{name}: {int(sel.sum())} tris  x {p[:,0].min():.2f}..{p[:,0].max():.2f} "
          f"(depth {p[:,0].max()-p[:,0].min():.2f})  y {p[:,1].min():.2f}..{p[:,1].max():.2f}"
          f"  |z| {np.abs(p[:,2]).min():.2f}..{np.abs(p[:,2]).max():.2f}")

lp = c[c[:, 2] < 0].copy(); rp = c[c[:, 2] >= 0].copy()
lp[:, 2] *= -1
if len(lp) == len(rp) and len(lp):
    dx = np.abs(np.sort(lp[:, 0]) - np.sort(rp[:, 0])).max()
    print(f"SYMMETRY: equal tri counts, max mirrored X difference {dx*1000:.1f}mm")
else:
    print(f"SYMMETRY: FAIL — {len(lp)} vs {len(rp)} tris")

glb = os.path.join(OUTD, "lamp_check.glb")
out.export(glb)

script = os.path.join(OUTD, "_lc.py")
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
# az 270 is the rear end-on view on this rig (written in CLAUDE.md, burned twice)
for name,az,el,ovr in [("straight",270,8,None),("r34_L",215,12,None),
                       ("r34_R",305,12,None),("wireframe",270,8,wire())]:
    a,e=math.radians(az),math.radians(el); d=size*1.55
    cam.location=(ctr.x+d*math.cos(e)*math.sin(a),ctr.y-d*math.cos(e)*math.cos(a),ctr.z+d*math.sin(e))
    cam.rotation_euler=(mathutils.Vector(ctr)-cam.location).to_track_quat('-Z','Y').to_euler()
    scn.view_layers[0].material_override=ovr
    scn.render.filepath=argv[1]+f"/lc_{name}.png"
    bpy.ops.render.render(write_still=True)
print("LAMP_CHECK_DONE")
""")
subprocess.run(["blender", "-b", "--python", script, "--", glb, OUTD], check=True)
print("RENDERS_DONE")
