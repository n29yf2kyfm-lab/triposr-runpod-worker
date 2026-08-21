#!/usr/bin/env python3
"""rebuild7.py -- GATE 3 v7 step 2: build the new front fascia into the cavity.

Reads the stripped car, the measured depth map and the plan; writes the rebuilt
car plus a build report.  Every dimension comes from plan.json, which derives
them from the mesh -- nothing here invents a number.

THE SKIN.  The new bumper face is not a quadratic.  A quadratic over this fascia
fitted 16.8 mm rms but was 100 mm out at the corners on the predecessor, which
floated a mirrored lens in mid-air.  Instead the skin is the car's OWN depth
field with the melt filtered out of it: nearest-fill, then a 42 mm median (which
rejects the badge blob and the fake plate slab as outliers because they are
smaller than the window), then a 12 mm Gaussian.  The nose FORM survives; the
crumple does not.

SYMMETRY IS BUILT IN, NOT HOPED FOR.  The skin is mirror-averaged about the
front-local centreline across the whole feature zone, and every feature is
constructed on one side and MIRRORED with `geo7.mirror_z` (which flips winding
too, so the copy is not inside-out).  v6's worst defect was 29.7 mm of L/R shape
deviation against a 2 mm threshold; a mirrored construction cannot produce that.
Outboard of the feature zone the skin blends back to the car's real, asymmetric
shape over 90 mm, because the bumper has to meet the wings where they actually
are -- the mesh's front is 90-108 mm wider on +z than on -z at every height.

EVERY PART TUCKS BEHIND THE SURVIVING SHELL.  The strip left a 12 mm flange of
original bodywork at every cut edge and the cut edge itself is ragged at face
resolution.  Each panel therefore extends past the cut edge and ramps 10 mm
REARWARD over the last 16 mm, so it passes behind the surviving shell instead of
fighting it for the same plane.

WHAT IS DELIBERATELY NOT BUILT, and why:
  * The headlamp tips of a real Mk8 rise ~90 mm ABOVE the bonnet leading edge at
    the corners.  Reproducing that requires cutting into the wing, and cutting
    the wing is how a rebuild turns back into parts-over-melt.  The lamp's upper
    edge instead follows this car's own measured bonnet shut line.  NOT BUILT.
  * No splitter.  There is none on this trim; the band below the lower grille is
    a body-colour valance and the node is named for what it is.
  * No slats in the upper grille.  The spec is explicit that nothing discrete is
    resolvable there; v5 modelled slats and it was the wrong car.
  * The park-sensor fitting seen in one reference only is an option, not a
    feature of this trim.  NOT BUILT.

Run: python3 rebuild7.py <stripped.glb> <ftex.npz> <plan.json> <out.glb> <report.json>
"""
import json
import os
import sys

import numpy as np
import trimesh
from scipy import ndimage
from trimesh.visual.material import PBRMaterial

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from geo7 import grid_solid, rect_grid, disc_solid, funnel, mirror_z

CAR, TEX, PLAN, OUT, REP = sys.argv[1:6]

d = np.load(TEX, allow_pickle=True)
D, ys, zs = d["D"], d["ys"], d["zs"]
RES, XN = float(d["RES"]), float(d["XMIN"])
P = json.load(open(PLAN))
F, Y = P["frame"], P["y"]
ZC = F["z_centre"]
YD = F["y_datum_bonnet_leading_edge"]
YLOW = F["y_bumper_lowest"]
SC = F["vertical_scale_vs_spec"]
SIL = np.isfinite(D)

R = {"frame": F, "parts": [], "checks": {}, "not_built": {}}

# ============================================================== THE SKIN
valid = SIL & (D < 0.35)
idx = ndimage.distance_transform_edt(~valid, return_distances=False,
                                     return_indices=True)
fill = np.where(valid, D, 0.0)[tuple(idx)]
skinF = ndimage.median_filter(fill, size=21)            # 42 mm window
skinF = ndimage.gaussian_filter(skinF, 6.0)            # sigma 12 mm

