"""loft_body.py — Alam 3D NURBS body: loft a CAD-grade car shell with
openNURBS (rhino3dm) from REAL cross-sections of a ground-truth mesh.

Why: build_golf.py proved a car guessed from primitives never reads as the
car. This does the opposite — every section is measured from the 1-of-1
ground-truth model, so the silhouette and proportions are real by
construction; the NURBS loft contributes the factory-smooth surface.

Output:
  <out>.3dm — native openNURBS/Rhino file: the section NURBS curves
              ("the lines") + the lofted degree-3 surface. The owned CAD asset.
  <out>.glb — dense tessellation with a Car_Paint material (paint-named, so
              the render worker resprays it cleanly). Body shell only — run
              cabin_assembly (glass+interior) and wheel_replace (wheels+arches)
              to finish it for the gates.

Usage:
  python3 pipeline/nurbs/loft_body.py <ground_truth.glb> <out_base>
      [--stations 72] [--levels 34] [--shell body,glass,...]
Axes: expects glTF y-up scene (x width, y height, z length) via trimesh.
"""
import sys

import numpy as np
import rhino3dm
import trimesh

SRC = sys.argv[1]
OUT = sys.argv[2]
argv = sys.argv[3:]


def arg(f, d):
    return type(d)(argv[argv.index(f) + 1]) if f in argv else d


N_ST = arg("--stations", 72)
N_LV = arg("--levels", 34)
SHELL = set(arg("--shell",
                "body,glass,r_glass,d_glass,vd_glass,black_matt,chrome").split(","))

sc = trimesh.load(SRC, force="scene")
parts = []
for g in sc.dump():
    mat = getattr(g.visual, "material", None)
    if mat is not None and (mat.name or "?") in SHELL:
        parts.append(g)
mesh = trimesh.util.concatenate(parts)
V = np.asarray(mesh.vertices)
lo, hi = V.min(0), V.max(0)
print(f"shell verts {len(V):,}  W={hi[0]-lo[0]:.2f} H={hi[1]-lo[1]:.2f} L={hi[2]-lo[2]:.2f}")
cx = (lo[0] + hi[0]) / 2

# ---- measured section grid (TRUE plane sections) -----------------------------
# v1 sampled loose vertex slabs: empty height bins collapsed to zero width and
# interior structure dented the hull — the render melted. v2 cuts real
# cross-sections, takes the outer silhouette per height level, interpolates
# levels no section reaches, and median-filters the grid before smoothing.
zs = np.linspace(lo[2] + 0.004 * (hi[2] - lo[2]),
                 hi[2] - 0.004 * (hi[2] - lo[2]), N_ST)
grid = np.zeros((N_ST, N_LV, 2))          # (station, level) -> (half_width, y)
# section floor = sill height: sections that dive into the wheel wells hang
# "curtain" lobes off the loft at all four corners. Flooring every section at
# the sill bridges the wells smoothly — wheel_replace then cuts the arches
# open and adds parametric wheels + liners, its exact job.
y_lo_g, y_hi_g = lo[1] + 0.11 * (hi[1] - lo[1]), hi[1]
for i, z in enumerate(zs):
    sec = mesh.section(plane_origin=[0, 0, z], plane_normal=[0, 0, 1])
    if sec is None:
        grid[i, :, 0] = np.nan
        grid[i, :, 1] = np.linspace(y_lo_g, y_hi_g, N_LV)
        continue
    pts = np.asarray(sec.vertices)
    y0 = max(np.percentile(pts[:, 1], 2), y_lo_g)
    y1 = np.percentile(pts[:, 1], 99.5)
    ys = np.linspace(y0, y1, N_LV)
    dy = (ys[1] - ys[0]) * 1.2
    w = np.full(N_LV, np.nan)
    for j, y in enumerate(ys):
        band = pts[np.abs(pts[:, 1] - y) < dy]
        if len(band) >= 2:
            w[j] = np.percentile(np.abs(band[:, 0] - cx), 98)
    # interpolate levels the section never crossed
    ok = np.isfinite(w)
    if ok.sum() >= 4:
        w[~ok] = np.interp(np.flatnonzero(~ok), np.flatnonzero(ok), w[ok])
    else:
        w[:] = np.nan
    # mirror guard: above 55% of section height the body tapers (tumblehome)
    j55 = int(0.55 * (N_LV - 1))
    if np.isfinite(w).all():
        w[j55:] = np.minimum.accumulate(np.maximum(w[j55:], 1e-4))
        w[j55:] = np.minimum(w[j55:], w[j55 - 1])
    grid[i, :, 0] = w
    grid[i, :, 1] = ys

