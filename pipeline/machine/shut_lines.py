#!/usr/bin/env python3
"""shut_lines.py — engrave the panel gaps the generator could not resolve.

THE PROBLEM, measured. Image-to-3D models here work on a sparse voxel grid;
Pixal3D runs at 1536 which is ~2.5mm per voxel on a 3.885m car. A real shut
line is 2-4mm wide, so the grid gets roughly ONE sample across it and Nyquist
needs two. Shut lines therefore come out faint or absent no matter what is
done upstream — resolution, seed, input prep, view count and five different
generators have all been tried and measured, and the melt survived all of them.

THE INSIGHT. The lines are not missing from the DATA, only from the GEOMETRY.
The camera saw them and the texture carries them. So they can be recovered
from evidence instead of invented from a template — which is what shelved this
idea the first time round ("synthetic lines without semantics risk drawing
wrong ones"). Nothing here draws a line the photograph does not show.

WHERE TO LOOK, and this cost one wrong attempt. Hunting the lines in the UV
TEXTURE does NOT work: the atlas is hundreds of small islands and a black-hat
filter spends its response on island seams and wheel spokes. Measured on the
PE12 car, a usable threshold lit 2.05% of a 4096x4096 texture and almost none
of it was a shut line. In IMAGE space it works — on a rendered view the same
filter traces the door gap, the bonnet split, the arch edges and the bumper
seams cleanly, because the surface is continuous there.

METHOD
  1. For each calibrated view, black-hat the luminance. Black-hat isolates
     THIN DARK features and ignores broad shading, which is the difference
     between a shut line and a shadow.
  2. Subtract the per-view glass / wheel / lamp masks the seg stage already
     renders, DILATED, so window surrounds, spokes and lamp outlines cannot
     be mistaken for panel gaps. Only lines lying on PAINT survive.
  3. Project face centroids through the camera and keep the faces that are the
     first visible surface at their pixel — the same z-buffer test seg_project
     uses, with the same mesh-relative tolerance (a camera-relative tolerance
     was measured to let the inner skin take the window mask).
  4. Accumulate a per-face score across views and normalise by how often each
     face was seen, so a face visible twice is not outvoted by one visible ten
     times.
  5. Displace the vertices of scoring faces INWARD along the vertex normal.

WHY INWARD DISPLACEMENT AND NOT A NORMAL MAP. A normal map is the safer first
move and is worth having, but it cannot occlude, so a shut line rendered that
way vanishes at a grazing angle — exactly the 3/4 view a car is judged from.
The mesh is dense enough to hold the groove (552k faces on the paint alone,
far finer than the voxel grid that failed to create it), so the geometry can
carry what the generator could not.

Run: python3 shut_lines.py <in.glb> <views_dir> <out.glb>
Env: LINE_DEPTH_MM (default 1.2), LINE_MIN_SCORE (0.35), LINE_BH_KERNEL (7),
     LINE_THRESH (18), SEG_DEPTH_TOL_FRAC (0.0025)
"""
import json
import os
import sys

import cv2
import numpy as np
import trimesh
from PIL import Image

import Imath
import OpenEXR

INP, VIEWS, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
DEPTH_MM = float(os.environ.get("LINE_DEPTH_MM", "1.2"))
MIN_SCORE = float(os.environ.get("LINE_MIN_SCORE", "0.35"))
KERNEL = int(os.environ.get("LINE_BH_KERNEL", "7"))
THRESH = int(os.environ.get("LINE_THRESH", "18"))
TOL_FRAC = float(os.environ.get("SEG_DEPTH_TOL_FRAC", "0.0025"))
PAINT_HINT = os.environ.get("LINE_PAINT_MAT", "carpaint")

sc = trimesh.load(INP, force="scene")
names = list(sc.geometry.keys())
paint = [n for n in names
         if PAINT_HINT in str(getattr(getattr(sc.geometry[n].visual, "material",
                                              None), "name", n)).lower()
         or PAINT_HINT in n.lower()]
if not paint:
    raise SystemExit(f"REFUSED: no geometry whose material or name contains "
                     f"'{PAINT_HINT}' in {names} — engraving the wrong "
                     "material would cut grooves into glass or tyres")
print(f"paint geometry: {paint}")

gm = sc.geometry[paint[0]]
V = gm.vertices.view(np.ndarray).copy()
Ffaces = gm.faces.view(np.ndarray)
cent = V[Ffaces].mean(1)
F = len(Ffaces)
whole = trimesh.util.concatenate([g for g in sc.geometry.values()])
CAR_DIAG = float(np.linalg.norm(whole.extents))
print(f"{F} paint faces, car diagonal {CAR_DIAG:.3f}")

# Blender's glTF importer converts Y-up -> Z-up: (x,y,z) -> (x,-z,y). The
# cameras were saved in BLENDER world space, so the centroids must move there
# before projecting — the same conversion seg_project does.
bcent = np.stack([cent[:, 0], -cent[:, 2], cent[:, 1]], 1)
cams = json.load(open(os.path.join(VIEWS, "cameras.json")))


