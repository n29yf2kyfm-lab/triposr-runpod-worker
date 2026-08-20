#!/usr/bin/env python3
"""render_views.py — local Blender render of a GLB at named azimuths.

AZIMUTH CONVENTION (verified by reading rear_diag2.py's camera formula and
the glTF Y-up -> Blender Z-up import): for a length-on-X, y-up car,
  az 90  = FRONT end-on (camera at +X)   az 270 = REAR end-on (camera at -X)
  az 0/180 = side views                  az 215 = rear 3/4, az 305 = rear 3/4 other side

Modes:
  shaded  — as authored (materials kept), bright studio-ish
  matid   — flat emission per material name, AA off, 1 sample (deterministic
            label render; the bl_label_render lesson)
  clay    — one neutral matte over everything (surface truth, no colour hiding)
  glasson — worker-style: transmission forced onto glass-named materials

Run: python3 render_views.py <glb> <outdir> <mode> <az,az,...> [tag]
"""
import os
import subprocess
import sys

GLB, OUTD, MODE, AZS = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
TAG = sys.argv[5] if len(sys.argv) > 5 else MODE
os.makedirs(OUTD, exist_ok=True)
GLB = os.path.abspath(GLB); OUTD = os.path.abspath(OUTD)

SCRIPT = os.path.join(OUTD, f"_rv_{TAG}.py")
open(SCRIPT, "w").write(r'''
import bpy, sys, math, mathutils, hashlib
argv = sys.argv[sys.argv.index("--")+1:]
GLB, OUTD, MODE, AZS, TAG = argv[0], argv[1], argv[2], argv[3], argv[4]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=GLB)
meshes=[o for o in bpy.data.objects if o.type=='MESH']

def emission(mat, col):
    mat.use_nodes=True; nt=mat.node_tree; nt.nodes.clear()
    e=nt.nodes.new("ShaderNodeEmission"); e.inputs[0].default_value=(col[0],col[1],col[2],1)
    o=nt.nodes.new("ShaderNodeOutputMaterial"); nt.links.new(e.outputs[0],o.inputs[0])

# ---- explicit diagnostic palette (owner-specified rear colours) ----
PAL = {
 "tail_lens_lo":(1.0,0.0,0.85), "tail_lens_ro":(1.0,0.45,0.0),   # L MAGENTA R ORANGE
 "tail_lens_lh":(1.0,0.0,0.85), "tail_lens_rh":(1.0,0.45,0.0),
 "tail_housing":(0.10,0.10,0.12),
 "rear_hatch":(0.0,0.85,1.0),                                     # hatch CYAN
 "rear_bumper":(1.0,0.92,0.0),                                    # bumper YELLOW
 "rear_glass":(0.03,0.05,0.45), "glass_rear":(0.03,0.05,0.45),    # rear glass DARK BLUE
 "rear_diffuser":(0.25,0.25,0.28),
 "plate":(1.0,1.0,1.0), "frame":(0.35,0.35,0.38),
 "carpaint":(0.55,0.55,0.56), "interior":(0.40,0.40,0.42),        # body GREY
 "glass":(0.10,0.55,0.35), "lamp_lens":(0.9,0.2,0.2),
 "tyre_rubber":(0.13,0.13,0.13), "rim_alloy":(0.62,0.62,0.66),
}
def palcol(name):
    n=name.lower()
    for k,v in PAL.items():
        if n.startswith(k): return v
    for k,v in PAL.items():
        if k in n: return v
    h=hashlib.md5(n.encode()).digest()
    return (h[0]/255*0.8+0.1, h[1]/255*0.8+0.1, h[2]/255*0.8+0.1)

ovr=None
if MODE=="matid":
    # colour by OBJECT, not by material: the four lens solids deliberately
    # SHARE one Tail_Lens_Red material (one physical lens material), so a
    # material-keyed matID cannot tell L from R -- and Rear_Hatch/Rear_Bumper
    # share the carpaint material for the same reason.
    for o in meshes:
        nm=o.name.split(".")[0]
        m=bpy.data.materials.new("mid_"+nm)
        emission(m, palcol(nm))
        o.data.materials.clear(); o.data.materials.append(m)
        print("MATID", nm, palcol(nm))
elif MODE=="clay":
    cm=bpy.data.materials.new("clay"); cm.use_nodes=True
    b=cm.node_tree.nodes.get("Principled BSDF")
    b.inputs["Base Color"].default_value=(0.62,0.62,0.63,1)
    b.inputs["Roughness"].default_value=0.55
    if "Metallic" in b.inputs: b.inputs["Metallic"].default_value=0.0
    ovr=cm
elif MODE in ("shaded","glasson"):
    for m in bpy.data.materials:
        m.use_nodes=True
        b=m.node_tree.nodes.get("Principled BSDF")
        if not b: continue
        if MODE=="glasson" and ("glass" in m.name.lower() or "window" in m.name.lower()):
            b.inputs["Transmission Weight"].default_value=1.0
            b.inputs["Base Color"].default_value=(0.18,0.20,0.22,1)
            b.inputs["Roughness"].default_value=0.0
            b.inputs["IOR"].default_value=1.45
            b.inputs["Alpha"].default_value=1.0
            m.blend_method='OPAQUE'

mn=mathutils.Vector((1e9,)*3); mx=mathutils.Vector((-1e9,)*3)
for o in meshes:
    for c in o.bound_box:
        w=o.matrix_world@mathutils.Vector(c)
        mn=mathutils.Vector(map(min,mn,w)); mx=mathutils.Vector(map(max,mx,w))
ctr=(mn+mx)/2; size=max(mx-mn)
scn=bpy.context.scene
scn.render.engine='CYCLES'; scn.cycles.device='CPU'
scn.cycles.use_denoising=False                 # NO OIDN in this container
scn.view_settings.view_transform='Standard'
scn.render.film_transparent=False
if MODE=="matid":
    scn.cycles.samples=1
    scn.render.filter_size=0.01
    scn.cycles.max_bounces=0
else:
    scn.cycles.samples=48
scn.render.resolution_x=1400; scn.render.resolution_y=900
w=bpy.data.worlds.new("w"); w.use_nodes=True
bg=w.node_tree.nodes["Background"]
bg.inputs[0].default_value=(0.86,0.86,0.88,1)
bg.inputs[1].default_value=(0.0 if MODE=="matid" else 1.2)
scn.world=w
if MODE!="matid":
    for ang,en in ((35,4.0),(200,2.0)):
        s=bpy.data.objects.new("s%d"%ang, bpy.data.lights.new("s%d"%ang,"SUN"))
        scn.collection.objects.link(s); s.data.energy=en
        s.rotation_euler=(math.radians(52),0,math.radians(ang))
cam=bpy.data.objects.new("c",bpy.data.cameras.new("c")); scn.collection.objects.link(cam); scn.camera=cam
scn.view_layers[0].material_override=ovr
for azs in AZS.split(","):
    az=float(azs); el=8.0 if az in (90.0,270.0,0.0,180.0) else 12.0
    a,e=math.radians(az),math.radians(el); d=size*1.5
    cam.location=(ctr.x+d*math.cos(e)*math.sin(a), ctr.y-d*math.cos(e)*math.cos(a), ctr.z+d*math.sin(e))
    cam.rotation_euler=(mathutils.Vector(ctr)-cam.location).to_track_quat('-Z','Y').to_euler()
    scn.render.filepath=OUTD+"/%s_az%03d.png"%(TAG,int(az))
    bpy.ops.render.render(write_still=True)
    print("RENDERED", scn.render.filepath)
print("RV_ALL_DONE")
''')
r = subprocess.run(["blender", "-b", "--python", SCRIPT, "--", GLB, OUTD, MODE, AZS, TAG],
                   capture_output=True, text=True)
out = r.stdout + r.stderr
# NEVER trust "Blender quit" — grep for OUR OWN marker
if "RV_ALL_DONE" not in out:
    print(out[-4000:])
    raise SystemExit("RENDER FAILED: RV_ALL_DONE marker absent")
for ln in out.splitlines():
    if ln.startswith("RENDERED"):
        print(ln)
print("RV_OK")
