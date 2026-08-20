#!/usr/bin/env python3
"""front_build.py -- GATE 3 / production brief Phase 7: front rebuild, v2.

Cuts the front apertures out of the melted shell and fits reconstructed
components into them.  Supersedes front_kit3.py (kept in git as the v1
record) and front_cut.py; they were split across two files and the
mirrored-outline sign handling was error-prone, so they are merged.

FRAME, MEASURED ON THIS FILE:  length on X, y up, z lateral, and
*** THE NOSE IS AT -X *** (verified by render).  The machine canon frame is
the opposite way round -- pipeline/machine/front_kit.py builds at XMAX and
on this car would put the whole front kit on the tailgate.  Depth D runs
BACKWARD from the nose plane: x = XMIN + D, so "proud" means SMALLER D.
Straight front is az 270; front 3/4s are az 215 and 305.

WHY THE SHELL IS CUT.  Measured: the melt's own surface sits up to 27 mm IN
FRONT of the fitted skin plane at the bottom of the grille band (shell 97 mm
vs fitted rim 120 mm at y=0.746).  Depth available for a grille built OVER
the shell is 18 mm at mid-band and negative at the bottom, so a real recess
is geometrically impossible without removing the intruding shell.  The brief
is explicit: replace, do not conceal.  Gate 5's coincident-vertex warning is
about MOVING one label's geometry (which tears the 25,369-pair seam);
deleting faces moves nothing, and the cut is applied to EVERY geometry over
the same footprint and depth window so the labels stay consistent.  Every
cut edge is overlapped by a >=12 mm flange on the insert.

ORIENTATION FROM CONSTRUCTION.  Components are extruded along -X, never
along a sampled body normal: 46% of body faces in the lamp band carry
inverted normals and that built three earlier lens passes inside-out.

SYMMETRY, AND THE ONE PLACE IT IS DELIBERATELY RELAXED.  Outlines are
designed once and mirrored.  Lens DEPTH is evaluated per side, because the
nose is measurably asymmetric -- at |z|=0.70 the -z bodywork is 120-200 mm
further back than +z -- and mirroring one depth sheet floated the left lens
in mid-air (v1's protruding slab, identified by component bisection).  The
outline, size and position stay symmetric; only the depth follows each
side's own bodywork, which is what a symmetric lamp in an asymmetric shell
must do.

Run: python3 front_build.py <car.glb> <ftex.npz> <out.glb> <report.json>
"""
import json
import os
import sys
import numpy as np
import trimesh
from scipy import ndimage
from trimesh.visual.material import PBRMaterial

CAR, TEX, OUT, REP = sys.argv[1:5]

d = np.load(TEX, allow_pickle=True)
DM, ys, zs = d["DM"], d["ys"], d["zs"]
GY, H, HW, XMIN = float(d["GY"]), float(d["H"]), float(d["HW"]), float(d["XMIN"])
RES = float(ys[1] - ys[0])
SIL = np.isfinite(DM)
SHELL = np.where(SIL, DM, 9.0)
print(f"frame XMIN {XMIN:.4f} GY {GY:.4f} H {H:.4f} halfW {HW:.4f}  NOSE AT -X")

REPORT = {"frame": {"XMIN": XMIN, "GY": GY, "H": H, "HW": HW}, "parts": [],
          "cuts": {}, "checks": {}}

# ----------------------------------------------------------------- outlines
LAMP_ZI, LAMP_ZO = 0.255, 0.700          # inner/outer |z|
LAMP_YC0, LAMP_YC1 = 0.7925, 0.7965
LAMP_HH0, LAMP_HH1 = 0.030, 0.058
NU, NV = 34, 14

GR_Y0, GR_Y1, GR_Z = 0.752, 0.838, 0.250
# LOWER INTAKE -- CONSTRUCTED, NOT FOUND.  Measured correction to an earlier
# reading of mine: the 258 mm plateau at y 0.374..0.415 is NOT an intake, it is
# the UNDERSIDE of the bumper's lower lip seen at a grazing angle (depth grows
# monotonically 48 -> 162 -> 258 -> 480 mm as y falls from 0.44 to 0.38).  Across
# y 0.44..0.60 the bumper face is a smooth 54..110 mm with no slot anywhere.
# This shell has no lower-intake aperture at all -- the Mk8's intake was never
# modelled, only crumpled into the bumper face.  So it is cut and built fresh,
# which is what the brief authorises for a section that cannot be repaired.
IN_Y0, IN_Y1, IN_Z = 0.458, 0.556, 0.460
PL_Y0, PL_Y1, PL_Z = 0.583, 0.697, 0.262

