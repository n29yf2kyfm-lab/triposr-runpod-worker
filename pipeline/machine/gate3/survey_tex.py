#!/usr/bin/env python3
"""survey_tex.py -- orthographic texture view of the front fascia.

Same (y,z) ray grid as survey_front, but each cell also records the FIRST
HIT TRIANGLE, its barycentric coordinate and the baseColorTexture texel
there.  The result is a dead-ahead orthographic image of the car's own
baked texture: the landmark source for where the lamps, grille, badge and
plate actually are.

Why the texture is admissible here and not always: CLAUDE.md records that
texture-based selection fails on DARK cars, where glass, dark paint and
dark trim share one near-black value (58% of the test Golf R's texels below
luminance 40).  This car's body texture is RED, so lamp/grille/trim texels
separate from body texels by hue, not brightness.  That is the favourable
case the record names, and the separation is measured below rather than
assumed.

FALSIFICATION, written before running: if the texture carries no usable
landmark, the fascia's texel population will be unimodal in hue/saturation
and a "non-body" mask will not form connected lamp- and grille-shaped
regions.  The mask is rendered as a PNG and looked at.

Run: python3 survey_tex.py <car.glb> <out.npz> <outdir>
"""
import os
import sys
import numpy as np
import trimesh
from PIL import Image

CAR, OUT, ODIR = sys.argv[1], sys.argv[2], sys.argv[3]
os.makedirs(ODIR, exist_ok=True)
RES = 0.003

sc = trimesh.load(CAR, force="scene")
names = list(sc.geometry.keys())
meshes = [sc.geometry[n] for n in names]
counts = [len(m.faces) for m in meshes]
gof = np.concatenate([[0], np.cumsum(counts)])
occ = trimesh.util.concatenate(meshes)
inter = trimesh.ray.ray_pyembree.RayMeshIntersector(occ)

V = occ.vertices
XMIN, GY = float(V[:, 0].min()), float(V[:, 1].min())
H = float(np.percentile(V[:, 1], 99.8)) - GY
HW = float(np.percentile(np.abs(V[:, 2]), 99.7))

# per-geometry texture arrays + per-face UV (mean of the 3 corners)
TEX, FUV = [], []
for m in meshes:
    im = None
    try:
        mat = m.visual.material
        if getattr(mat, "baseColorTexture", None) is not None:
            im = np.asarray(mat.baseColorTexture.convert("RGB"))
    except Exception:
        im = None
    TEX.append(im)
    uv = getattr(m.visual, "uv", None)
    FUV.append(np.asarray(uv)[m.faces].mean(1) if uv is not None else None)
    print("tex" if im is not None else "no-tex",
          im.shape if im is not None else "-", "faces", len(m.faces))

ys = np.arange(GY + 0.02, GY + 0.72 * H, RES)
zs = np.arange(-HW - 0.05, HW + 0.05, RES)
ZZ, YY = np.meshgrid(zs, ys)
N = ZZ.size
X0 = XMIN - 0.60
org = np.stack([np.full(N, X0), YY.ravel(), ZZ.ravel()], 1)
dr = np.tile([1.0, 0.0, 0.0], (N, 1))
print(f"grid {YY.shape} = {N} rays at {RES*1000:.0f}mm")

D = np.full(N, np.nan, np.float32)
TRI = np.full(N, -1, np.int64)
CH = 40000
for s in range(0, N, CH):
    e = min(s + CH, N)
    loc, iray, itri = inter.intersects_location(org[s:e], dr[s:e], multiple_hits=False)
    if len(iray):
        D[s + iray] = loc[:, 0] - X0 - 0.60
        TRI[s + iray] = itri

RGB = np.zeros((N, 3), np.uint8)
GID = np.searchsorted(gof, TRI, side="right") - 1
GID[TRI < 0] = -1
for gi in range(len(meshes)):
    sel = np.nonzero(GID == gi)[0]
    if not len(sel):
        continue
    if TEX[gi] is None or FUV[gi] is None:
        RGB[sel] = (110, 110, 118)
        continue
    lf = TRI[sel] - gof[gi]
    uv = FUV[gi][lf]
    t = TEX[gi]
    px = np.clip((uv[:, 0] % 1.0) * (t.shape[1] - 1), 0, t.shape[1] - 1).astype(int)
    py = np.clip((1 - uv[:, 1] % 1.0) * (t.shape[0] - 1), 0, t.shape[0] - 1).astype(int)
    RGB[sel] = t[py, px]

sh = YY.shape
IM = RGB.reshape(*sh, 3)
DM = D.reshape(sh)
GM = GID.reshape(sh)
Image.fromarray(IM[::-1]).save(os.path.join(ODIR, "front_tex.png"))
print("wrote", os.path.join(ODIR, "front_tex.png"), IM.shape)

# hue/saturation separation, measured on the FASCIA only
F = np.isfinite(DM) & (DM < 0.45)
f = IM[F].astype(np.float32)
mx, mn = f.max(1), f.min(1)
sat = (mx - mn) / np.clip(mx, 1, None)
redish = (f[:, 0] > f[:, 1] + 18) & (f[:, 0] > f[:, 2] + 18)
print(f"fascia texels {F.sum()}  mean RGB {f.mean(0).round(1)}")
print(f"  red-dominant (body paint): {100*redish.mean():.1f}%")
print(f"  saturation p10/p50/p90: {np.round(np.percentile(sat,[10,50,90]),3)}")
print(f"  luma<70 & not red-dominant (lamp/grille/trim): "
      f"{100*((mx<70)&~redish).mean():.1f}%")

np.savez_compressed(OUT, IM=IM, DM=DM, GM=GM, ys=ys, zs=zs,
                    GY=GY, H=H, HW=HW, XMIN=XMIN, names=np.array(names))
print("SURVEY_TEX_DONE")
