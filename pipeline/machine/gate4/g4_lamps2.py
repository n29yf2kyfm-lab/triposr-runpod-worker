#!/usr/bin/env python3
"""g4_lamps2.py — four tail-lamp solids, ONE design, SEATED PER SIDE.

WHY v2 EXISTS (measured, not guessed). v1 followed rear_lamps4's rule "build
one side and MIRROR it -- symmetry by construction". On this car that rule
FAILS, because the body is not symmetric:

    -z half-width minus +z half-width, in the lamp band, per x-slice:
      x=0.0 +0.03   x=0.6 +0.08   x=1.2 +0.13   x=1.6 +0.14   x=1.9 +0.15 m
    holds at EVERY height sampled, including y 0.85-0.96 which is above the
    tyre top (0.830), so it is not an arch-lip artefact; and the rear-view
    render silhouette is asymmetric by ~0.15 m, which agrees independently.

    The whole rear half of this car is SHEARED toward -z by up to 150 mm.

The mirrored v1 lenses were therefore buried: L outer 98% of vertices inside
the body (median -104 mm), L hatch 72% (median -10 mm). Only the R outer was
proud. CLAUDE.md records mirror asymmetry as a 0.16%-of-length no-op on
Hunyuan output; here it is 3.15% of length, twenty times that.

THE FIX is the wheel_stage pattern, not a mirror: ONE master design, SEATED on
each side's own measured surface. Both sides are built in the SAME mirrored-to
-+z parameter space with identical topology, identical angular span, identical
height band and taper, identical thickness and stand-off. Only the seating
radius r(theta, y) -- which is measured from that side's own skin -- differs.
So the two lamps are the same part; the body is what is crooked, and that is
reported rather than hidden.

Everything else is rear_lamps4's method, unchanged: orientation from
CONSTRUCTION never from body normals; ride the outward MAXIMUM of local relief;
closed solid = outer skin + inner skin + stitched perimeter wall.

Run: python3 g4_lamps2.py <car.glb> <out.npz>
"""
import json
import sys
import numpy as np
import trimesh
from scipy import ndimage

CAR, OUT = sys.argv[1], sys.argv[2]

Y_LO, Y_HI = 0.790, 0.920
Z_IN_HATCH, Z_OUT_HATCH = 0.262, 0.520
Z_IN_OUTER = 0.535
OFF, THICK, HOUSE = 0.006, 0.020, 0.030
NTH, NY = 30, 11
NZ, NYH = 18, 9

sc = trimesh.load(CAR, force="scene")
allv = np.vstack([g.vertices for g in sc.geometry.values()])
XMIN, XMAX = float(allv[:, 0].min()), float(allv[:, 0].max())
L = XMAX - XMIN
PIV = np.array([XMAX - 0.55, 0.35])

skin = []
for n in ("carpaint", "interior"):
    g = sc.geometry[n]
    c = g.triangles_center
    skin.append(c[c[:, 0] > XMAX - 0.42 * L])
SK = np.vstack(skin)
BAND = SK[(SK[:, 1] > Y_LO - 0.10) & (SK[:, 1] < Y_HI + 0.10)]


def outermost(v):
    if len(v) >= 25:
        return float(np.percentile(v, 99.0))
    return float(np.sort(v)[-2]) if len(v) >= 2 else float(v[-1])


def solid(pos, nrm, off, t):
    ny, nx = pos.shape[0], pos.shape[1]
    P = pos.reshape(-1, 3); N = nrm.reshape(-1, 3); n = len(P)
    V = np.vstack([P + N * (off + t), P + N * off])
    F = []
    for j in range(ny - 1):
        for i in range(nx - 1):
            a = j * nx + i; b = a + 1; c = a + nx; d2 = c + 1
            F += [[a, c, d2], [a, d2, b]]
            A, B, C, D = a + n, b + n, c + n, d2 + n
            F += [[A, D, C], [A, B, D]]
    edge = ([j * nx for j in range(ny)] +
            [(ny - 1) * nx + i for i in range(1, nx)] +
            [j * nx + (nx - 1) for j in range(ny - 2, -1, -1)] +
            [i for i in range(nx - 2, 0, -1)])
    for e in range(len(edge)):
        a, b = edge[e], edge[(e + 1) % len(edge)]
        F += [[a, b, b + n], [a, b + n, a + n]]
    m = trimesh.Trimesh(vertices=V, faces=np.array(F), process=True)
    m.fix_normals()
    return m