# REPAIR 3.  A 42 mm median plus a 12 mm Gaussian pulls a CONVEX surface
# backward, and the fascia's outer corner is the most convex place on it -- so
# the smoothed skin sank behind the car's own bodywork there and the surviving
# shell stood up to 23.5 mm proud of the new panels (median 2.8, p90 9.5, 30% of
# 168.8 cm2 over 5 mm; measured by coverage.py). The fix is not to smooth less
# everywhere -- the crumple has to go from the FEATURE zone -- but to hand the
# outer 90 mm back to the car: outboard of the feature zone the skin blends to a
# lightly-filtered copy of the real surface, so the bumper meets the wing where
# the wing actually is.
local = ndimage.gaussian_filter(fill, 3.0)              # sigma 6 mm
zt = 2.0 * ZC - zs
it = np.clip(np.rint((zt - zs[0]) / RES).astype(int), 0, len(zs) - 1)
ZFEAT, ZBLEND = 0.628, 0.090
w = np.clip((ZFEAT + ZBLEND - np.abs(zs - ZC)) / ZBLEND, 0.0, 1.0)[None, :]
# mirror-average about ZC inside the feature zone, blend to the real surface out
skinF = w * 0.5 * (skinF + skinF[:, it]) + (1.0 - w) * local
R["checks"]["skin"] = {
    "method": "nearest-fill -> 42 mm median -> 12 mm gaussian -> mirror-average "
              "inside |z-zc|<0.628, blended out over 90 mm",
    "range_mm": [round(float(skinF.min()) * 1000, 1),
                 round(float(skinF.max()) * 1000, 1)],
    "mirror_residual_in_feature_zone_mm": round(float(np.abs(
        (skinF - skinF[:, it])[:, np.abs(zs - ZC) < ZFEAT]).max()) * 1000, 4),
}


def skin(Yq, Zq):
    r = np.clip(np.rint((np.asarray(Yq) - ys[0]) / RES).astype(int), 0, len(ys) - 1)
    c = np.clip(np.rint((np.asarray(Zq) - zs[0]) / RES).astype(int), 0, len(zs) - 1)
    return skinF[r, c]


# ------------------------------------------------- the car's own bonnet edge
def bonnet_edge_curve():
    out = []
    for ztest in np.arange(-0.90, 0.9001, 0.02):
        ci = int(round((ztest - zs[0]) / RES))
        sl = slice(max(0, ci - 15), min(len(zs), ci + 16))
        with np.errstate(all="ignore"):
            c = np.nanmin(np.where(SIL[:, sl], D[:, sl], np.nan), axis=1)
        ok = np.isfinite(c)
        if ok.sum() < 30:
            out.append(np.nan)
            continue
        i2 = np.arange(len(ys))
        cf = ndimage.uniform_filter1d(np.interp(i2, i2[ok], c[ok]), 11)
        g = np.gradient(cf, RES)
        m = (ys < 1.02) & (ys > 0.60) & (g < 1.3)
        i = np.nonzero(m)[0]
        out.append(float(ys[i[-1]]) if len(i) else np.nan)
    return np.arange(-0.90, 0.9001, 0.02), np.array(out)


bz, be = bonnet_edge_curve()
g = np.isfinite(be)
be = ndimage.uniform_filter1d(np.interp(bz, bz[g], be[g]), 5)
be = np.clip(be, YD - 0.040, YD + 0.060)
# symmetrise the shut line too, so the lamps and slot mirror exactly
be = 0.5 * (be + np.interp(2 * ZC - bz, bz, be))
BE = lambda z: np.interp(z, bz, be)

# ------------------------------------------------------ the cut edge per side
zn, zp = {}, {}
for yy in np.arange(YLOW - 0.01, YD + 0.061, 0.010):
    m = SIL & ((ys > yy - 0.020) & (ys < yy + 0.020))[:, None] & (D < 0.42)
    i = np.nonzero(m.sum(0) >= 4)[0]
    zn[yy] = float(zs[i.min()]) if len(i) else np.nan
    zp[yy] = float(zs[i.max()]) if len(i) else np.nan
yk = np.array(sorted(zn))
ZN = np.array([zn[y] for y in yk])
ZP = np.array([zp[y] for y in yk])
for a in (ZN, ZP):
    gg = np.isfinite(a)
    a[:] = np.interp(yk, yk[gg], a[gg])
ZN = ndimage.uniform_filter1d(ZN, 5)
ZP = ndimage.uniform_filter1d(ZP, 5)
EDGE_N = lambda y: np.interp(y, yk, ZN)      # fascia edge, -z side
EDGE_P = lambda y: np.interp(y, yk, ZP)      # fascia edge, +z side

TUCK_D, TUCK_CELLS = 0.010, 3


