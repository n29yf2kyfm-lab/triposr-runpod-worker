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
from skimage.morphology import skeletonize
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
THIN = os.environ.get("LINE_THIN", "1") == "1"
SHARP = os.environ.get("LINE_SHARP", "1") == "1"
MIN_LEN = int(os.environ.get("LINE_MIN_LEN", "40"))
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

# ENGRAVE EVERY PAINT GEOMETRY, NOT JUST THE FIRST.
# This used to be `sc.geometry[paint[0]]`, written when the body was ONE mesh
# ("552k faces on the paint alone", per the note above). premium.py now splits
# the body across named parts -- measured 2026-08-25 on the Golf, the paint is
# 7 geometries: Front_Wing_R, Front_Wing_L, Front_Bumper, Bonnet, carpaint,
# Rear_Bumper, Rear_Hatch. Taking paint[0] engraved the RIGHT FRONT WING ONLY
# (4,168 faces of the car) and reported success: 23 faces scored, 53 vertices
# moved. Silent, and exactly the shape of "shipped a file identical to its
# input while claiming a fix" that the refusal below exists to prevent.
# The parts are concatenated for scoring so a shut line running from wing to
# door is one connected structure, then the displacement is written back to
# each source geometry by vertex offset.
_parts, _off, _foff, _n, _fn = [], {}, {}, 0, 0
for _nm in paint:
    _g = sc.geometry[_nm]
    _off[_nm] = (_n, len(_g.vertices))
    _foff[_nm] = (_fn, len(_g.faces))
    _n += len(_g.vertices)
    _fn += len(_g.faces)
    _parts.append(_g)
V = np.vstack([g.vertices.view(np.ndarray) for g in _parts]).copy()
_fl, _base = [], 0
for g in _parts:
    _fl.append(g.faces.view(np.ndarray) + _base)
    _base += len(g.vertices)
Ffaces = np.vstack(_fl)
cent = V[Ffaces].mean(1)
F = len(Ffaces)
print(f"paint parts: {len(_parts)} geometries, {len(V)} verts, {F} faces")
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
    # LENGTH FILTER — and this one is why the first sharp pass FAILED. Thinning
    # plus full-depth displacement turned every speck of texture mottle into its
    # own little groove, and the finished door read as scratched paint. Crease
    # density went 35.9 -> 126.7 and looked like a triumph; it was measuring
    # NOISE, which is the exact failure mode that metric is documented to have
    # ("a noisy scan scores high for the wrong reason").
    # A shut line is a LONG CONNECTED STRUCTURE. Baked-lighting mottle is a
    # scatter of small blobs. Keep components whose bounding box spans at least
    # MIN_LEN pixels — that separates them cleanly and costs nothing.
    n, lab, stats, _ = cv2.connectedComponentsWithStats(
        lines.astype(np.uint8), connectivity=8)
    keep = np.zeros(n, bool)
    for i in range(1, n):
        w = stats[i, cv2.CC_STAT_WIDTH]
        h = stats[i, cv2.CC_STAT_HEIGHT]
        keep[i] = max(w, h) >= MIN_LEN
    lines = keep[lab]
    # SKELETONISE. Black-hat returns a BAND several pixels wide around a gap,
    # and a band displaced with soft shoulders becomes a shallow DISH — measured
    # at 1.2mm (invisible) and 4.0mm (still soft) because the depth was spread
    # across the band's whole width. Thinning to a single-pixel spine puts the
    # full depth where the gap actually is.
    if THIN:
        lines = skeletonize(lines)
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

# PER-VERTEX WEIGHT. v1 averaged the face scores into the vertices to give the
# groove "soft shoulders" and avoid a one-triangle cliff. That was the wrong
# instinct and it is what made the first two passes fail: averaging spreads the
# displacement over the band's full width, so the result is a shallow dish that
# the shading cannot catch. A real shut line is a narrow, deep, HARD-EDGED
# feature — the cliff is the point.
# ---------------------------------------------------------------- engrave
# LOCAL SUBDIVISION BEFORE DISPLACEMENT, and this is the whole reason v1 did
# nothing visible. Measured 2026-08-25 on the premium Golf: the paint's MEDIAN
# EDGE IS 18.58mm, so displacing a vertex 1.2mm tilts its triangle by 3.7
# degrees where a crease needs ~30 to read. The groove was in the geometry and
# no shading could catch it, and raising LINE_DEPTH_MM to 8mm (7x the real
# depth) changed the render not at all -- proving depth was never the problem.
# The selection was also CONFETTI at that density: 335 disconnected islands of
# ~3 vertices, because a 3mm-wide line projected onto 18.6mm triangles lands on
# scattered individual faces. The 2D filter is fine; the triangulation cannot
# hold what it finds.
#
# So refine first. Each subdivision halves the edge, and the band is grown by
# one ring so the groove has material either side of it.
#
# CRACK-FREE BY CONSTRUCTION. Subdividing only selected faces leaves T-junctions
# where the refined band meets its coarse neighbours. That is harmless HERE
# because the boundary vertices are FROZEN: a T-junction midpoint sits exactly
# on the coarse neighbour's straight edge, and if it never moves, no gap can
# open. Displacement is therefore restricted to vertices strictly interior to
# the refined band.
SUBDIV = int(os.environ.get("LINE_SUBDIV", "3"))
TARGET_MM = float(os.environ.get("LINE_TARGET_EDGE_MM", "4.0"))
depth_units = DEPTH_MM / 1000.0
tot_moved = 0

