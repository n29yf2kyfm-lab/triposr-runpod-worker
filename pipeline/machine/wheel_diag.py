#!/usr/bin/env python3
"""wheel_diag.py — V41 wheel-gate validation renders (Stages 6-7).

Builds a diagnostic-material copy of the V41 car (Stage 6 colours: tyres
medium grey, rims light grey, hubs blue, discs silver, calipers red, body
neutral clay, grey ground) plus a body-only variant, then renders the
required validation set: 5 orthographic views, 4 three-quarters, wheel
close-up, wireframe, axle-debug (annotated top + front orthos with axle
lines, centres, centreline, track/wheelbase/contact measurements), and
the wheel-removal proof. No bloom, no DoF, flat sun light, Standard view
transform, denoising off (this Blender has no OIDN).

Run: python3 wheel_diag.py <v41.glb> <wheel_qc.json> <outdir>
"""
import json
import os
import subprocess
import sys
import numpy as np
import trimesh
from trimesh.visual.material import PBRMaterial

V41, QCF, OUTD = sys.argv[1], sys.argv[2], sys.argv[3]
os.makedirs(OUTD, exist_ok=True)
qc = json.load(open(QCF))

DIAG = {  # stage-6 colour language
    "TYRE_MASTER": ([120, 120, 122], 0.0, 0.85),
    "RIM_MASTER": ([205, 205, 208], 0.0, 0.45),
    "HUB_MASTER": ([30, 70, 200], 0.0, 0.5),
    "BRAKE_DISC_MASTER": ([195, 195, 200], 0.6, 0.35),
    "BRAKE_CALIPER_MASTER": ([210, 30, 30], 0.0, 0.5),
}
CLAY = ([168, 162, 152], 0.0, 0.85)
DARK = ([70, 70, 73], 0.0, 0.8)


def mat(name, spec):
    col, met, rgh = spec
    return trimesh.visual.TextureVisuals(material=PBRMaterial(
        name=name, baseColorFactor=col + [255], metallicFactor=met,
        roughnessFactor=rgh))


sc = trimesh.load(V41, force="scene")
diag = trimesh.Scene()
body_only = trimesh.Scene()
recol = {}
for gname, g in sc.geometry.items():
    gm = g.copy()
    if gname in DIAG:
        gm.visual = mat(gname, DIAG[gname])
    elif "carpaint" in gname:
        gm.visual = mat("clay", CLAY)
    else:
        gm.visual = mat(f"d_{gname}", DARK)
    recol[gname] = gm
# walk the GRAPH so instanced nodes keep their transforms
for node in sc.graph.nodes_geometry:
    T, gname = sc.graph[node]
    for scene, skip_wheels in ((diag, False), (body_only, True)):
        if skip_wheels and gname in DIAG:
            continue                     # removal-proof scene: no wheels
        if gname not in scene.geometry:
            scene.add_geometry(recol[gname], geom_name=gname,
                               node_name=node, transform=T)
        else:
            scene.graph.update(frame_to=node, matrix=T, geometry=gname)

# ground plane, neutral grey, top face at y=0
gp = trimesh.creation.box(extents=[9.0, 0.02, 6.0])
gp.apply_translation([0, -0.01, 0])
gp.visual = mat("ground", ([128, 128, 130], 0.0, 0.9))
diag.add_geometry(gp, node_name="GROUND", geom_name="GROUND")
body_only.add_geometry(gp.copy(), node_name="GROUND", geom_name="GROUND")

dglb = os.path.join(OUTD, "V41_WHEEL_DIAG.glb")
bglb = os.path.join(OUTD, "V41_BODY_ONLY.glb")
diag.export(dglb, include_normals=True)
body_only.export(bglb, include_normals=True)
print("diag scenes written")