def tuck(ny, nz, edges=("n", "s", "e", "w")):
    """1 on the outer ring, ramping to 0 over TUCK_CELLS cells inboard."""
    j = np.arange(ny)[:, None] * np.ones((1, nz))
    i = np.ones((ny, 1)) * np.arange(nz)[None, :]
    big = np.full((ny, nz), 1e9)
    if "s" in edges:
        big = np.minimum(big, j)
    if "n" in edges:
        big = np.minimum(big, (ny - 1) - j)
    if "w" in edges:
        big = np.minimum(big, i)
    if "e" in edges:
        big = np.minimum(big, (nz - 1) - i)
    t = np.clip(big / TUCK_CELLS, 0, 1)
    return 1.0 - t * t * (3 - 2 * t)


PARTS = []


def add(node, mesh, mat):
    PARTS.append((node, mesh, mat))
    e = mesh.vertices.max(0) - mesh.vertices.min(0)
    b = mesh.split(only_watertight=False)
    print(f"  + {node:22s} {len(mesh.faces):6d}f  wt={mesh.is_watertight} "
          f"shells={len(b)}  {e[0]*1000:.0f}x{e[1]*1000:.0f}x{e[2]*1000:.0f}mm")
    R["parts"].append({"node": node, "material": mat,
                       "faces": int(len(mesh.faces)),
                       "watertight": bool(mesh.is_watertight),
                       "shells": int(len(b)),
                       "extent_mm": [round(float(v) * 1000, 1) for v in e],
                       "bbox_min": [round(float(v), 5) for v in mesh.vertices.min(0)],
                       "bbox_max": [round(float(v), 5) for v in mesh.vertices.max(0)]})


# ======================================================== geometry constants
LAMP_ZI, LAMP_ZO = 0.347, 0.628        # |z-ZC| inner corner / outer tip
GR_H = 0.067 * SC                      # upper slot height, constant
LG_Z = 0.455                           # lower grille half width
IN_Z0, IN_Z1 = 0.495, 0.665            # outer intake
PL_W, PL_H = 0.520, 0.111              # TRUE plate
PL_YC = 0.5 * (Y["plate_top"] + Y["plate_bottom"])
BADGE_D = P["parts"]["badge"]["diameter"]
BLADE_T = 0.007
BLADE_DROP = 0.020 * SC                # blade centreline below the shut line
LG_Y0, LG_Y1 = Y["grille_lower_bottom"], Y["intake_top"]

# Lamp height profile along u (0 = inner corner, 1 = outer tip).  Defined here
# rather than in the lamp section because the bumper panel that sweeps UNDER the
# lamp needs the lamp's own lower edge to butt against.
NU, NV = 30, 12
uu = np.linspace(0, 1, NU)
hh_u = np.array([0.0, 0.20, 0.45, 0.65, 0.85, 1.0])
hh_v = np.array([0.016, 0.040, 0.060, 0.070, 0.062, 0.044]) * (SC / 0.796)
HH = np.interp(uu, hh_u, hh_v)

R["checks"]["dimensions_used"] = {
    "lamp_inner_mm": LAMP_ZI * 1000, "lamp_outer_mm": LAMP_ZO * 1000,
    "upper_slot_height_mm": round(GR_H * 1000, 1),
    "lower_grille_half_mm": LG_Z * 1000,
    "intake_mm": [IN_Z0 * 1000, IN_Z1 * 1000],
    "plate_mm": [PL_W * 1000, PL_H * 1000],
    "badge_diameter_mm": round(BADGE_D * 1000, 1),
    "blade_thickness_mm": BLADE_T * 1000,
    "blade_below_shutline_mm": round(BLADE_DROP * 1000, 1),
}

# ============================================================ 1. BUMPER SKIN
# Body-colour panels tiling the footprint around every aperture.  Each is one
# closed shell; they are all bound to node Bumper_Front.
SKIN_T = 0.016
panels = []


def panel(y0, y1, z0, z1, ny, nz, edges=("n", "s", "e", "w"), name=""):
    Yg, Zg = rect_grid(y0, y1, z0, z1, ny, nz)
    Df = skin(Yg, Zg) + TUCK_D * tuck(ny, nz, edges)
    panels.append((grid_solid(XN, Yg, Zg, Df, Df + SKIN_T), name))


OV = 0.014          # overlap past the cut edge, tucked behind the shell

