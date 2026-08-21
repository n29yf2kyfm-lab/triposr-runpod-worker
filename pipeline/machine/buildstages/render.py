#!/usr/bin/env python3
"""render.py — local Blender renders for the merge pipeline's gates.

Modelled on pipeline/machine/rear2/render_views.py, kept separate because the
gate needs a MATERIAL-keyed id pass (that file's matID is OBJECT-keyed on
purpose, to tell L from R lamps sharing one material) and needs the camera to be
LOCKED across a before/after pair rather than framed on each file's own bbox.

RIG RULES, all of them paid for already and recorded in CLAUDE.md:
  * CYCLES only, CPU.  There is no EGL here.
  * `use_denoising = False`.  This container has no OpenImageDenoiser and
    `True` raises RuntimeError AFTER "Blender quit" prints, leaving stale
    frames.  So: delete the target frames first and grep for OUR OWN marker,
    never for Blender's exit.
  * view transform `Standard`, never AgX.  AgX plus inherited light energies
    clipped a tyre to pure white and produced a false defect verdict.
  * exposure is verified numerically by the caller, not eyeballed.

AZIMUTH, for this car: az 90 places the camera at glTF +X and az 270 at -X.
car_rebound has its NOSE at -X, so **az 270 = FRONT, az 090 = REAR**.  That is
asserted by `assert_front_az()` against the headlamp/taillamp node positions
rather than trusted — CLAUDE.md records renders burned twice on this mapping.
"""
from __future__ import annotations

import os
import subprocess

_SCRIPT = r'''
import bpy, sys, math, mathutils, hashlib, json
argv = sys.argv[sys.argv.index("--")+1:]
GLB, OUTD, MODE, TAG, CAMJSON, RES, SAMPLES = argv[0], argv[1], argv[2], argv[3], argv[4], int(argv[5]), int(argv[6])
CAM = json.loads(CAMJSON)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=GLB)
meshes=[o for o in bpy.data.objects if o.type=='MESH']

def emission(mat, col):
    mat.use_nodes=True; nt=mat.node_tree; nt.nodes.clear()
    e=nt.nodes.new("ShaderNodeEmission"); e.inputs[0].default_value=(col[0],col[1],col[2],1)
    o=nt.nodes.new("ShaderNodeOutputMaterial"); nt.links.new(e.outputs[0],o.inputs[0])

# A HASH palette is NOT usable for masking.  Measured on this car: md5 gave
# `glass` (0.20,0.45,0.75) and `Lamp_Lens` (0.20,0.51,0.80) -- 0.07 apart in a
# unit cube, so a nearest-colour mask would confuse the glazing with the
# headlamps and the respray control would report on the wrong pixels.  Colours
# are taken from a fixed maximally-separated ladder, indexed by the material's
# position in the SORTED name list, and the minimum pairwise separation is
# printed so the caller can assert it rather than hope.
LADDER=[(1,0,0),(0,1,0),(0,0,1),(1,1,0),(1,0,1),(0,1,1),
        (1,0.5,0),(0.5,0,1),(0,1,0.5),(1,0,0.5),(0.5,1,0),(0,0.5,1),
        (0.6,0.3,0.1),(0.1,0.6,0.3),(0.3,0.1,0.6),(1,1,1),
        (0.5,0.5,0),(0,0.5,0.5),(0.5,0,0.5),(1,0.75,0.75),
        (0.75,1,0.75),(0.75,0.75,1),(0.35,0.35,0.35),(0.9,0.55,0.2)]
def matcol(i):
    return LADDER[i % len(LADDER)]

ovr=None
palette={}
if MODE=="matid":
    order=sorted({m.name.split(".")[0] for m in bpy.data.materials})
    if len(order) > len(LADDER):
        raise SystemExit("MATID REFUSED: %d materials exceed the %d-colour ladder; "
                         "a wrapped ladder cannot be masked" % (len(order), len(LADDER)))
    for m in list(bpy.data.materials):
        nm=m.name.split(".")[0]
        palette[nm]=matcol(order.index(nm))
        emission(m, palette[nm])
    _c=list(palette.values())
    _d=min((sum((a[k]-b[k])**2 for k in range(3)))**0.5
           for i,a in enumerate(_c) for b in _c[i+1:]) if len(_c)>1 else 9.0
    print("PALETTE_MIN_SEP", round(_d,4))
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

scn=bpy.context.scene
scn.render.engine='CYCLES'; scn.cycles.device='CPU'
scn.cycles.use_denoising=False                  # NO OIDN in this container
scn.view_settings.view_transform='Standard'
scn.render.film_transparent=False
if MODE=="matid":
    scn.cycles.samples=1; scn.render.filter_size=0.01; scn.cycles.max_bounces=0
else:
    scn.cycles.samples=SAMPLES
scn.render.resolution_x=RES; scn.render.resolution_y=int(RES*9/14)
w=bpy.data.worlds.new("w"); w.use_nodes=True
bg=w.node_tree.nodes["Background"]
bg.inputs[0].default_value=(0.86,0.86,0.88,1) if MODE!="clay" else (0.30,0.30,0.32,1)
bg.inputs[1].default_value=(0.0 if MODE=="matid" else 0.75)
scn.world=w
if MODE!="matid":
    for ang,en in ((35,2.1),(200,1.05)):
        s=bpy.data.objects.new("s%d"%ang, bpy.data.lights.new("s%d"%ang,"SUN"))
        scn.collection.objects.link(s); s.data.energy=en
        s.rotation_euler=(math.radians(52),0,math.radians(ang))
cam=bpy.data.objects.new("c",bpy.data.cameras.new("c")); scn.collection.objects.link(cam); scn.camera=cam
scn.view_layers[0].material_override=ovr

# CAMERA IS LOCKED BY THE CALLER, not framed on this file's own bbox: a
# before/after pair framed independently is not a matched pair.
ctr=mathutils.Vector(CAM["centre"]); size=float(CAM["size"])
for item in CAM["shots"]:
    az=float(item["az"]); el=float(item["el"]); tag=item["tag"]
    a,e=math.radians(az),math.radians(el); d=size*float(CAM.get("dist_mul",1.5))
    cam.location=(ctr.x+d*math.cos(e)*math.sin(a), ctr.y-d*math.cos(e)*math.cos(a), ctr.z+d*math.sin(e))
    cam.rotation_euler=(mathutils.Vector(ctr)-cam.location).to_track_quat('-Z','Y').to_euler()
    if "lens" in CAM: cam.data.lens=float(CAM["lens"])
    scn.render.filepath=OUTD+"/%s_%s.png"%(TAG,tag)
    bpy.ops.render.render(write_still=True)
    print("RENDERED", scn.render.filepath)
if palette: print("PALETTE", json.dumps(palette))
print("BG_RENDER_ALL_DONE")
'''


