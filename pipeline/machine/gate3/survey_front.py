#!/usr/bin/env python3
"""survey_front.py -- directed depth survey of the front fascia.

Fires a (y,z) grid of rays straight down +X into the nose (the nose is at
-X on this file -- verified by render, see front_diag.py) and records:

  d1  first-hit depth from the nose plane   -> the fascia surface itself
  g1  which geometry that first hit belongs to
  d2  second-hit depth                      -> what sits BEHIND the skin,
                                               i.e. how deep an aperture or
                                               a duct may go before it
                                               strikes the melt
Nothing here uses a material name or a face normal.  Output: front.npz plus
depth/label PNGs to LOOK at (the arbiter, per project standard).

Run: python3 survey_front.py <car.glb> <out.npz> <outdir>
"""
import os
import sys
import numpy as np
import trimesh

CAR, OUT, ODIR = sys.argv[1], sys.argv[2], sys.argv[3]
os.makedirs(ODIR, exist_ok=True)
RES = 0.004

sc = trimesh.load(CAR, force="scene")
names = list(sc.geometry.keys())
meshes = [sc.geometry[n] for n in names]
gof = np.concatenate([[0]] + [np.cumsum([len(m.faces) for m in meshes])])
occ = trimesh.util.concatenate(meshes)
inter = trimesh.ray.ray_pyembree.RayMeshIntersector(occ)

V = occ.vertices
XMIN, GY = float(V[:, 0].min()), float(V[:, 1].min())
H = float(np.percentile(V[:, 1], 99.8)) - GY
HW = float(np.percentile(np.abs(V[:, 2]), 99.7))
print(f"XMIN {XMIN:.4f} ground {GY:.4f} H {H:.4f} halfW {HW:.4f}")

ys = np.arange(GY + 0.02, GY + 0.86 * H, RES)
zs = np.arange(-HW - 0.06, HW + 0.06, RES)
ZZ, YY = np.meshgrid(zs, ys)
N = ZZ.size
X0 = XMIN - 0.60
org = np.stack([np.full(N, X0), YY.ravel(), ZZ.ravel()], 1)
dr = np.tile([1.0, 0.0, 0.0], (N, 1))
print(f"grid {YY.shape} = {N} rays, res {RES*1000:.0f}mm")

d1 = np.full(N, np.nan)
d2 = np.full(N, np.nan)
g1 = np.full(N, -1, dtype=np.int8)
CH = 60000
for s in range(0, N, CH):
    e = min(s + CH, N)
    loc, iray, itri = inter.intersects_location(org[s:e], dr[s:e], multiple_hits=True)
    if not len(iray):
        continue
    t = loc[:, 0] - X0
    o = np.lexsort((t, iray))
    iray, itri, t = iray[o], itri[o], t[o]
    first = np.ones(len(iray), bool)
    first[1:] = iray[1:] != iray[:-1]
    fi = np.nonzero(first)[0]
    d1[s + iray[fi]] = t[fi]
    g1[s + iray[fi]] = np.searchsorted(gof, itri[fi], side="right") - 1
    si = fi + 1
    ok = (si < len(iray)) & np.r_[iray[np.clip(fi + 1, 0, len(iray) - 1)] == iray[fi]]
    d2[s + iray[fi[ok]]] = t[si[ok]]
    print(f"  {e}/{N}", flush=True)

sh = YY.shape
D1 = d1.reshape(sh) - 0.60          # depth measured from the nose-most point
D2 = d2.reshape(sh) - 0.60
G1 = g1.reshape(sh)
hit = np.isfinite(D1)
print(f"silhouette: {hit.sum()} of {N} cells hit ({100*hit.mean():.1f}%)")
print(f"depth range {np.nanmin(D1)*1000:.0f}..{np.nanpercentile(D1,99)*1000:.0f} mm")
for gi, n in enumerate(names):
    m = G1 == gi
    print(f"  first-hit {n:12s} {m.sum():7d} cells ({100*m.sum()/max(hit.sum(),1):5.1f}% of silhouette)")

np.savez_compressed(OUT, D1=D1, D2=D2, G1=G1, ys=ys, zs=zs,
                    XMIN=XMIN, GY=GY, H=H, HW=HW, names=np.array(names))

try:
    from PIL import Image
    lo, hi = np.nanpercentile(D1, 0.5), np.nanpercentile(D1, 99.0)
    img = np.clip((D1 - lo) / max(hi - lo, 1e-6), 0, 1)
    img = np.where(hit, img, 1.0)
    Image.fromarray((img[::-1] * 255).astype(np.uint8)).save(
        os.path.join(ODIR, "front_depth.png"))
    PAL = np.array([[220, 40, 40], [240, 190, 30], [40, 120, 240],
                    [30, 30, 30], [240, 90, 190], [30, 190, 90], [235, 235, 235]])
    Image.fromarray(PAL[np.where(G1 >= 0, G1, 6)][::-1].astype(np.uint8)).save(
        os.path.join(ODIR, "front_label.png"))
    print("wrote depth/label PNGs")
except Exception as ex:
    print("png skipped:", ex)
print("SURVEY_DONE", OUT)