FLANGE = 0.014                           # insert overlaps remaining shell by this


def lamp_grid(side, dy=0.0, dz=0.0):
    u = np.linspace(0, 1, NU)
    zc = LAMP_ZI - dz + u * ((LAMP_ZO + dz) - (LAMP_ZI - dz))
    hh = (LAMP_HH0 + (LAMP_HH1 - LAMP_HH0) * u ** 0.7) + dy
    yc = LAMP_YC0 + (LAMP_YC1 - LAMP_YC0) * u
    Y = np.stack([np.linspace(yc[k] - hh[k], yc[k] + hh[k], NV) for k in range(NU)])
    Z = side * np.repeat(zc[:, None], NV, 1)
    return Y, Z


def rect_grid(y0, y1, z0, z1, ny, nz):
    Y = np.repeat(np.linspace(y0, y1, ny)[:, None], nz, 1)
    Z = np.repeat(np.linspace(z0, z1, nz)[None, :], ny, 0)
    return Y, Z


# ------------------------------------------------------------------ helpers
def idx(Y, Z):
    return (np.clip(np.searchsorted(ys, np.asarray(Y).ravel()), 0, len(ys) - 1),
            np.clip(np.searchsorted(zs, np.asarray(Z).ravel()), 0, len(zs) - 1))


def mask_of(Y, Z):
    m = np.zeros(DM.shape, bool)
    r, c = idx(Y, Z)
    m[r, c] = True
    return ndimage.binary_closing(ndimage.binary_dilation(m, np.ones((3, 3))),
                                  np.ones((7, 7)))


def rim_fit(mask, ring=11, dmax=0.30, label=""):
    """Quadratic depth surface fitted to real bodywork on a ring around `mask`.

    dmax rejects ring cells whose ray missed the fascia entirely -- without
    it the lower-intake ring pulled samples from 600-900 mm behind the car
    and the fit ranged 119..917 mm (v1's protruding intake bar).
    """
    ringm = ndimage.binary_dilation(mask, np.ones((ring, ring))) & ~mask
    r, c = np.nonzero(ringm & SIL & (DM < dmax))
    y, z, dep = ys[r], zs[c], DM[r, c]
    if len(y) < 80:
        raise SystemExit(f"rim_fit({label}): only {len(y)} usable ring cells")
    A = np.stack([np.ones_like(y), z, y, z * z, y * y, y * z], 1)
    w = np.ones(len(y))
    for _ in range(4):
        coef, *_ = np.linalg.lstsq(A * w[:, None], dep * w, rcond=None)
        res = np.abs(A @ coef - dep)
        s = max(np.median(res), 1e-4)
        w = 1.0 / (1.0 + (res / (2.5 * s)) ** 2)
    rms = float(np.sqrt((w * (A @ coef - dep) ** 2).sum() / w.sum()))
    print(f"  rim_fit({label}): {len(y)} cells, robust rms {rms*1000:.1f}mm")
    REPORT["checks"][f"rim_{label}"] = {"cells": int(len(y)), "rms_mm": rms * 1000}
    return lambda Y, Z: (coef[0] + coef[1] * Z + coef[2] * Y + coef[3] * Z * Z
                         + coef[4] * Y * Y + coef[5] * Y * Z)


ERO = {}
_VAL = SIL & (DM < 0.60)


def skin_mean(Y, Z, rad=0.012):
    """Local MEAN depth of real fascia bodywork (cells that actually hit).

    Used to anchor a component's flange to the body instead of to a global
    quadratic.  The band quadratic fitted rms 16.8 mm overall but topped out
    at 423 mm where the -z corner really sits at 489-565 mm, so the mirrored
    lens floated ~100 mm proud there -- v2's residual protruding wedge.
    """
    k = int(round(rad / RES))
    key = ("m", k)
    if key not in ERO:
        num = ndimage.uniform_filter(np.where(_VAL, DM, 0.0), size=2 * k + 1)
        den = ndimage.uniform_filter(_VAL.astype(float), size=2 * k + 1)
        ERO[key] = np.where(den > 0.06, num / np.maximum(den, 1e-9), np.nan)
    r, c = idx(Y, Z)
    return ERO[key][r, c].reshape(np.asarray(Y).shape)