BSCRIPT = os.path.join(OUTD, "_wd.py")
open(BSCRIPT, "w").write(r'''
import bpy, sys, math, mathutils
argv = sys.argv[sys.argv.index("--")+1:]
GLB, OUT, MODE = argv[0], argv[1], argv[2]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=GLB)
meshes=[o for o in bpy.data.objects if o.type=='MESH' and o.name!='GROUND']
mn=mathutils.Vector((1e9,)*3); mx=mathutils.Vector((-1e9,)*3)
for o in meshes:
    for c in o.bound_box:
        w=o.matrix_world@mathutils.Vector(c)
        mn=mathutils.Vector(map(min,mn,w)); mx=mathutils.Vector(map(max,mx,w))
ctr=(mn+mx)/2; size=max(mx-mn)
scn=bpy.context.scene
scn.render.engine='CYCLES'; scn.cycles.device='CPU'; scn.cycles.samples=40
scn.cycles.use_denoising=False; scn.view_settings.view_transform='Standard'
scn.render.resolution_x=1280; scn.render.resolution_y=800
w=bpy.data.worlds.new("w"); w.use_nodes=True
w.node_tree.nodes["Background"].inputs[0].default_value=(0.72,0.72,0.74,1); scn.world=w
sun=bpy.data.objects.new("s",bpy.data.lights.new("s","SUN")); scn.collection.objects.link(sun)
sun.data.energy=3.0; sun.data.angle=0.5
sun.rotation_euler=(math.radians(45),0,math.radians(160))
cam=bpy.data.objects.new("c",bpy.data.cameras.new("c")); scn.collection.objects.link(cam); scn.camera=cam
def wiremat():
    m=bpy.data.materials.new("wire"); m.use_nodes=True
    nt=m.node_tree; nt.nodes.clear()
    wf=nt.nodes.new("ShaderNodeWireframe"); wf.inputs[0].default_value=0.0012
    e1=nt.nodes.new("ShaderNodeEmission"); e1.inputs["Color"].default_value=(0.05,0.05,0.05,1)
    e2=nt.nodes.new("ShaderNodeEmission"); e2.inputs["Color"].default_value=(1,1,1,1)
    mixn=nt.nodes.new("ShaderNodeMixShader"); o=nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(wf.outputs[0],mixn.inputs[0]); nt.links.new(e2.outputs[0],mixn.inputs[1])
    nt.links.new(e1.outputs[0],mixn.inputs[2]); nt.links.new(mixn.outputs[0],o.inputs[0])
    return m
def shoot(name, az, el, ortho=None, target=None, dist=None, ovr=None):
    t = mathutils.Vector(target) if target else mathutils.Vector((ctr.x,ctr.y,(mn.z+mx.z)/2))
    a,e=math.radians(az),math.radians(el); d=dist if dist else size*1.6
    cam.location=(t.x+d*math.cos(e)*math.sin(a), t.y-d*math.cos(e)*math.cos(a), t.z+d*math.sin(e))
    cam.rotation_euler=(t-cam.location).to_track_quat('-Z','Y').to_euler()
    if ortho:
        cam.data.type='ORTHO'; cam.data.ortho_scale=ortho
    else:
        cam.data.type='PERSP'; cam.data.lens=50
    scn.view_layers[0].material_override=ovr
    scn.render.filepath=OUT+f"/{name}.png"
    bpy.ops.render.render(write_still=True)
# NOTE az convention (car length on X, nose +X): az 90 = straight FRONT,
# az 270 = straight REAR, az 0 = RIGHT side, az 180 = LEFT side.
if MODE == "full":
    shoot("01_front_ortho",   90, 2, ortho=2.6)
    shoot("02_rear_ortho",   270, 2, ortho=2.6)
    shoot("03_left_ortho",   180, 2, ortho=5.0)
    shoot("04_right_ortho",    0, 2, ortho=5.0)
    shoot("05_top_ortho",      0,89.9, ortho=5.0)
    shoot("06_front34_L",    145,14)
    shoot("07_front34_R",     35,14)
    shoot("08_rear34_L",     215,14)
    shoot("09_rear34_R",     305,14)
    # FR wheel close-up: glTF (1.247,0.317,0.7745) -> Blender (x, -z, y)
    shoot("10_wheel_closeup", 40, 8, target=(1.247,-0.7745,0.317), dist=1.05)
    shoot("11_wireframe",      0, 2, ortho=5.0, ovr=wiremat())
    shoot("12a_axledebug_top", 0,89.9, ortho=5.2)
    shoot("12b_axledebug_front",90, 1, ortho=2.8)
else:
    shoot("proof_left_ortho", 180, 2, ortho=5.0)
    shoot("proof_front34_L",  145,10)
    shoot("proof_arch_close",  145, 6, target=(1.247,0.7745,0.32), dist=1.2)
print("WHEEL_DIAG_RENDERS_DONE", MODE)
''')
subprocess.run(["blender", "-b", "--python", BSCRIPT, "--", dglb, OUTD, "full"],
               check=True, capture_output=True)
