"""NEGATIVE-CONTROL-BEARING self-check of raster.py's camera model.
If the rasterised Body_Shell mask does not agree with Blender's own label pass,
nothing downstream of raster.py may be believed."""
import json, sys, numpy as np, trimesh
from PIL import Image
import raster

sc = trimesh.load("car_rebound.glb", force="scene", process=False)
T,gn = sc.graph["Body_Shell"]; g = sc.geometry[gn]
V = trimesh.transform_points(g.vertices, T); F = np.asarray(g.faces)
Vb = raster.gltf_to_blender(V)
cams,cfg = raster.cams_from_cfg("rig_cfg.json")

def srgb8(l):
    c=np.asarray(l,float)/255.0
    s=np.where(c<=0.0031308,c*12.92,1.055*np.power(c,1/2.4)-0.055)
    return np.clip(np.rint(s*255.0),0,255).astype(int)
LEV=srgb8(np.array([40+i*43 for i in range(6)]))
lbl=json.load(open("r_before/labelsall.json"))
bs=srgb8(np.array(lbl["Body_Shell"]))
print("Body_Shell label colour (linear)",lbl["Body_Shell"],"-> expected sRGB",bs)

view=sys.argv[1] if len(sys.argv)>1 else "az270_e05"
a=np.asarray(Image.open(f"r_before/label_all_{view}.png").convert("RGB")).astype(int)
d=np.abs(a[...,None]-LEV[None,None,None,:]); a=LEV[d.argmin(-1)]
blender_mask = (a[:,:,0]==bs[0])&(a[:,:,1]==bs[1])&(a[:,:,2]==bs[2])

idb,_ = raster.rasterise(cams[view], Vb, F)
mine = idb>0
# Blender's mask is Body_Shell WHERE VISIBLE past every other node; mine has no
# occluders, so mine must be a SUPERSET. The test is on the superset relation
# plus agreement on the silhouette.
inter=(mine&blender_mask).sum(); bonly=(blender_mask&~mine).sum()
print(f"view {view}: blender Body_Shell px={blender_mask.sum()}  raster px={mine.sum()}")
print(f"  agreement: blender-only (raster MISSED) = {bonly}  ({100*bonly/max(blender_mask.sum(),1):.3f}%)")
print(f"  intersection = {inter} ({100*inter/max(blender_mask.sum(),1):.3f}% of blender mask)")
ys,xs=np.where(blender_mask)
ys2,xs2=np.where(mine)
print(f"  blender bbox x[{xs.min()},{xs.max()}] y[{ys.min()},{ys.max()}]")
print(f"  raster  bbox x[{xs2.min()},{xs2.max()}] y[{ys2.min()},{ys2.max()}]")
ok = bonly/max(blender_mask.sum(),1) < 0.01
print("CAMERA MODEL", "VALIDATED" if ok else "*** MISMATCH — DO NOT PROCEED ***")
# NEGATIVE CONTROL: a deliberately wrong camera must FAIL this test.
bad = raster.Cam(np.array(cfg["cameras"][view]["loc"])+np.array([0.35,0,0]),
                 cfg["cameras"][view]["look"], cfg["lens_mm"], cfg["resolution"])
idb2,_ = raster.rasterise(bad, Vb, F)
bonly2 = (blender_mask&~(idb2>0)).sum()
print(f"NEGATIVE CONTROL (camera shifted 350mm): blender-only = {bonly2} "
      f"({100*bonly2/blender_mask.sum():.3f}%) -> must be >> 1%: "
      f"{'CONTROL FIRES' if bonly2/blender_mask.sum()>0.01 else '*** CONTROL DID NOT FIRE ***'}")