def shell_min(Y, Z, rad=0.008):
    k = int(round(rad / RES))
    if k not in ERO:
        ERO[k] = ndimage.grey_erosion(SHELL, size=(2 * k + 1, 2 * k + 1))
    r, c = idx(Y, Z)
    return ERO[k][r, c].reshape(np.asarray(Y).shape)


def grid_solid(Y, Z, Dfront, Dback, name):
    Y = np.asarray(Y); Z = np.asarray(Z)
    ny, nz = Y.shape
    n = ny * nz
    Df = np.broadcast_to(np.asarray(Dfront), (ny, nz)).ravel()
    Db = np.broadcast_to(np.asarray(Dback), (ny, nz)).ravel()
    V = np.vstack([np.stack([XMIN + Df, Y.ravel(), Z.ravel()], 1),
                   np.stack([XMIN + Db, Y.ravel(), Z.ravel()], 1)])
    F = []
    for j in range(ny - 1):
        for i in range(nz - 1):
            a = j * nz + i; b = a + 1; c = a + nz; e = c + 1
            F += [[a, c, e], [a, e, b], [a + n, e + n, c + n], [a + n, b + n, e + n]]
    edge = ([j * nz for j in range(ny)] +
            [(ny - 1) * nz + i for i in range(1, nz)] +
            [j * nz + (nz - 1) for j in range(ny - 2, -1, -1)] +
            [i for i in range(nz - 2, 0, -1)])
    for k in range(len(edge)):
        a, b = edge[k], edge[(k + 1) % len(edge)]
        F += [[a, b, b + n], [a, b + n, a + n]]
    m = trimesh.Trimesh(vertices=V, faces=np.array(F), process=True)
    m.fix_normals()
    return m


PARTS = []


def add(name, mesh, col, rough, metal=0.0):
    PARTS.append((name, mesh, col, rough, metal))
    ext = mesh.vertices.max(0) - mesh.vertices.min(0)
    print(f"  + {name:18s} {len(mesh.faces):6d}f  wt={mesh.is_watertight}  "
          f"{ext[0]*1000:.0f}x{ext[1]*1000:.0f}x{ext[2]*1000:.0f}mm")
    REPORT["parts"].append({"name": name, "faces": int(len(mesh.faces)),
                            "watertight": bool(mesh.is_watertight),
                            "extent_mm": [round(float(v) * 1000, 1) for v in ext]})


def funnel(ny, nz, ramp_cells):
    """0 on the flange band, 1 in the aperture interior; smoothstepped."""
    j = np.minimum(np.arange(ny)[:, None], (ny - 1) - np.arange(ny)[:, None])
    i = np.minimum(np.arange(nz)[None, :], (nz - 1) - np.arange(nz)[None, :])
    t = np.clip(np.minimum(j, i) / max(ramp_cells, 1), 0, 1)
    return t * t * (3 - 2 * t)


# ================================================================== CUT PASS
sc = trimesh.load(CAR, force="scene")
CUTS = []                       # (label, ymin, ymax, zmin, zmax, d0, d1)
LAMPCUT = {}
_Yl, _Zl = lamp_grid(+1, dy=-0.013, dz=-0.015)
_zc = _Zl[:, 0]
_ylo, _yhi = _Yl.min(1), _Yl.max(1)


def lamp_cut_mask(c, side):
    """Faces inside the shrunk lamp OUTLINE (per-column y band), not its bbox."""
    az = np.abs(c[:, 2])
    ok = (az >= _zc.min()) & (az <= _zc.max())
    ok &= (c[:, 2] > 0) if side > 0 else (c[:, 2] < 0)
    lo = np.interp(az, _zc, _ylo)
    hi = np.interp(az, _zc, _yhi)
    return ok & (c[:, 1] > lo) & (c[:, 1] < hi)
CUTS.append(("grille", GR_Y0 + FLANGE, GR_Y1 - FLANGE,
             -(GR_Z - FLANGE), GR_Z - FLANGE, 0.02, 0.42))
