#!/usr/bin/env python3
"""Recolour audit for the hardened ingest pipeline.

Renders two contrasting colour variants of a car and checks the BODY colour
actually changes. Catches the failure the MG4 and A2 both hit: the pipeline
picks the wrong paint material, so every "colour" looks identical. A car that
fails should not ship its colour-swap (fall back to single-neutral + flag).

Usage: recolour_audit.py <assetId> [colA] [colB]   (default red vs blue)
Exit 0 = PASS (colours differ), 2 = FAIL (recolour did not take), 3 = skip.
Prints:  RECOLOUR_AUDIT <aid> <PASS|FAIL|SKIP> dist=<n>
"""
import sys, os, json, subprocess, urllib.request, struct, math
import numpy as np
from PIL import Image
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CAT = os.environ.get("CATALOGUE") or os.path.join(REPO, "platform", "catalogue", "catalogue.v2.json")
TMP = os.environ.get("TMPDIR", "/tmp")
GT = ["npx", "--yes", "@gltf-transform/cli@4"]
AID = sys.argv[1]
CA = sys.argv[2] if len(sys.argv) > 2 else "red"
CB = sys.argv[3] if len(sys.argv) > 3 else "blue"

BLENDER = r'''
import bpy,sys,math,mathutils
inp,out=sys.argv[-2],sys.argv[-1]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=inp)
sc=bpy.context.scene; sc.render.engine='CYCLES'; sc.cycles.samples=16; sc.cycles.device='CPU'
sc.cycles.use_denoising=False; sc.render.resolution_x=400; sc.render.resolution_y=300
sc.render.film_transparent=True; sc.render.image_settings.color_mode='RGBA'
try: sc.view_settings.view_transform='Standard'
except: pass
w=bpy.data.worlds.new("w"); sc.world=w; w.use_nodes=True
w.node_tree.nodes["Background"].inputs[1].default_value=1.0
objs=[o for o in bpy.data.objects if o.type=='MESH']
mn=mathutils.Vector((1e9,)*3); mx=mathutils.Vector((-1e9,)*3)
for o in objs:
    for c in o.bound_box:
        wc=o.matrix_world@mathutils.Vector(c); mn=mathutils.Vector(map(min,mn,wc)); mx=mathutils.Vector(map(max,mx,wc))
ctr=(mn+mx)/2; rad=max((mx-mn))/2
l=bpy.data.lights.new("k",'SUN'); l.energy=3.0; lo=bpy.data.objects.new("k",l); sc.collection.objects.link(lo)
lo.rotation_euler=(math.radians(55),0,math.radians(30))
cam=bpy.data.cameras.new("c"); co=bpy.data.objects.new("c",cam); sc.collection.objects.link(co); sc.camera=co
cam.clip_start=max(rad*0.001,0.001); cam.clip_end=rad*1000   # scale-agnostic: mm-unit models were beyond default 100 far-clip -> blank
a=math.radians(35); e=math.radians(12); D=rad*3.2
co.location=ctr+mathutils.Vector((D*math.cos(e)*math.sin(a),-D*math.cos(e)*math.cos(a),D*math.sin(e)))
d=ctr-co.location; co.rotation_euler=d.to_track_quat('-Z','Y').to_euler()
sc.render.filepath=out; bpy.ops.render.render(write_still=True)
'''

def body_mean(png):
    im = np.asarray(Image.open(png).convert("RGBA"), dtype=np.float32)/255.0
    a = im[..., 3]; rgb = im[..., :3]
    fg = a > 0.6
    mx = rgb.max(2); mn = rgb.min(2); val = mx; sat = np.where(mx > 0, (mx-mn)/np.maximum(mx, 1e-6), 0)
    # body = foreground paint pixels: not glass/tyre (dark), not chrome/spec (near-white)
    body = fg & (val > 0.12) & (val < 0.97) & ((sat > 0.12) | (val > 0.3))
    if body.sum() < 200: body = fg & (val > 0.1) & (val < 0.98)
    return rgb[body].mean(0) if body.any() else np.array([0., 0., 0.])

def render_variant(url, tag):
    glb = f"{TMP}/aud_{AID}_{tag}.glb"; nd = glb+".nd.glb"; png = f"{TMP}/aud_{AID}_{tag}.png"
    urllib.request.urlretrieve(url, glb)
    subprocess.run(GT+["copy", glb, nd], capture_output=True, text=True, timeout=200)
    src = nd if os.path.exists(nd) and os.path.getsize(nd) > 10000 else glb
    bp = f"{TMP}/_audrender_{AID}.py"; open(bp, "w").write(BLENDER)
    subprocess.run(["blender", "-b", "-P", bp, "--", src, png], capture_output=True, text=True, timeout=300)
    res = body_mean(png) if os.path.exists(png) else None
    for f in (glb, nd, png):
        try: os.remove(f)
        except OSError: pass
    return res

def main():
    e = {x["assetId"]: x for x in json.load(open(CAT))}.get(AID)
    if not e: print(f"RECOLOUR_AUDIT {AID} SKIP no-entry"); sys.exit(3)
    cv = e.get("colourVariants") or {}
    if not cv or CA not in cv or CB not in cv:
        print(f"RECOLOUR_AUDIT {AID} SKIP single-neutral-or-missing-variants"); sys.exit(3)
    ma = render_variant(cv[CA], CA); mb = render_variant(cv[CB], CB)
    if ma is None or mb is None:
        print(f"RECOLOUR_AUDIT {AID} SKIP render-failed"); sys.exit(3)
    dist = float(np.linalg.norm(ma-mb))
    ok = dist >= 0.08        # body colour must move meaningfully between two DVLA colours
    print(f"RECOLOUR_AUDIT {AID} {'PASS' if ok else 'FAIL'} dist={dist:.3f} "
          f"{CA}={[round(x,2) for x in ma]} {CB}={[round(x,2) for x in mb]}")
    sys.exit(0 if ok else 2)

main()
