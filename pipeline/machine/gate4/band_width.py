#!/usr/bin/env python3
"""band_width.py — measure the LAMP BAND WIDTH from a straight rear render.

Criterion 4 is a proportion: the lit/lens band across the tail, as a ratio of
the car's own rear-face width in the SAME image. Measuring it in pixels of the
straight rear view is the honest way — it is the thing the eye judges, and it
needs no assumption about which material or label the lamp lives in.

Method: in the lamp height rows, a pixel is LENS if it is much darker than the
body and not background. Reports, per side, the outer and inner edge and the
centre gap. Silhouette width is measured on the same rows.

Run: python3 band_width.py <render.png> [label]
"""
import sys
import numpy as np
from PIL import Image

IMG = sys.argv[1]
TAG = sys.argv[2] if len(sys.argv) > 2 else IMG
a = np.asarray(Image.open(IMG).convert("RGB")).astype(np.float32)
Ht, Wd = a.shape[:2]
lum = a @ np.array([0.2126, 0.7152, 0.0722])

# background = the near-white plate the renders use; find the car silhouette
bg = lum > 205
car = ~bg
rows = np.where(car.any(1))[0]
cols = np.where(car.any(0))[0]
r0, r1 = rows.min(), rows.max()
print(f"{TAG}: car rows {r0}..{r1} ({r1-r0+1}px tall), cols {cols.min()}..{cols.max()}")

# lamp band rows: the measured landmark band 0.541..0.633 of car HEIGHT,
# measured from the GROUND up, so from the bottom of the silhouette
def row_for(hfrac):
    return int(round(r1 - hfrac * (r1 - r0)))


band = slice(row_for(0.66), row_for(0.50))
print(f"  lamp band rows {band.start}..{band.stop} (car height fraction 0.50..0.66)")

sub = a[band]; sublum = lum[band]; subcar = car[band]
wid = []
for k in range(sub.shape[0]):
    c = np.where(subcar[k])[0]
    if len(c):
        wid.append(c.max() - c.min() + 1)
sil = float(np.median(wid))
print(f"  silhouette width across the band: {sil:.0f} px (median of {len(wid)} rows)")

# LENS pixels: much darker than the surrounding body. Body here is bright red
# paint; a lens is near-neutral dark. Use luminance well below the body median.
bodylum = float(np.median(sublum[subcar]))
th = min(bodylum * 0.62, bodylum - 12)
lens = subcar & (sublum < th)
print(f"  body median luminance {bodylum:.1f}; lens threshold {th:.1f}; "
      f"lens pixels {int(lens.sum())} ({100*lens.sum()/subcar.sum():.1f}% of band)")

colcount = lens.sum(0)
present = colcount > 0.25 * lens.shape[0]     # a column is LENS if a quarter of the band rows are
cols_l = np.where(present)[0]
if len(cols_l) == 0:
    print("  NO lens band detected")
    raise SystemExit
cc = (cols.min() + cols.max()) / 2
left = cols_l[cols_l < cc]; right = cols_l[cols_l >= cc]
res = {}
for tag, arr in (("L", left), ("R", right)):
    if len(arr) == 0:
        print(f"  {tag}: none"); continue
    res[tag] = (int(arr.min()), int(arr.max()))
    print(f"  {tag} lens columns {arr.min()}..{arr.max()}  span {arr.max()-arr.min()+1}px "
          f"= {(arr.max()-arr.min()+1)/sil:.3f} of silhouette width")
if "L" in res and "R" in res:
    gap = res["R"][0] - res["L"][1]
    outer = res["R"][1] - res["L"][0] + 1
    print(f"  CENTRE GAP {gap}px = {gap/sil:.3f} of silhouette width")
    print(f"  OUTER SPAN (L outer edge -> R outer edge) {outer}px = {outer/sil:.3f}")
    cov = (res['L'][1]-res['L'][0]+1 + res['R'][1]-res['R'][0]+1) / sil
    print(f"  LENS COVERAGE (both lamps) = {cov:.3f} of silhouette width")