CUTS.append(("intake", IN_Y0 + FLANGE, IN_Y1 - FLANGE,
             -(IN_Z - FLANGE), IN_Z - FLANGE, 0.02, 0.30))
CUTS.append(("plate", PL_Y0 + FLANGE, PL_Y1 - FLANGE,
             -(PL_Z - FLANGE), PL_Z - FLANGE, 0.02, 0.155))

total_cut = 0
for lab, y0, y1, z0, z1, d0, d1 in CUTS + [("lampR", 0, 0, 0, 0, 0.02, 0.46),
                                           ("lampL", 0, 0, 0, 0, 0.02, 0.46)]:
    n = 0
    for gname, g in sc.geometry.items():
        c = g.triangles_center
        if lab.startswith("lamp"):
            kill = lamp_cut_mask(c, +1 if lab.endswith("R") else -1)
        else:
            kill = ((c[:, 1] > y0) & (c[:, 1] < y1) &
                    (c[:, 2] > z0) & (c[:, 2] < z1))
        kill = kill & (c[:, 0] > XMIN + d0) & (c[:, 0] < XMIN + d1)
        if kill.any():
            g.update_faces(~kill)
            n += int(kill.sum())
            REPORT["cuts"].setdefault(lab, {})[gname] = int(kill.sum())
    total_cut += n
    print(f"CUT {lab:7s} y {y0:.3f}..{y1:.3f} z {z0:+.3f}..{z1:+.3f} "
          f"d {d0:.2f}..{d1:.2f} -> {n} faces")
REPORT["cut_total"] = total_cut
print(f"CUT TOTAL {total_cut} faces")

# ================================================================ RIM FITS
bandmask = mask_of(*lamp_grid(+1)) | mask_of(*lamp_grid(-1)) | \
    mask_of(*rect_grid(GR_Y0, GR_Y1, -GR_Z, GR_Z, 10, 40))
rim_band = rim_fit(bandmask, ring=13, dmax=0.32, label="band")
rim_in = rim_fit(mask_of(*rect_grid(IN_Y0, IN_Y1, -IN_Z, IN_Z, 9, 46)),
                 ring=13, dmax=0.30, label="intake")
rim_pl = rim_fit(mask_of(*rect_grid(PL_Y0, PL_Y1, -PL_Z, PL_Z, 10, 30)),
                 ring=9, dmax=0.26, label="plate")