def theta_of(x, z):
    return np.degrees(np.arctan2(z - PIV[1], x - PIV[0]))


TH_IN = theta_of(1.978, Z_IN_OUTER)
TH_OUT = 88.0
thetas = np.linspace(TH_IN, TH_OUT, NTH)
u = np.linspace(0.0, 1.0, NTH)
ylo_t = (Y_LO + 0.010) + (1 - u) * 0.008
yhi_t = (Y_HI - 0.012) - (1 - u) * 0.012
ys_ref = np.linspace(Y_LO, Y_HI, NY)
zs = np.linspace(Z_OUT_HATCH, Z_IN_HATCH, NZ)
uh = np.linspace(0.0, 1.0, NZ)
ylo_h = (Y_LO + 0.010) + uh * 0.028
yhi_h = (Y_HI - 0.015) - uh * 0.030


def build_side(sign):
    """Build both units for one side, in mirrored-to-+z parameter space."""
    S = BAND[BAND[:, 2] * sign > 0].copy()
    S[:, 2] *= sign                                   # mirror this side to +z
    ang = theta_of(S[:, 0], S[:, 2])
    rad = np.hypot(S[:, 0] - PIV[0], S[:, 2] - PIV[1])

    # ---- OUTER: p99 outer radius per (theta, y) cell = the envelope
    R = np.full((NTH, NY), np.nan)
    for i, t in enumerate(thetas):
        mt = np.abs(ang - t) < 3.0
        if mt.sum() < 8:
            continue
        for j, yy in enumerate(ys_ref):
            m = mt & (np.abs(S[:, 1] - yy) < 0.016)
            if m.sum() >= 3:
                R[i, j] = outermost(rad[m])
    for j in range(NY):
        col = R[:, j]; ok = ~np.isnan(col)
        if ok.sum() >= 2:
            R[:, j] = np.interp(np.arange(NTH), np.where(ok)[0], col[ok])
    for i in range(NTH):
        row = R[i]; ok = ~np.isnan(row)
        if ok.sum() >= 2:
            R[i] = np.interp(np.arange(NY), np.where(ok)[0], row[ok])
    if np.isnan(R).any():
        R[np.isnan(R)] = np.nanmedian(R)
    R = np.maximum(R, ndimage.gaussian_filter(R, 0.9, mode="nearest"))

    pos_o = np.zeros((NTH, NY, 3)); nrm_o = np.zeros((NTH, NY, 3))
    for i, t in enumerate(thetas):
        tr = np.radians(t)
        d = np.array([np.cos(tr), 0.0, np.sin(tr)])       # CONSTRUCTION normal
        yy = np.linspace(ylo_t[i], yhi_t[i], NY)
        r = np.interp(yy, ys_ref, R[i])
        for j in range(NY):
            p2 = PIV + r[j] * np.array([d[0], d[2]])
            pos_o[i, j] = [p2[0], yy[j], p2[1]]
            nrm_o[i, j] = d

    # ---- HATCH: tail face, x = outward maximum, CONSTRUCTION normal +x
    Xf = np.full((NZ, NYH), np.nan)
    for i, zz in enumerate(zs):
        mz = np.abs(S[:, 2] - zz) < 0.022
        yy = np.linspace(ylo_h[i], yhi_h[i], NYH)
        for j, y0 in enumerate(yy):
            m = mz & (np.abs(S[:, 1] - y0) < 0.016)
            if m.sum() >= 3:
                Xf[i, j] = outermost(S[m, 0])
    for j in range(NYH):
        col = Xf[:, j]; ok = ~np.isnan(col)
        if ok.sum() >= 2:
            Xf[:, j] = np.interp(np.arange(NZ), np.where(ok)[0], col[ok])
    if np.isnan(Xf).any():
        Xf[np.isnan(Xf)] = np.nanmedian(Xf)
    Xf = np.maximum(Xf, ndimage.gaussian_filter(Xf, 0.9, mode="nearest"))
    pos_h = np.zeros((NZ, NYH, 3)); nrm_h = np.zeros((NZ, NYH, 3))
    for i, zz in enumerate(zs):
        yy = np.linspace(ylo_h[i], yhi_h[i], NYH)
        for j in range(NYH):
            pos_h[i, j] = [Xf[i, j], yy[j], zz]
            nrm_h[i, j] = [1.0, 0.0, 0.0]

    res = {}
    for key, pos, nrm in (("o", pos_o, nrm_o), ("h", pos_h, nrm_h)):
        lens = solid(pos, nrm, OFF, THICK)
        hous = solid(pos, nrm, -HOUSE, HOUSE - 0.002)
        if sign < 0:                                   # mirror back to -z
            for m in (lens, hous):
                m.vertices = m.vertices * np.array([1.0, 1.0, -1.0])
                m.faces = m.faces[:, ::-1]
                m.fix_normals()
        res[key] = (lens, hous)
    return res, R, Xf