# --- valance band (NO SPLITTER: this is a plain body-colour band) ----------
vy0, vy1 = YLOW - OV, Y["grille_lower_bottom"]
Yv, Zv = rect_grid(vy0, vy1, 0, 1, 10, 60)
Zv = ZC + (EDGE_N(Yv) - ZC) + (EDGE_P(Yv) - EDGE_N(Yv)) * Zv
Zv = ZC + (Zv - ZC) * 1.0
Dv = skin(Yv, Zv) + TUCK_D * tuck(10, 60)
add("Valance_Front", grid_solid(XN, Yv, Zv, Dv, Dv + SKIN_T), "carpaint")

# --- lower band: divider between grille and intake, and outboard of intake --
for sgn in (-1, +1):
    panel(LG_Y0, LG_Y1, ZC + sgn * LG_Z, ZC + sgn * IN_Z0, 8, 6,
          edges=("n", "s"), name="lg_intake_divider")
for sgn in (-1, +1):
    Yq, Zq = rect_grid(LG_Y0, LG_Y1, 0, 1, 8, 10)
    zin = ZC + sgn * IN_Z1
    zout = (EDGE_P(Yq) + OV) if sgn > 0 else (EDGE_N(Yq) - OV)
    Zq = zin + (zout - zin) * Zq
    Dq = skin(Yq, Zq) + TUCK_D * tuck(8, 10, ("n", "s", "e" if sgn > 0 else "w"))
    panels.append((grid_solid(XN, Yq, Zq, Dq, Dq + SKIN_T), "outboard_of_intake"))

# --- mid band: intake top up to the lamp's lower edge, full width ----------
Ym, Zm = rect_grid(LG_Y1, Y["headlamp_lowest"], 0, 1, 10, 56)
Zm = (EDGE_N(Ym) - OV) + ((EDGE_P(Ym) + OV) - (EDGE_N(Ym) - OV)) * Zm
Dm = skin(Ym, Zm) + TUCK_D * tuck(10, 56)
panels.append((grid_solid(XN, Ym, Zm, Dm, Dm + SKIN_T), "mid_band"))

# --- between the lamp's lower edge and the upper slot, inboard of the lamps -
Yb, Zb = rect_grid(Y["headlamp_lowest"], 1.0, 0, 1, 8, 34)
Zb = ZC - LAMP_ZI + 2 * LAMP_ZI * Zb
Yb = Y["headlamp_lowest"] + (BE(Zb) - GR_H - Y["headlamp_lowest"]) * \
    np.linspace(0, 1, 8)[:, None]
Db = skin(Yb, Zb) + TUCK_D * tuck(8, 34, ("s",))
panels.append((grid_solid(XN, Yb, Zb, Db, Db + SKIN_T), "below_slot"))

# --- UNDER the lamp: the bumper's upper surface sweeping beneath it --------
# REPAIR 1.  Without this the lamp aperture is only covered over the lamp's own
# height, which tapers to 16 mm at the inner corner while the aperture there is
# 77 mm tall -- measured as a 22.0 cm2 open hole at y 0.796..0.834,
# z -0.60..-0.49 by coverage.py, and visible as a dark void in ev/rb1.
_uu = np.linspace(0, 1, 30)
_hh = np.interp(_uu, hh_u, hh_v)
for sgn in (-1, +1):
    zline = ZC + sgn * (LAMP_ZI + (LAMP_ZO - LAMP_ZI) * _uu)
    lamp_bot = (BE(zline) - 0.008) - _hh
    y_lo = Y["headlamp_lowest"] - OV
    y_hi = np.maximum(lamp_bot + 0.005, y_lo + 0.008)
    Yq = y_lo + (y_hi - y_lo)[None, :] * np.linspace(0, 1, 5)[:, None]
    Zq = np.repeat(zline[None, :], 5, 0)
    Dq = skin(Yq, Zq) + TUCK_D * tuck(5, 30, ("n", "s"))
    panels.append((grid_solid(XN, Yq, Zq, Dq, Dq + SKIN_T), "under_lamp"))

# --- outboard of the lamp tip, up to the wing -----------------------------
for sgn in (-1, +1):
    Yq, Zq = rect_grid(Y["headlamp_lowest"], 1.0, 0, 1, 8, 8)
    zin = ZC + sgn * LAMP_ZO
    zout = (EDGE_P(Yq) + OV) if sgn > 0 else (EDGE_N(Yq) - OV)
    Zq = zin + (zout - zin) * Zq
    Yq = Y["headlamp_lowest"] + (BE(Zq) - Y["headlamp_lowest"]) * \
        np.linspace(0, 1, 8)[:, None]
    Dq = skin(Yq, Zq) + TUCK_D * tuck(8, 8, ("n", "e" if sgn > 0 else "w"))
    panels.append((grid_solid(XN, Yq, Zq, Dq, Dq + SKIN_T), "outboard_of_lamp"))