# =============================================================== HEADLAMPS
LENS_T, HOUS_T = 0.014, 0.080
for sd, tag in ((+1, "R"), (-1, "L")):
    Y, Z = lamp_grid(sd)
    yc = LAMP_YC0 + (LAMP_YC1 - LAMP_YC0) * np.linspace(0, 1, NU)
    hh = LAMP_HH0 + (LAMP_HH1 - LAMP_HH0) * np.linspace(0, 1, NU) ** 0.7
    zc = Z[:, 0]
    # ANCHOR PER COLUMN to the real bodywork just above and just below the
    # lamp.  Above is the wing/bonnet edge, below is the bumper top; both are
    # genuine surfaces, and their local plane is the surface a lamp sits in.
    yb, ya = yc - hh - 0.024, yc + hh + 0.024
    db = skin_mean(yb, zc, 0.014)
    da = skin_mean(ya, zc, 0.014)
    fb = rim_band(yb, zc)
    fa = rim_band(ya, zc)
    nb, na = np.isnan(db), np.isnan(da)
    db = np.where(nb, fb, db)
    da = np.where(na, fa, da)
    print(f"lamp {tag}: anchors fell back to the fit on "
          f"{int(nb.sum())} lower / {int(na.sum())} upper columns of {NU}")
    db = ndimage.gaussian_filter1d(db, 1.6, mode="nearest")
    da = ndimage.gaussian_filter1d(da, 1.6, mode="nearest")
    mid = 0.5 * (ya + yb)
    tilt = (da - db) / np.maximum(ya - yb, 1e-6)
    Dl = (0.5 * (da + db))[:, None] + tilt[:, None] * (Y - mid[:, None]) - 0.005
    Dl = ndimage.gaussian_filter(Dl, 0.7, mode="nearest")
    print(f"lamp {tag}: skin anchors {db.min()*1000:.0f}..{da.max()*1000:.0f}mm  "
          f"lens {Dl.min()*1000:.0f}..{Dl.max()*1000:.0f}mm  "
          f"outer col {Dl[-1].mean()*1000:.0f}mm")
    REPORT["checks"][f"lens_{tag}_depth_mm"] = [float(Dl.min() * 1000),
                                                float(Dl.max() * 1000)]
    REPORT["checks"][f"lens_{tag}_outer_mm"] = float(Dl[-1].mean() * 1000)
    add(f"Head_Lens_{tag}", grid_solid(Y, Z, Dl, Dl + LENS_T, "l"),
        [24, 25, 28], 0.05)
    ycm = Y.mean(1)[:, None]
    add(f"Head_Housing_{tag}",
        grid_solid(ycm + (Y - ycm) * 0.92, Z * 0.995, Dl + LENS_T,
                   Dl + LENS_T + HOUS_T, "h"), [16, 16, 18], 0.55)
    add(f"Head_Inner_{tag}",
        grid_solid(ycm + (Y - ycm) * 0.60, Z * 0.97, Dl + LENS_T + 0.032,
                   Dl + LENS_T + 0.044, "i"), [198, 201, 208], 0.18, 0.85)
    # DRL bar: the per-car audit rubric fails "headlights lacking sharp
    # internal LED elements", and an opaque lens with nothing in it reads as a
    # black slab.  Built as OPAQUE geometry rather than by making the lens
    # transparent, which would add a BLEND material for the glazing gates to
    # trip over for no benefit.
    hhc = 0.5 * (Y.max(1) - Y.min(1))
    Yd = (Y.mean(1)[:, None] +
          hhc[:, None] * np.linspace(-0.62, -0.20, 3)[None, :])
    Dd = (0.5 * (da + db))[:, None] + tilt[:, None] * (Yd - mid[:, None]) - 0.011
    add(f"Head_DRL_{tag}", grid_solid(Yd, np.repeat(zc[:, None], 3, 1),
                                      Dd, Dd + 0.009, "d"),
        [236, 240, 246], 0.16, 0.30)

# =================================================================== GRILLE
NYg, NZg = 14, 52
Yg, Zg = rect_grid(GR_Y0, GR_Y1, -GR_Z, GR_Z, NYg, NZg)
Dr = rim_band(Yg, Zg)
env = shell_min(Yg, Zg, 0.008) - 0.004
t = funnel(NYg, NZg, 2)
Dlip = np.minimum(Dr - 0.002, env)
Dfloor = Dlip + 0.042
Df = Dlip + (Dfloor - Dlip) * t
print(f"grille: lip {Dlip.min()*1000:.0f}..{Dlip.max()*1000:.0f}mm  "
      f"floor {Dfloor.min()*1000:.0f}..{Dfloor.max()*1000:.0f}mm  "
      f"depth {(Dfloor-Dlip).mean()*1000:.0f}mm")
REPORT["checks"]["grille_depth_mm"] = float((Dfloor - Dlip).mean() * 1000)
add("Grille_Well", grid_solid(Yg, Zg, Df, Df + 0.012, "g"), [12, 12, 13], 0.80)
for k, yy in enumerate(np.linspace(GR_Y0 + 0.024, GR_Y1 - 0.024, 3)):
    Ys, Zs = rect_grid(yy - 0.007, yy + 0.007, -GR_Z + 0.020, GR_Z - 0.020, 4, NZg)
    Ds = rim_band(Ys, Zs) + 0.012
    add(f"Grille_Slat_{k}", grid_solid(Ys, Zs, Ds, Ds + 0.010, "s"),
        [20, 20, 22], 0.28)

# ==================================================================== BADGE
BR, BY = 0.050, 0.795
th = np.linspace(0, 2 * np.pi, 44, endpoint=False)
rr = np.linspace(0.12, 1.0, 6)
Yb = BY + np.outer(rr, np.cos(th)) * BR
Zb = np.outer(rr, np.sin(th)) * BR
Db = rim_band(np.full_like(Yb, BY), Zb) - 0.010
add("Front_Badge", grid_solid(Yb, Zb, Db, Db + 0.030, "b"),
    [206, 209, 215], 0.12, 0.90)