print("full-set renders done")
subprocess.run(["blender", "-b", "--python", BSCRIPT, "--", bglb, OUTD, "removal"],
               check=True, capture_output=True)
print("removal-proof renders done")

# ---- axle-debug overlay (Stage 7 item 12) ----
from PIL import Image, ImageDraw
W, H = 1280, 800
cw = qc["wheels"]
cx_g = (2.170 + -2.167) / 2          # body ctr x (bbox centre used by cam)
# the render camera centres on the car bbox (without ground): recompute
sc3 = trimesh.load(V41, force="scene")
allv = np.vstack([g.vertices for g in sc3.geometry.values()])
bmin, bmax = allv.min(0), allv.max(0)
CTR = (bmin + bmax) / 2

top = Image.open(f"{OUTD}/12a_axledebug_top.png").convert("RGB")
d = ImageDraw.Draw(top)
OS = 5.2
osv = OS * H / W
def top_px(xg, zg):
    return (W/2 + (xg - CTR[0]) * W / OS, H/2 + (zg - CTR[2]) * H / osv)
# centreline
d.line([top_px(bmin[0]-0.2, 0), top_px(bmax[0]+0.2, 0)], fill=(30,110,30), width=3)
# axle lines
for pair, col in ((("FR","FL"),(220,40,40)), (("RR","RL"),(40,60,220))):
    a, b = cw[pair[0]]["centre"], cw[pair[1]]["centre"]
    d.line([top_px(a[0],a[2]), top_px(b[0],b[2])], fill=col, width=4)
for tag, c in cw.items():
    px, py = top_px(c["centre"][0], c["centre"][2])
    d.ellipse([px-7,py-7,px+7,py+7], outline=(0,0,0), width=3)
    d.line([px-12,py,px+12,py], fill=(0,0,0), width=1)
    d.line([px,py-12,px,py+12], fill=(0,0,0), width=1)
    d.text((px+10, py+8), tag, fill=(0,0,0))
g = qc["gates"]
d.text((14, 10), f"AXLE DEBUG (top ortho) — V41_WHEEL_GATE 2026-08-18", fill=(0,0,0))
d.text((14, 28), f"wheelbase {g['wheelbase_measured']:.3f} m (arch-derived, approx; Mk8 spec 2.619)", fill=(0,0,0))
d.text((14, 46), f"track F {g['track_front_measured']:.3f} m / R {g['track_rear_measured']:.3f} m (Mk8 spec)", fill=(0,0,0))
d.text((14, 64), f"axle parallelism {g['axle_parallelism_deg']:.3f} deg   toe max {g['toe_max_deg']:.2f} deg   camber max {g['camber_max_deg']:.2f} deg", fill=(0,0,0))
top.save(f"{OUTD}/12_axledebug_top.png")

fr = Image.open(f"{OUTD}/12b_axledebug_front.png").convert("RGB")
d = ImageDraw.Draw(fr)
OS2 = 2.8
osv2 = OS2 * H / W
def fr_px(zg, yg):
    return (W/2 + (zg - CTR[2]) * W / OS2, H/2 - (yg - CTR[1]) * H / osv2)
# ground line + contact points + centreline
d.line([fr_px(-1.3, 0), fr_px(1.3, 0)], fill=(30,110,30), width=3)
d.line([fr_px(0, -0.05), fr_px(0, 1.6)], fill=(30,110,30), width=2)
for tag in ("FR","FL"):
    c = cw[tag]["centre"]
    px, py = fr_px(c[2], c[1])
    d.ellipse([px-7,py-7,px+7,py+7], outline=(200,30,30), width=3)
    gx, gy = fr_px(c[2], 0)
    d.line([(px,py),(gx,gy)], fill=(200,30,30), width=2)
    d.ellipse([gx-5,gy-5,gx+5,gy+5], fill=(200,30,30))
    d.text((gx+8, gy-18), f"{tag} contact dy={cw[tag]['ground_contact_y']*1000:.1f}mm", fill=(0,0,0))
d.text((14, 10), "AXLE DEBUG (front ortho) — ground plane, contact points, centreline", fill=(0,0,0))
d.text((14, 28), f"L/R centre height diff: front {g['lr_centre_height_diff_mm']['front']}mm rear {g['lr_centre_height_diff_mm']['rear']}mm", fill=(0,0,0))
fr.save(f"{OUTD}/12_axledebug_front.png")
print("axle-debug overlays written")