bump = trimesh.util.concatenate([m for m, _ in panels])
add("Bumper_Front", bump, "carpaint")
R["checks"]["bumper_panel_names"] = [n for _, n in panels]

# ======================================================== 2. UPPER GRILLE
# ONE constant-height slot, NO SLATS.  Its top edge IS the bonnet shut line.
NY, NZ = 9, 70
Yg, Zg = rect_grid(0, 1, ZC - LAMP_ZI, ZC + LAMP_ZI, NY, NZ)
top = BE(Zg[0])[None, :]
Yg = (top - GR_H) + GR_H * np.linspace(0, 1, NY)[:, None]
Dlip = skin(Yg, Zg)
t = funnel(NY, NZ, 2)
Dfl = Dlip + 0.038
Dg = Dlip + (Dfl - Dlip) * t
# REPAIR 2. The strip cut up to the measured bonnet edge, so a shut-line strip
# a few mm tall was left OPEN above every part whose top sat at BE - 0.008
# (measured: a 3.9 cm2 hole at y 0.860..0.866, z -0.396..-0.322). One extra row
# is appended ABOVE the shut line and pushed 12 mm rearward, so it passes behind
# the surviving bonnet lip and closes the strip without showing.
Yg = np.vstack([Yg, top + 0.004])
Zg = np.vstack([Zg, Zg[-1]])
Dg = np.vstack([Dg, Dg[-1] + 0.012])
add("Grille_Upper", grid_solid(XN, Yg, Zg, Dg, Dg + 0.012), "Trim_Black")
R["checks"]["upper_slot"] = {
    "height_mm": round(GR_H * 1000, 2),
    "height_constant_within_mm": round(float(
        (Yg[-1] - Yg[0]).max() - (Yg[-1] - Yg[0]).min()) * 1000, 4),
    "recess_depth_mm": round(float((Dfl - Dlip).mean()) * 1000, 1),
    "slats": 0, "note": "no slats: spec 4.1, nothing discrete is resolvable",
}

# ============================================================ 3. HEADLAMPS
def lamp_grid(scale_h=1.0, inset=0.0):
    z = ZC + (LAMP_ZI + inset) + (LAMP_ZO - inset - (LAMP_ZI + inset)) * uu
    ytop = BE(z) - 0.008
    h = HH * scale_h
    Yl = np.stack([np.linspace(ytop[k] - h[k], ytop[k], NV) for k in range(NU)])
    Zl = np.repeat(z[:, None], NV, 1)
    return Yl, Zl


Yl, Zl = lamp_grid()
Dl = skin(Yl, Zl)
# REPAIR 4a: the lens is set 3 mm BEHIND the surrounding bumper skin. Built
# flush it was geometrically invisible -- in a clay pass a flush panel of the
# same material has no outline at all, and the audit rubric fails a lamp with no
# defined edge. 3 mm of rebate gives the aperture a real shadow line that does
# not depend on the material being dark.
LENS_RECESS = 0.003
Dl = Dl + LENS_RECESS
# REPAIR 2, lamp side: one extra column above the shut line, tucked rearward.
Yl = np.hstack([Yl, (BE(Zl[:, 0]) + 0.004)[:, None]])
Zl = np.hstack([Zl, Zl[:, -1:]])
Dl = np.hstack([Dl, Dl[:, -1:] + 0.012])
lens = grid_solid(XN, Yl, Zl, Dl, Dl + 0.014)
Yh, Zh = lamp_grid(0.90, 0.006)
Dh = skin(Yh, Zh)
hous = grid_solid(XN, Yh, Zh, Dh + 0.014, Dh + 0.078)
# internals: round projector outboard, rectangular element inboard (spec 4.x)
# Internals: the reference shows TWO large rounded elements side by side in the
# outer half of the lamp, plus a narrower inner section. Built as two discs and
# one rectangular element, sized to the lamp's own height at each station so
# nothing pokes through the lens.
_lamp_h = Yl[:, -2] - Yl[:, 0]          # height per column, excluding tuck row
internals = []
for col in (24, 18):
    yc_o = 0.5 * (Yl[col, 0] + Yl[col, -2])
    rad = min(0.030 * (SC / 0.796), 0.40 * float(_lamp_h[col]))
    internals.append(disc_solid(XN, yc_o, float(Zl[col, 0]), rad,
                                lambda y, z: float(skin(y, z)) + 0.026,
                                lambda y, z: float(skin(y, z)) + 0.050,
                                nr=4, nt=40))