# ============================================================= LOWER INTAKE
NYi, NZi = 12, 60
Yi, Zi = rect_grid(IN_Y0, IN_Y1, -IN_Z, IN_Z, NYi, NZi)
Dr = rim_in(Yi, Zi)
env = shell_min(Yi, Zi, 0.008) - 0.004
t = funnel(NYi, NZi, 2)
Dlip = np.clip(np.minimum(Dr - 0.002, env), 0.030, 0.190)
Dfloor = Dlip + 0.050
Df = Dlip + (Dfloor - Dlip) * t
print(f"intake: lip {Dlip.min()*1000:.0f}..{Dlip.max()*1000:.0f}mm  "
      f"depth {(Dfloor-Dlip).mean()*1000:.0f}mm")
REPORT["checks"]["intake_depth_mm"] = float((Dfloor - Dlip).mean() * 1000)
add("Intake_Well", grid_solid(Yi, Zi, Df, Df + 0.012, "iw"), [10, 10, 11], 0.85)
for k, yy in enumerate(np.linspace(IN_Y0 + 0.022, IN_Y1 - 0.022, 2)):
    Ys, Zs = rect_grid(yy - 0.007, yy + 0.007, -IN_Z + 0.026, IN_Z - 0.026, 4, NZi)
    Ds = rim_in(Ys, Zs) + 0.016
    add(f"Intake_Slat_{k}", grid_solid(Ys, Zs, Ds, Ds + 0.011, "is"),
        [18, 18, 20], 0.32)

# ============================================================= PLATE RECESS
NYp, NZp = 12, 34
Yp, Zp = rect_grid(PL_Y0, PL_Y1, -PL_Z, PL_Z, NYp, NZp)
Dr = rim_pl(Yp, Zp)
env = shell_min(Yp, Zp, 0.008) - 0.004
t = funnel(NYp, NZp, 2)
Dlip = np.minimum(Dr - 0.002, env)
Dfloor = Dlip + 0.022
Df = Dlip + (Dfloor - Dlip) * t
print(f"plate: lip {Dlip.min()*1000:.0f}..{Dlip.max()*1000:.0f}mm  "
      f"recess {(Dfloor-Dlip).mean()*1000:.0f}mm")
REPORT["checks"]["plate_recess_mm"] = float((Dfloor - Dlip).mean() * 1000)
add("Plate_Recess", grid_solid(Yp, Zp, Df, Df + 0.012, "p"), [22, 22, 24], 0.60)
Ypl, Zpl = rect_grid(PL_Y0 + 0.028, PL_Y1 - 0.028, -PL_Z + 0.030, PL_Z - 0.030,
                     8, 26)
# v2 evaluated the plate face from its own rim fit and the recess FLOOR poked
# through it (visible in the v2 matID as a tan wedge across the white plate).
# Derive it from the same floor field instead, so it is behind the lip and in
# front of the floor by construction.
_fl = np.clip(np.minimum(rim_pl(Ypl, Zpl) - 0.002,
                         shell_min(Ypl, Zpl, 0.008) - 0.004), 0.010, 0.170)
Dpl = _fl + 0.010
add("Front_Plate", grid_solid(Ypl, Zpl, Dpl - 0.003, Dpl + 0.004, "pl"),
    [233, 233, 226], 0.42)

# =================================================================== ASSEMBLE
out = trimesh.Scene()
for node in sc.graph.nodes_geometry:
    T, gn = sc.graph[node]
    if gn not in out.geometry:
        out.add_geometry(sc.geometry[gn], geom_name=gn, node_name=node, transform=T)
    else:
        out.graph.update(frame_to=node, matrix=T, geometry=gn)
for name, m, col, rough, metal in PARTS:
    mat = PBRMaterial(name=name, baseColorFactor=list(col) + [255],
                      metallicFactor=metal, roughnessFactor=rough,
                      doubleSided=False)
    m.visual = trimesh.visual.TextureVisuals(material=mat)
    out.add_geometry(m, node_name=name, geom_name=name)
out.export(OUT)
json.dump(REPORT, open(REP, "w"), indent=1)
print(f"FRONT_BUILD_DONE {OUT} ({os.path.getsize(OUT)} bytes) "
      f"{len(PARTS)} parts, {sum(len(m.faces) for _,m,_,_,_ in PARTS)} faces, "
      f"{sum(m.is_watertight for _,m,_,_,_ in PARTS)}/{len(PARTS)} watertight")
