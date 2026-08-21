#!/usr/bin/env python3
"""tex_view.py -- GATE 3 v7: look at the front depth map and its node ownership.

Writes three PNGs (depth, ownership, and a depth-gradient/shaded view) plus a
text profile through the centreline.  This is a LOOKING tool: it renders what
was measured, it does not judge.

Run: python3 tex_view.py <ftex.npz> <outdir>
"""
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

NPZ, OUT = sys.argv[1], sys.argv[2]
os.makedirs(OUT, exist_ok=True)
d = np.load(NPZ, allow_pickle=True)
D, ys, zs, OWN, nodes = d["D"], d["ys"], d["zs"], d["OWN"], list(d["nodes"])
RES = float(d["RES"])

# image rows = y increasing UPWARD, cols = z.  The car faces -X, so +z is the
# car's LEFT; viewed from the front the car's left appears on the viewer's
# RIGHT.  Columns are therefore NOT flipped -- an image column of increasing z
# reads left-to-right as car-right -> car-left, which is what a front view is.
def to_img(a):
    return np.flipud(a)


SIL = np.isfinite(D)
print(f"depth range {np.nanmin(D)*1000:.1f} .. {np.nanmax(D)*1000:.1f} mm")

# ---------------------------------------------------------------- depth PNG
lo, hi = 0.0, 0.45
g = np.clip((np.where(SIL, D, hi) - lo) / (hi - lo), 0, 1)
img = (255 * (1.0 - g)).astype(np.uint8)          # proud = bright
rgb = np.dstack([img, img, img])
rgb[~SIL] = (40, 0, 60)
Image.fromarray(to_img(rgb)).resize((951 * 2, 501 * 2), Image.NEAREST).save(
    os.path.join(OUT, "depth.png"))

# ------------------------------------------------------------ ownership PNG
pal = np.array([
    [230, 25, 75], [60, 180, 75], [255, 225, 25], [0, 130, 200], [245, 130, 48],
    [145, 30, 180], [70, 240, 240], [240, 50, 230], [210, 245, 60], [250, 190, 190],
    [0, 128, 128], [230, 190, 255], [170, 110, 40], [255, 250, 200], [128, 0, 0],
    [170, 255, 195], [128, 128, 0], [255, 215, 180], [0, 0, 128], [128, 128, 128]])
own_rgb = np.zeros(D.shape + (3,), np.uint8)
own_rgb[...] = (30, 30, 30)
present = []
for i, n in enumerate(nodes):
    m = OWN == i
    if m.sum() == 0:
        continue
    own_rgb[m] = pal[len(present) % len(pal)]
    present.append((n, int(m.sum()), pal[len(present) % len(pal)]))
im = Image.fromarray(to_img(own_rgb)).resize((951 * 2, 501 * 2), Image.NEAREST)
dr = ImageDraw.Draw(im)
for k, (n, c, col) in enumerate(present):
    dr.rectangle([8, 8 + 18 * k, 26, 22 + 18 * k], fill=tuple(int(x) for x in col))
    dr.text((32, 8 + 18 * k), f"{n}  {c} cells", fill=(255, 255, 255))
im.save(os.path.join(OUT, "owner.png"))
print("owners on the frontmost surface:")
for n, c, _ in sorted(present, key=lambda t: -t[1]):
    print(f"  {n:22s} {c:7d} cells")

# ------------------------------------------------------- shaded / curvature
gy, gz = np.gradient(np.where(SIL, D, np.nan), RES)
sh = np.clip(0.5 - 2.0 * gz - 1.2 * gy, 0, 1)
sh = np.where(SIL, sh, 0.12)
Image.fromarray(to_img((255 * sh).astype(np.uint8))).resize(
    (951 * 2, 501 * 2), Image.NEAREST).save(os.path.join(OUT, "shaded.png"))

# ---------------------------------------------------------------- profiles
zc_i = int(np.argmin(np.abs(zs)))
print("\ncentreline profile (z=%.3f), y from top:" % zs[zc_i])
col = D[:, zc_i]
for j in range(len(ys) - 1, -1, -5):
    if np.isfinite(col[j]):
        print(f"   y {ys[j]:.3f}  D {col[j]*1000:7.1f} mm   owner "
              f"{nodes[OWN[j, zc_i]] if OWN[j,zc_i]>=0 else '-'}")