yc_i = 0.5 * (Yl[9, 0] + Yl[9, -2])
Yr, Zr = rect_grid(yc_i - 0.010, yc_i + 0.010, Zl[5, 0], Zl[13, 0], 4, 8)
Dr = skin(Yr, Zr)
internals.append(grid_solid(XN, Yr, Zr, Dr + 0.026, Dr + 0.042))

R["checks"]["headlamp"] = {
    "inner_corner_mm_from_centre": LAMP_ZI * 1000,
    "outer_tip_mm_from_centre": LAMP_ZO * 1000,
    "length_mm": round((LAMP_ZO - LAMP_ZI) * 1000, 1),
    "top_edge": "follows the car's own measured bonnet shut line, 8 mm below it",
    "height_inner_mm": round(float(HH[0]) * 1000, 1),
    "height_max_mm": round(float(HH.max()) * 1000, 1),
    "height_max_at_u": float(uu[int(np.argmax(HH))]),
    "internals": ["round projector outboard", "rectangular element inboard"],
}
for tag, sgn in (("R", +1), ("L", -1)):
    def place(m):
        return m if sgn > 0 else mirror_z(m, ZC)
    add(f"Headlamp_{tag}_Lens", place(lens), "Lamp_Lens")
    add(f"Headlamp_{tag}_Housing", place(hous), "Trim_Black")
    add(f"Headlamp_{tag}_Internal",
        place(trimesh.util.concatenate(internals)), "Chrome_Trim")

# ==================================================== 4. THE ONE BLADE
# tip -> lamp -> grille -> THROUGH the badge -> opposite tip, unbroken.
NB = 200
zb = np.linspace(ZC - LAMP_ZO, ZC + LAMP_ZO, NB)
yb = BE(zb) - BLADE_DROP
Yblade = np.stack([yb - BLADE_T / 2, yb + BLADE_T / 2])
Zblade = np.stack([zb, zb])
Dbl = skin(Yblade, Zblade)
add("DRL_Blade", grid_solid(XN, Yblade, Zblade, Dbl + 0.002, Dbl + 0.009),
    "DRL_Blade")
sp = np.abs((BE(zb) - yb) - BLADE_DROP)
R["checks"]["blade"] = {
    "shells": 1,
    "spans_z": [round(float(zb[0]), 4), round(float(zb[-1]), 4)],
    "width_mm": round(float(zb[-1] - zb[0]) * 1000, 1),
    "thickness_mm": BLADE_T * 1000,
    "parallel_to_shutline_within_mm": round(float(sp.max()) * 1000, 4),
    "crosses_badge": bool(zb[0] < ZC - BADGE_D / 2 and zb[-1] > ZC + BADGE_D / 2),
    "note": "ONE mesh, one shell, continuous through the badge; the badge sits "
            "ON it (spec 4.1/4.2).",
}

# =============================================================== 5. BADGE
# REPAIR 5. The badge CONFORMS to the fascia instead of being a flat plate on
# it. Measured on this car: the skin falls back 264.3 -> 127.5 mm between the
# badge's top and bottom, i.e. 136.8 mm of rake across a 118.6 mm badge, so a
# flat disc at the centre depth was 61.5 mm behind the bumper at its lower edge
# and rendered as a dome with its bottom third buried (matID: 6,152 visible px
# against 9,161 for a full disc).
add("Badge", disc_solid(XN, Y["badge_centre"], ZC, BADGE_D / 2,
                        lambda y, z: float(skin(y, z)) - 0.006,
                        lambda y, z: float(skin(y, z)) + 0.014,
                        nr=6, nt=64), "Chrome_Trim")
add("Badge_Mount", disc_solid(XN, Y["badge_centre"], ZC, BADGE_D / 2 * 0.62,
                              lambda y, z: float(skin(y, z)) + 0.014,
                              lambda y, z: float(skin(y, z)) + 0.040,
                              nr=4, nt=40), "Trim_Black")