# stations with no/degenerate section: interpolate from neighbours
bad = ~np.isfinite(grid[:, :, 0]).all(1)
if bad.any():
    for j in range(N_LV):
        for k in (0, 1):
            grid[bad, j, k] = np.interp(
                np.flatnonzero(bad), np.flatnonzero(~bad), grid[~bad, j, k])

# 3-wide median filter along stations kills single-station dents (handles,
# grille cavities), then gentle clay smoothing both ways
med = grid.copy()
med[1:-1, :, 0] = np.median(
    np.stack([grid[:-2, :, 0], grid[1:-1, :, 0], grid[2:, :, 0]]), axis=0)
grid = med
for _ in range(2):
    grid[1:-1] = 0.5 * grid[1:-1] + 0.25 * (grid[:-2] + grid[2:])
    grid[:, 1:-1] = 0.5 * grid[:, 1:-1] + 0.25 * (grid[:, :-2] + grid[:, 2:])

# ---- control net: left sill -> over the roof -> right sill -------------------
cols = []
for j in range(N_LV):
    cols.append((-1, j))
for j in range(N_LV - 1, -1, -1):
    cols.append((+1, j))
K = len(cols)
net = np.zeros((N_ST, K, 3))
for i in range(N_ST):
    for c, (s, j) in enumerate(cols):
        wv, yv = grid[i, j]
        net[i, c] = (cx + s * wv, yv, zs[i])

# ---- openNURBS: section curves + lofted surface ------------------------------
model = rhino3dm.File3dm()
model.Settings.ModelUnitSystem = rhino3dm.UnitSystem.Meters
lay_c = rhino3dm.Layer(); lay_c.Name = "alam_sections"; model.Layers.Add(lay_c)
lay_s = rhino3dm.Layer(); lay_s.Name = "alam_body"; model.Layers.Add(lay_s)
for i in range(N_ST):
    pts = [rhino3dm.Point3d(*net[i, c]) for c in range(K)]
    cu = rhino3dm.NurbsCurve.Create(False, 3, pts)
    att = rhino3dm.ObjectAttributes(); att.LayerIndex = 0
    model.Objects.AddCurve(cu, att)

srf = rhino3dm.NurbsSurface.Create(3, False, 4, 4, N_ST, K)
# rhino3dm's Create() leaves knot vectors unset — PointAt returns NaN until
# clamped uniform knots exist (found the hard way: the loft evaluated to a
# NaN slab). CreateUniformKnots gives a valid clamped-uniform vector.
srf.KnotsU.CreateUniformKnots(1.0)
srf.KnotsV.CreateUniformKnots(1.0)
for i in range(N_ST):
    for c in range(K):
        srf.Points[(i, c)] = rhino3dm.Point4d(*net[i, c], 1.0)
att = rhino3dm.ObjectAttributes(); att.LayerIndex = 1
model.Objects.AddSurface(srf, att)
model.Write(OUT + ".3dm", 8)
print(f"NURBS_3DM {OUT}.3dm  ({N_ST} section curves + lofted surface)")

# ---- tessellate the NURBS surface -> GLB -------------------------------------
du, dv = srf.Domain(0), srf.Domain(1)
RU, RV = N_ST * 5, K * 4
us = np.linspace(du.T0, du.T1, RU)
vs_ = np.linspace(dv.T0, dv.T1, RV)
P = np.zeros((RU, RV, 3))
for a, u in enumerate(us):
    for b, vv in enumerate(vs_):
        p = srf.PointAt(u, vv)
        P[a, b] = (p.X, p.Y, p.Z)
assert np.isfinite(P).all(), "NURBS evaluation produced NaN — check knots"
verts = P.reshape(-1, 3)
faces = []
for a in range(RU - 1):
    r0, r1 = a * RV, (a + 1) * RV
    for b in range(RV - 1):
        faces.append((r0 + b, r1 + b, r1 + b + 1))
        faces.append((r0 + b, r1 + b + 1, r0 + b + 1))
body = trimesh.Trimesh(vertices=verts, faces=np.array(faces))
body.visual = trimesh.visual.TextureVisuals(
    material=trimesh.visual.material.PBRMaterial(
        name="Car_Paint", baseColorFactor=[140, 143, 148, 255],
        metallicFactor=0.4, roughnessFactor=0.35))
scene_out = trimesh.Scene({"alam_body": body})
scene_out.export(OUT + ".glb")
print(f"NURBS_GLB {OUT}.glb  ({len(verts):,} verts, {len(faces):,} tris)")
print("LOFT_OK")