def read_depth(fp):
    ex = OpenEXR.InputFile(fp)
    hdr = ex.header()
    dw = hdr["dataWindow"]
    W = dw.max.x - dw.min.x + 1
    H = dw.max.y - dw.min.y + 1
    ch = "R" if "R" in hdr["channels"] else list(hdr["channels"])[0]
    return np.frombuffer(ex.channel(ch, Imath.PixelType(Imath.PixelType.FLOAT)),
                         dtype=np.float32).reshape(H, W)


def line_image(vname, R):
    """Thin dark features on PAINT only, as a boolean image."""
    rgba = np.array(Image.open(os.path.join(VIEWS, f"{vname}.png"))
                    .convert("RGBA"))
    alpha = rgba[:, :, 3] > 8
    grey = cv2.cvtColor(rgba[:, :, :3], cv2.COLOR_RGB2GRAY)
    se = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (KERNEL, KERNEL))
    bh = cv2.morphologyEx(grey, cv2.MORPH_BLACKHAT, se)
    lines = (bh > THRESH) & alpha
    # EXCLUDE the non-paint classes, dilated. Undilated, the one-pixel border
    # of a window or a wheel reads as a perfect thin dark line and would be
    # engraved as a panel gap — the strongest false positive in the whole
    # method, since those borders are exactly what black-hat likes most.
    kd = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (KERNEL * 2 + 1,) * 2)
    for cls in ("glass", "wheel", "lamp"):
        fp = os.path.join(VIEWS, f"{vname}_{cls}.png")
        if not os.path.exists(fp):
            continue
        m = (np.array(Image.open(fp).convert("L")) > 127).astype(np.uint8)
        lines &= ~cv2.dilate(m, kd).astype(bool)
    # the SILHOUETTE is a dark edge against the background and is not a gap
    edge = cv2.dilate((~alpha).astype(np.uint8), kd).astype(bool)
    lines &= ~edge
    return lines


score = np.zeros(F, np.float32)
seen = np.zeros(F, np.float32)
for vname, c in cams.items():
    W2C = np.array(c["world_to_camera"])
    f = c["focal_px"]
    R = c["res"]
    depth = read_depth(os.path.join(VIEWS, c["depth_exr"]))
    pc = (W2C[:3, :3] @ bcent.T).T + W2C[:3, 3]
    z = -pc[:, 2]
    ok = z > 1e-6
    u = (R / 2 + f * pc[:, 0] / z).round().astype(int)
    v = (R / 2 - f * pc[:, 1] / z).round().astype(int)
    ok &= (u >= 0) & (u < R) & (v >= 0) & (v < R)
    ray = np.linalg.norm(pc, axis=1)
    dpx = np.full(F, 1e10, np.float32)
    dpx[ok] = depth[v[ok], u[ok]]
    tol = TOL_FRAC * CAR_DIAG
    vis_z = ok & (np.abs(dpx - z) < tol)
    vis_r = ok & (np.abs(dpx - ray) < tol)
    vis = vis_z if vis_z.sum() >= vis_r.sum() else vis_r   # self-calibrate
    li = line_image(vname, R)
    hit = np.zeros(F, bool)
    hit[vis] = li[v[vis], u[vis]]
    score += hit
    seen += vis
    print(f"{vname}: visible {int(vis.sum()):6d}  line-faces {int(hit.sum()):5d}")

has = seen > 0
norm = np.zeros(F, np.float32)
norm[has] = score[has] / seen[has]
sel = norm >= MIN_SCORE
print(f"faces scoring >= {MIN_SCORE}: {int(sel.sum())} "
      f"({100 * sel.mean():.2f}% of paint)")
if sel.sum() == 0:
    raise SystemExit("REFUSED: nothing scored — engraving nothing would ship a "
                     "file identical to its input while claiming a fix")

# per-VERTEX weight from face scores, so the groove has soft shoulders rather
# than a one-triangle cliff that reads as faceting
vw = np.zeros(len(V), np.float32)
cnt = np.zeros(len(V), np.float32)
np.add.at(vw, Ffaces.ravel(), np.repeat(norm, 3))
np.add.at(cnt, Ffaces.ravel(), 1.0)
vw[cnt > 0] /= cnt[cnt > 0]
vw[vw < MIN_SCORE] = 0.0

gm.fix_normals()
vn = gm.vertex_normals
depth_units = DEPTH_MM / 1000.0
gm.vertices = V - vn * (vw[:, None] * depth_units)
moved = int((vw > 0).sum())
print(f"displaced {moved} vertices inward by up to {DEPTH_MM:.2f}mm "
      f"({100 * moved / len(V):.2f}% of paint vertices)")

sc.export(OUT, include_normals=True)
print("wrote", OUT)