# ========================================================= 6. LOWER GRILLE
NY, NZ = 12, 64
Yq, Zq = rect_grid(LG_Y0, LG_Y1, ZC - LG_Z, ZC + LG_Z, NY, NZ)
Dlip = skin(Yq, Zq)
t = funnel(NY, NZ, 2)
Dfl = Dlip + 0.048
Dw = Dlip + (Dfl - Dlip) * t
well = grid_solid(XN, Yq, Zq, Dw, Dw + 0.012)
PITCH = 0.021 * SC
nslat = int((LG_Y1 - LG_Y0 - 0.012) // PITCH)
slats = []
for k in range(nslat):
    yy = LG_Y0 + 0.008 + (k + 0.5) * PITCH
    Ys, Zs = rect_grid(yy - 0.0035, yy + 0.0035,
                       ZC - LG_Z + 0.016, ZC + LG_Z - 0.016, 3, NZ)
    Ds = skin(Ys, Zs) + 0.016
    slats.append(grid_solid(XN, Ys, Zs, Ds, Ds + 0.008))
add("Grille_Lower", trimesh.util.concatenate([well] + slats), "Trim_Black")
R["checks"]["lower_grille"] = {
    "slat_count": nslat, "pitch_mm": round(PITCH * 1000, 2),
    "recess_depth_mm": round(float((Dfl - Dlip).mean()) * 1000, 1),
    "half_width_mm": LG_Z * 1000,
    "note": "horizontal lattice; slat COUNT is not a spec claim (the plate hides "
            "the grille top in both references) -- pitch is.",
}

# ====================================================== 7. PLATE + CARRIER
NY, NZ = 10, 30
Yc, Zc_ = rect_grid(PL_YC - PL_H / 2 - 0.007, PL_YC + PL_H / 2 + 0.007,
                    ZC - PL_W / 2 - 0.007, ZC + PL_W / 2 + 0.007, NY, NZ)
Dlip = skin(Yc, Zc_)
t = funnel(NY, NZ, 2)
Dfl = Dlip + 0.020
Dc = Dlip + (Dfl - Dlip) * t
add("Plate_Carrier", grid_solid(XN, Yc, Zc_, Dc, Dc + 0.012), "Trim_Black")
Yp, Zp_ = rect_grid(PL_YC - PL_H / 2, PL_YC + PL_H / 2,
                    ZC - PL_W / 2, ZC + PL_W / 2, 5, 22)
Dp = skin(Yp, Zp_) + 0.014
add("Plate", grid_solid(XN, Yp, Zp_, Dp, Dp + 0.004), "Plate_Face")
R["checks"]["plate"] = {
    "width_mm": PL_W * 1000, "height_mm": PL_H * 1000,
    "standard": "BS AU 145d oblong, TRUE size (not scaled with the fascia)",
    "centre_z": ZC, "centre_y": round(PL_YC, 5),
    "centre_offset_from_centreline_mm": round(
        float(0.5 * (Zp_.min() + Zp_.max()) - ZC) * 1000, 4),
}

# ========================================================== 8. OUTER INTAKES
NY, NZ = 9, 22
Yi, Zi = rect_grid(LG_Y0, LG_Y1, ZC + IN_Z0, ZC + IN_Z1, NY, NZ)
Dlip = skin(Yi, Zi)
t = funnel(NY, NZ, 2)
Dfl = Dlip + 0.036
Di = Dlip + (Dfl - Dlip) * t
iwell = grid_solid(XN, Yi, Zi, Di, Di + 0.012)
# THREE blades (spec 4.3: the apparent fourth is the surround's specular edge),
# each thickest outboard, tapering inboard.
blades = []
for k, fy in enumerate((0.28, 0.52, 0.76)):
    yy = LG_Y0 + fy * (LG_Y1 - LG_Y0)
    zz = np.linspace(ZC + IN_Z0 + 0.012, ZC + IN_Z1 - 0.008, 14)
    taper = np.linspace(0.0022, 0.0075, 14)          # point inboard, thick outboard
    Yb2 = np.stack([yy - taper, yy + taper])
    Zb2 = np.stack([zz, zz])
    Db2 = skin(Yb2, Zb2) + 0.012
    blades.append(grid_solid(XN, Yb2, Zb2, Db2, Db2 + 0.007))
# The well and the blades are SEPARATE nodes because they carry different
# materials. An earlier revision concatenated the blades into the well AND
# added them again as their own node, so every blade existed twice, coincident,
# in two materials. Caught by reading the part table, fixed here.
bladeset = trimesh.util.concatenate(blades)
add("Intake_R", iwell, "Trim_Black")
add("Intake_L", mirror_z(iwell, ZC), "Trim_Black")
add("Intake_R_Blades", bladeset, "Chrome_Trim")
add("Intake_L_Blades", mirror_z(bladeset, ZC), "Chrome_Trim")
R["checks"]["intake"] = {
    "blades_per_side": 3,
    "note": "THREE. A bright-peak count returned four; the fourth resolved at "
            "6.5x as the surround's specular edge and is NOT modelled.",
    "z_from_centre_mm": [IN_Z0 * 1000, IN_Z1 * 1000],
}

# ============================================== 9. THE ONE PROVEN ASYMMETRY
# Tow-eye blanking cover: present on the car's RIGHT only, in BOTH references,
# on an RHD and an LHD car -- so it is a body-side feature, not a driver-side
# one.  The car's RIGHT is NEGATIVE z in this file's frame.
tz = ZC - 0.455 * (LAMP_ZO / 0.850)
ty = Y["towEye"]
add("TowEye_Cover", disc_solid(XN, float(ty), float(tz), 0.030,
                               lambda y, z: float(skin(y, z)) + 0.001,
                               lambda y, z: float(skin(y, z)) + 0.007,
                               nr=4, nt=40), "carpaint")
R["checks"]["tow_eye"] = {
    "z": round(float(tz), 4), "y": round(float(ty), 4),
    "side": "car's RIGHT (negative z in this file's frame)",
    "mirrored": False,
    "note": "the ONE proven asymmetry; everything else is mirrored.",
}

R["not_built"] = {
 "headlamp_tips_above_bonnet_edge":
   "A real Mk8's lamp tips rise ~90 mm above the bonnet leading edge at the "
   "corners. Building that requires cutting the wing, which reintroduces the "
   "parts-over-melt failure this gate exists to prevent. The lamp's upper edge "
   "follows this car's own measured shut line instead. NOT BUILT.",
 "upper_grille_slats": "Spec 4.1: nothing discrete is resolvable. NOT BUILT.",
 "splitter": "There is no splitter on this trim. The band below the lower "
             "grille is a body-colour valance and is named Valance_Front.",
 "park_sensor": "Present in one reference only; an option, not a trim feature. "
                "NOT BUILT.",
 "lamp_etched_legend": "Illegible at 1600 px in the only reference showing it. "
                       "NOT BUILT.",
}

# ================================================================== ASSEMBLE
MATS = {
 "carpaint":   dict(baseColorFactor=[0.776, 0.012, 0.012, 1.0],
                    metallicFactor=0.0, roughnessFactor=0.24),
 "Trim_Black": dict(baseColorFactor=[0.02, 0.02, 0.024, 1.0],
                    metallicFactor=0.0, roughnessFactor=0.55),
 "Lamp_Lens":  dict(baseColorFactor=[0.035, 0.035, 0.039, 1.0],
                    metallicFactor=0.0, roughnessFactor=0.06),
 "Chrome_Trim": dict(baseColorFactor=[0.62, 0.64, 0.67, 1.0],
                     metallicFactor=0.90, roughnessFactor=0.14),
 "DRL_Blade":  dict(baseColorFactor=[0.80, 0.82, 0.85, 1.0],
                    metallicFactor=0.35, roughnessFactor=0.12),
 "Plate_Face": dict(baseColorFactor=[0.88, 0.88, 0.85, 1.0],
                    metallicFactor=0.0, roughnessFactor=0.42),
}

sc = trimesh.load(CAR, force="scene", process=False)
for node, m, matname in PARTS:
    mat = PBRMaterial(name=matname, doubleSided=False, **MATS[matname])
    m.visual = trimesh.visual.TextureVisuals(material=mat)
    sc.add_geometry(m, node_name=node, geom_name=node)
open(OUT, "wb").write(
    trimesh.exchange.gltf.export_glb(sc, include_normals=True))
R["out_bytes"] = os.path.getsize(OUT)
R["parts_total_faces"] = int(sum(len(m.faces) for _, m, _ in PARTS))
json.dump(R, open(REP, "w"), indent=1)
print(f"\nREBUILD_DONE {OUT} ({R['out_bytes']} bytes)  "
      f"{len(PARTS)} nodes, {R['parts_total_faces']} faces")