for _nm in paint:
    fs, fc = _foff[_nm]
    part_sel = sel[fs:fs + fc]
    if not part_sel.any():
        continue
    g = sc.geometry[_nm]
    pv = np.asarray(g.vertices, dtype=np.float64).copy()
    pf = np.asarray(g.faces)
    keep = np.where(part_sel)[0]

    # grow the selection by one vertex-ring so the groove has shoulders
    touched = np.zeros(len(pv), bool)
    touched[pf[keep].ravel()] = True
    band = np.where(touched[pf].any(1))[0]

    # Track scored-ness GEOMETRICALLY across subdivision, not by index.
    # trimesh's `return_index` is a dict {parent: [4 children]}, not a per-face
    # parent array; reading it as the latter mapped parent indices onto new-face
    # indices and made the scored set meaningless -- three renders showed no
    # groove while the bug was here, not in the method. Centroids are immune to
    # whatever the index convention is: a child face's centroid lies inside its
    # parent, so a radius query against the ORIGINAL scored centroids re-derives
    # the selection exactly, at any subdivision depth.
    from scipy.spatial import cKDTree
    seed_c = pv[pf[keep]].mean(1)
    seed_r = np.linalg.norm(pv[pf[keep][:, 0]] - pv[pf[keep][:, 1]],
                            axis=1).mean() * 0.75
    tree = cKDTree(seed_c)
    for _it in range(SUBDIV):
        bl = np.asarray(sorted(band), dtype=np.int64) if isinstance(band, set) \
            else np.asarray(band, dtype=np.int64)
        if len(bl) == 0:
            break
        el = np.linalg.norm(pv[pf[bl][:, 0]] - pv[pf[bl][:, 1]], axis=1)
        if np.median(el) * 1000.0 <= TARGET_MM:
            break
        pv, pf = trimesh.remesh.subdivide(pv, pf, face_index=bl)
        cen = pv[pf].mean(1)
        near = tree.query_ball_point(cen, seed_r)
        band = np.array([i for i, n in enumerate(near) if n], dtype=np.int64)
        if len(band) == 0:
            break
    cen = pv[pf].mean(1)
    near = tree.query_ball_point(cen, seed_r * 0.6)
    scored = set(int(i) for i, n in enumerate(near) if n)
    band = set(int(i) for i, n in enumerate(tree.query_ball_point(cen, seed_r)) if n)

    sc_idx = np.array(sorted(scored), dtype=np.int64)
    if len(sc_idx) == 0:
        continue
    # FROZEN = every vertex used by a face outside the refined band. Those are
    # the coarse neighbours and the T-junction seam; moving them cracks the hull.
    inband = np.zeros(len(pf), bool)
    inband[np.asarray(sorted(band), dtype=np.int64)] = True
    frozen = np.zeros(len(pv), bool)
    if (~inband).any():
        frozen[pf[~inband].ravel()] = True

    move = np.zeros(len(pv), bool)
    move[pf[sc_idx].ravel()] = True
    move &= ~frozen
    if not move.any():
        continue

    g2 = trimesh.Trimesh(vertices=pv, faces=pf, process=False)
    g2.fix_normals()
    vn = g2.vertex_normals
    pv = pv - vn * (move[:, None].astype(np.float64) * depth_units)

    ng = trimesh.Trimesh(vertices=pv, faces=pf, process=False)
    ng.visual = g.visual
    sc.geometry[_nm] = ng
    tot_moved += int(move.sum())
    print(f"  {_nm}: {int(part_sel.sum())} scored faces -> {len(pf)} faces after "
          f"subdiv, {int(move.sum())} verts displaced")

print(f"displaced {tot_moved} vertices inward by {DEPTH_MM:.2f}mm "
      f"(subdiv {SUBDIV}, target edge {TARGET_MM}mm)")
if tot_moved == 0:
    raise SystemExit("REFUSED: nothing displaced — a file identical to its "
                     "input must not ship as a fix")

sc.export(OUT, include_normals=True)
print("wrote", OUT)
