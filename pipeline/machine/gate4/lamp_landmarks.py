#!/usr/bin/env python3
"""lamp_landmarks.py — find the TAIL LAMP landmarks from the baked texture.

This car has NO tail-lamp label and NO tail-lamp geometry: the matID render
at az090 shows one flat body colour across the whole tail, while the shaded
render shows two dark lamp smears. The lamps exist ONLY as dark texels in
carpaint's 4096^2 base-colour map. Those texels are the manufacturer's own
landmark and are the honest place to take the position from.

RIVAL THEORY, written before building (method rule): the hypothesis is
"dark texels in the tail band mark the tail lamps". It would be FALSIFIED if
the dark texels came out as one continuous full-width band (that would be a
shadow or a trim strip, not two lamps), or if they were scattered with no
left/right structure. The probe reports the spatial layout, so either
outcome is visible; it does not assume two clusters.

Run: python3 lamp_landmarks.py <glb> <out.json>
"""
import json
import sys
import numpy as np
import trimesh
from scipy import ndimage

GLB = sys.argv[1]
OUT = sys.argv[2] if len(sys.argv) > 2 else "lamp_landmarks.json"

sc = trimesh.load(GLB, force="scene")
cp = sc.geometry["carpaint"]
allv = np.vstack([g.vertices for g in sc.geometry.values()])
XMIN, XMAX = float(allv[:, 0].min()), float(allv[:, 0].max())
GY = float(allv[:, 1].min()); H = float(allv[:, 1].max()) - GY
L = XMAX - XMIN
HW = float(np.percentile(np.abs(allv[:, 2]), 99.7))

img = np.asarray(cp.visual.material.baseColorTexture.convert("RGB")).astype(np.float32)
TH, TW = img.shape[:2]
uv = np.asarray(cp.visual.uv)
fc = cp.triangles_center
fuv = uv[cp.faces].mean(1)
px = np.clip((fuv[:, 0] % 1.0) * (TW - 1), 0, TW - 1).astype(int)
py = np.clip((1.0 - (fuv[:, 1] % 1.0)) * (TH - 1), 0, TH - 1).astype(int)
col = img[py, px]
lum = col @ np.array([0.2126, 0.7152, 0.0722])

# TAIL-FACING zone. Selection is POSITIONAL only — never by face normal
# (46% of lamp-band body normals are flipped on this class of mesh).
tail = fc[:, 0] > XMAX - 0.16 * L
print(f"tail zone (x > {XMAX-0.16*L:.3f}): {int(tail.sum())} carpaint faces")
print(f"  luminance in the zone: p5={np.percentile(lum[tail],5):.1f} "
      f"p50={np.percentile(lum[tail],50):.1f} p95={np.percentile(lum[tail],95):.1f}")

DARK = float(np.percentile(lum[tail], 22))
dark = tail & (lum < DARK)
print(f"  dark threshold (p22) = {DARK:.1f} -> {int(dark.sum())} dark faces")

# ---- spatial layout of the dark texels: is it two lamps or one band? ----
print("\n  dark-face HEIGHT histogram (fraction of car height):")
hist = {}
for f0 in np.arange(0.10, 0.85, 0.05):
    s = dark & (fc[:, 1] >= GY + f0 * H) & (fc[:, 1] < GY + (f0 + 0.05) * H)
    hist[round(f0, 2)] = int(s.sum())
    if s.sum():
        print(f"    {f0:.2f}-{f0+0.05:.2f}H : {int(s.sum()):6d}  "
              f"z[{fc[s,2].min():+.2f},{fc[s,2].max():+.2f}]")

# lamp band = the contiguous height run with the strongest dark count above
# the glass sill and below the bumper shadow
cand = {k: v for k, v in hist.items() if 0.35 <= k <= 0.65}
peak = max(cand, key=cand.get)
band = dark & (fc[:, 1] > GY + (peak - 0.09) * H) & (fc[:, 1] < GY + (peak + 0.14) * H)
print(f"\n  lamp band peaks at {peak:.2f}H -> band {peak-0.09:.2f}..{peak+0.14:.2f}H, "
      f"{int(band.sum())} dark faces")

# left / right structure
zc = fc[band, 2]
print(f"  band z spread: {zc.min():+.3f} .. {zc.max():+.3f}")
gapz = np.histogram(zc, bins=24, range=(-HW, HW))[0]
print("  z histogram (24 bins across the width):")
print("   ", " ".join(f"{g:4d}" for g in gapz))
centre_frac = float(np.mean(np.abs(zc) < 0.18 * HW))
print(f"  fraction of band faces near the CENTRELINE (|z|<0.18 halfW): {centre_frac:.3f}")
if centre_frac > 0.25:
    print("  -> reads as ONE CONTINUOUS BAND (rival theory not excluded)")
else:
    print("  -> reads as TWO SEPARATE CLUSTERS (consistent with L/R lamps)")

res = {}
for sgn, tag in ((+1, "R"), (-1, "L")):
    s = band & (fc[:, 2] * sgn > 0.10 * HW)
    if s.sum() < 30:
        print(f"  {tag}: only {int(s.sum())} faces — no landmark")
        continue
    P = fc[s]
    d = dict(faces=int(s.sum()),
             x=[float(np.percentile(P[:, 0], 2)), float(np.percentile(P[:, 0], 98))],
             y=[float(np.percentile(P[:, 1], 2)), float(np.percentile(P[:, 1], 98))],
             z=[float(np.percentile(P[:, 2], 2)), float(np.percentile(P[:, 2], 98))],
             z_abs_max=float(np.percentile(np.abs(P[:, 2]), 98)))
    res[tag] = d
    print(f"  {tag} lamp landmark: {d['faces']} faces  "
          f"x[{d['x'][0]:.3f},{d['x'][1]:.3f}] y[{d['y'][0]:.3f},{d['y'][1]:.3f}] "
          f"z[{d['z'][0]:+.3f},{d['z'][1]:+.3f}]")

res["_frame"] = dict(XMIN=XMIN, XMAX=XMAX, GY=GY, H=H, L=L, HW=HW)
res["_band"] = dict(peak=float(peak), ylo=float(GY + (peak - 0.09) * H),
                    yhi=float(GY + (peak + 0.14) * H), dark_threshold=DARK,
                    centre_frac=centre_frac)
json.dump(res, open(OUT, "w"), indent=1)
print("\nwrote", OUT)