out, rep = {}, {}
for sign, side in ((+1, "R"), (-1, "L")):
    r, R, Xf = build_side(sign)
    rep[f"seat_{side}"] = dict(outer_radius_min=float(R.min()), outer_radius_max=float(R.max()),
                               hatch_x_min=float(Xf.min()), hatch_x_max=float(Xf.max()))
    print(f"{side}: outer radius {R.min():.3f}..{R.max():.3f}  hatch x {Xf.min():.3f}..{Xf.max():.3f}")
    for key, unit in (("o", "O"), ("h", "H")):
        lens, hous = r[key]
        tag = f"{side}{unit}"
        for nm, m in ((tag, lens), (tag + "_house", hous)):
            ext = m.vertices.max(0) - m.vertices.min(0)
            print(f"   {nm}: {len(m.faces)}f watertight={m.is_watertight} "
                  f"vol={m.volume*1e6:.0f}cm3 ext {ext[0]:.3f}x{ext[1]:.3f}x{ext[2]:.3f}")
            out[f"{nm}_v"] = m.vertices; out[f"{nm}_f"] = m.faces
            rep[nm] = dict(faces=int(len(m.faces)), watertight=bool(m.is_watertight),
                           volume_cm3=float(m.volume * 1e6),
                           ext=[float(e) for e in ext])

bad = [k for k, v in rep.items() if isinstance(v, dict) and v.get("watertight") is False]
if bad:
    raise SystemExit(f"REFUSED: lamp solids not watertight: {bad}")

# ---- ONE DESIGN check: the two sides must have identical topology and, in
# the (theta,y)/(z,y) parameter space, identical footprints.
same_top = (len(out["RO_f"]) == len(out["LO_f"]) and len(out["RH_f"]) == len(out["LH_f"]))
hR = out["RO_v"][:, 1].max() - out["RO_v"][:, 1].min()
hL = out["LO_v"][:, 1].max() - out["LO_v"][:, 1].min()
print(f"\nONE-DESIGN check: identical topology={same_top}; "
      f"outer unit height R {hR*1000:.1f}mm vs L {hL*1000:.1f}mm "
      f"(delta {abs(hR-hL)*1000:.2f}mm)")
rep["one_design"] = dict(identical_topology=bool(same_top),
                         height_R_mm=float(hR * 1000), height_L_mm=float(hL * 1000))
if not same_top:
    raise SystemExit("REFUSED: the two sides are not the same design")

allz = np.concatenate([np.abs(out["RO_v"][:, 2]), np.abs(out["RH_v"][:, 2])])
rep["band_R"] = dict(inner_abs_z=float(allz.min()), outer_abs_z=float(allz.max()))
allzl = np.concatenate([np.abs(out["LO_v"][:, 2]), np.abs(out["LH_v"][:, 2])])
rep["band_L"] = dict(inner_abs_z=float(allzl.min()), outer_abs_z=float(allzl.max()))
print(f"R assembly |z| {allz.min():.3f}..{allz.max():.3f}; "
      f"L assembly |z| {allzl.min():.3f}..{allzl.max():.3f}")

np.savez(OUT, **out)
json.dump(rep, open(OUT.replace(".npz", ".json"), "w"), indent=1)
print("wrote", OUT)