def camera_for(meas, dist_mul=1.5, lens=None):
    """A camera spec locked to ONE file's bbox, reusable across a matched pair.

    glTF (x,y,z) -> Blender (x,-z,y) on import, which is why the centre is
    remapped here rather than in the Blender script.
    """
    lo, hi = meas["bbox_min"], meas["bbox_max"]
    ctr = [(lo[0] + hi[0]) / 2, -(lo[2] + hi[2]) / 2, (lo[1] + hi[1]) / 2]
    size = max(hi[i] - lo[i] for i in range(3))
    c = {"centre": ctr, "size": size, "dist_mul": dist_mul, "shots": []}
    if lens:
        c["lens"] = lens
    return c


def shots(spec):
    """[(az, el, tag)] -> the camera's shot list."""
    return [{"az": a, "el": e, "tag": t} for a, e, t in spec]


def render(glb, outdir, mode, tag, cam, res=1400, samples=48, timeout=3600):
    """Render `cam["shots"]` of `glb`.  Returns the list of written paths.

    Stale-frame safety: every target frame is DELETED before the run, and the
    run is only believed if it printed its own completion marker.
    """
    os.makedirs(outdir, exist_ok=True)
    glb = os.path.abspath(glb)
    outdir = os.path.abspath(outdir)
    want = [os.path.join(outdir, f"{tag}_{s['tag']}.png") for s in cam["shots"]]
    for p in want:
        if os.path.exists(p):
            os.remove(p)
    script = os.path.join(outdir, f"_bgr_{tag}.py")
    open(script, "w").write(_SCRIPT)
    import json as _j
    r = subprocess.run(
        ["blender", "-b", "--python", script, "--", glb, outdir, mode, tag,
         _j.dumps(cam), str(res), str(samples)],
        capture_output=True, text=True, timeout=timeout)
    out = r.stdout + r.stderr
    if "BG_RENDER_ALL_DONE" not in out:
        raise SystemExit("RENDER FAILED (own marker absent):\n" + out[-4000:])
    missing = [p for p in want if not os.path.exists(p)]
    if missing:
        raise SystemExit(f"RENDER FAILED: frames not written {missing}")
    pal, sep = {}, None
    for ln in out.splitlines():
        if ln.startswith("PALETTE "):
            pal = _j.loads(ln[8:])
        if ln.startswith("PALETTE_MIN_SEP "):
            sep = float(ln.split()[1])
    if mode == "matid" and sep is not None and sep < 0.30:
        raise SystemExit(f"MATID REFUSED: palette min separation {sep} is too "
                         f"small to mask reliably")
    return want, pal
