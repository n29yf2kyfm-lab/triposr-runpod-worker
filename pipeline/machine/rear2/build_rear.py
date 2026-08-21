#!/usr/bin/env python3
"""build_rear.py — build the rebuilt rear panels as closed pressings.

Each panel is:
  OUTER SKIN   the fitted Class-A surface, inset from the measured component
               outline by GAP so a REAL panel gap exists (not a painted line)
  INNER SKIN   the same surface offset inward by the panel thickness, and
               extended FLANGE beyond the outer outline so it shows in the gap
               as a dark hemmed edge -- the shut-line backstop. A gap with
               nothing behind it is a hole; a gap with a dark flange behind it
               is a shut line.
  RETURN       outer and inner stitched all round, so the panel is a closed
               solid, not a sheet.

The tailgate is ONE component built from TWO fitted patches sharing a single
vertex row at the backlight sill, so the sill is a real CREASE and the door is
still watertight. Its backlight APERTURE is a rectangle in the panel's own
(u,v) parameter space with grid lines placed exactly on its edges -- so the
screen boundary is clean BY CONSTRUCTION rather than by smoothing a ragged one.

Run: python3 build_rear.py <glb> <outdir>
"""
import json, os, sys
import numpy as np, trimesh
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from patchlib import Patch, arclen_u, grid_normals, orient_outward, quads
from residual import SkinMap, smooth_residual

GLB = sys.argv[1]; OUTD = sys.argv[2] if len(sys.argv) > 2 else "build"
os.makedirs(OUTD, exist_ok=True)

GAP = 0.0035          # lateral panel gap, per side -> a ~7 mm seam to the quarters
GAP_V = 0.0020        # tailgate/bumper seam, per side -> ~4 mm. Kept TIGHTER than
                      # the lateral gap on purpose: the car's own measured profile
                      # steps back 48 mm between y 0.550 and y 0.570, so that seam
                      # already reads as a deep shadow and an 8 mm gap on top of it
                      # rendered as a broad black band across the tail.
FLANGE = 0.014        # how far the dark inner skin peeks beyond the outer edge
T_HATCH = 0.014       # tailgate panel thickness
T_BUMPER = 0.018
GLASS_SETBACK = 0.003 # brief phase 5: 2-3 mm standoff
GLASS_TUCK = 0.012    # glass overlaps behind the frame by this much

# backlight aperture, in the surround patch's own parameter space
AP_U = 0.90           # lateral frame  (~55-64 mm at this panel's widths)
AP_Y0, AP_Y1 = 1.015, 1.262

rep = {"GAP": GAP, "FLANGE": FLANGE, "T_HATCH": T_HATCH, "T_BUMPER": T_BUMPER,
       "AP_U": AP_U, "AP_Y0": AP_Y0, "AP_Y1": AP_Y1}

_sc = trimesh.load(GLB, force="scene", process=False)
_P = np.vstack([g.triangles_center for n, g in _sc.geometry.items()
                if not n.startswith(("Tail_Lens", "Tail_Housing", "Rear_Plate"))])
_ye = np.arange(0.20, 0.60, 0.01)
_lo, _hi = [], []
for _y in _ye:
    _m = (np.abs(_P[:, 1] - _y) < 0.02) & (_P[:, 0] > 1.35)
    _lo.append(np.percentile(_P[_m, 2], 0.3)); _hi.append(np.percentile(_P[_m, 2], 99.7))
_k = np.ones(9) / 9.0
_lo = np.convolve(np.r_[[_lo[0]] * 4, _lo, [_lo[-1]] * 4], _k, "valid")
_hi = np.convolve(np.r_[[_hi[0]] * 4, _hi, [_hi[-1]] * 4], _k, "valid")
ENV_LO = lambda y: float(np.interp(y, _ye, _lo))
ENV_HI = lambda y: float(np.interp(y, _ye, _hi))

SIGMA_CELLS = 7.0     # residual low-pass width, in grid cells (~45 mm here)

P_low = Patch("measurements/fit_hatch_low.npz")
P_sur = Patch("measurements/fit_hatch_surr.npz")
P_bmp = Patch("measurements/fit_bumper.npz")
Y_SILL = P_low.yhi

SKIN_CART = SkinMap(_P, np.arange(0.545, 1.345, 0.010), np.arange(-0.78, 0.66, 0.010), "cart")
SKIN_RAD = SkinMap(_P, np.arange(0.215, 0.585, 0.010), np.arange(-92.0, 92.0, 1.0), "radial",
                   pivot=lambda y: (P_bmp.frame(y)[2], P_bmp.frame(y)[3]), xmin=1.35)


def apply_residual(V, mode, tag):
    """pull the fitted grid onto the measured skin with a LOW-PASSED offset."""
    nv, nu, _ = V.shape
    y = V[..., 1].ravel()
    if mode == "radial":
        xc = np.array([P_bmp.frame(t)[2] for t in V[..., 1].ravel()])
        zc = np.array([P_bmp.frame(t)[3] for t in V[..., 1].ravel()])
        q = np.degrees(np.arctan2(V[..., 2].ravel() - zc, V[..., 0].ravel() - xc))
        val = np.hypot(V[..., 0].ravel() - xc, V[..., 2].ravel() - zc)
        meas, ok = SKIN_RAD.sample(y, q)
    else:
        q = V[..., 2].ravel(); val = V[..., 0].ravel()
        meas, ok = SKIN_CART.sample(y, q)
    res = (meas - val).reshape(nv, nu)
    ok = ok.reshape(nv, nu)
    res = np.clip(res, -0.30, 0.30)
    sm = smooth_residual(res, ok, SIGMA_CELLS)
    W = V.copy()
    if mode == "radial":
        a = np.radians(q).reshape(nv, nu)
        W[..., 0] += sm * np.cos(a); W[..., 2] += sm * np.sin(a)
    else:
        W[..., 0] += sm
    rep.setdefault("residual", {})[tag] = {
        "n": int(res.size), "measured_cells_pct": round(float(ok.mean() * 100), 2),
        "raw_res_rms_mm": round(float(np.sqrt(np.mean(res[ok] ** 2)) * 1000), 3),
        "raw_res_p95_mm": round(float(np.percentile(np.abs(res[ok]), 95) * 1000), 3),
        "raw_res_max_mm": round(float(np.abs(res[ok]).max() * 1000), 3),
        "applied_rms_mm": round(float(np.sqrt(np.mean(sm ** 2)) * 1000), 3),
        "applied_max_mm": round(float(np.abs(sm).max() * 1000), 3),
        "post_res_rms_mm": round(float(np.sqrt(np.mean((res - sm)[ok] ** 2)) * 1000), 3),
        "post_res_p95_mm": round(float(np.percentile(np.abs((res - sm)[ok]), 95) * 1000), 3),
        "sigma_cells": SIGMA_CELLS}
    return W


def ring_rect(i0, i1, j0, j1):
    r = [(i0, j) for j in range(j0, j1)] + [(i, j1) for i in range(i0, i1)] + \
        [(i1, j) for j in range(j1, j0, -1)] + [(i, j0) for i in range(i1, i0, -1)]
    return r


def stitch(Vo, Vi, ring, nu, outward_sign, base_i, base_o=0):
    """quads joining outer ring to inner ring; winding chosen by measurement."""
    F = []
    ctr = Vo.reshape(-1, 3).mean(0)
    for k in range(len(ring)):
        i0, j0 = ring[k]; i1, j1 = ring[(k + 1) % len(ring)]
        a = base_o + i0 * nu + j0; b = base_o + i1 * nu + j1
        c = base_i + i1 * nu + j1; d = base_i + i0 * nu + j0
        pa, pb = Vo[i0, j0], Vo[i1, j1]
        e = pb - pa
        mid = 0.5 * (pa + pb)
        away = mid - ctr; away -= e * np.dot(away, e) / (np.dot(e, e) + 1e-12)
        nrm = np.cross(pb - pa, Vi[i0, j0] - pa)
        if np.dot(nrm, away) * outward_sign > 0:
            F += [[a, b, c], [a, c, d]]
        else:
            F += [[a, c, b], [a, d, c]]
    return F


SLOPE_MAX = 3.0       # |dx/dz| beyond which x(y,z) stops being a usable surface


def row_u_limits(pat, y, uu_ref):
    """widest u interval around the panel centre where the measured skin is
    ACTUALLY THERE and single-valued.

    Gate 4's Rear_Hatch footprint reaches the tailgate's top corners, but at
    those corners the +z D-pillar plunges forward and the surface becomes
    nearly PARALLEL to x -- so x(y,z) has no value to measure and the skin map
    is simply empty there (measured: SkinMap(1.32, +0.51) invalid, and the
    polynomial alone put that corner at x = 1.010 against a real ~1.20). The
    panel is trimmed to where the measurement exists rather than extrapolated
    into where it does not; the D-pillar corner keeps its original geometry and
    that is reported as a residual, not hidden.
    """
    v = pat.v_of_y(y)
    us = np.linspace(-1, 1, 401)
    P4 = pat.point(us, np.full(401, v))
    _, ok = SKIN_CART.sample(P4[:, 1], P4[:, 2])
    a, _ = SKIN_CART.sample(P4[:, 1], P4[:, 2] - 0.02)
    b, _ = SKIN_CART.sample(P4[:, 1], P4[:, 2] + 0.02)
    slope = np.abs(b - a) / 0.04
    good = ok & (slope < SLOPE_MAX)
    c = int(np.argmin(np.abs(us)))
    lo = c
    while lo > 0 and good[lo - 1]: lo -= 1
    hi = c
    while hi < 400 and good[hi + 1]: hi += 1
    return us[lo], us[hi]


def build_hatch():
    NU, NV_L, NV_S = 161, 46, 61
    # ---- v nodes: hatch_low rows, then the SHARED SILL ROW, then surround rows
    yl = np.linspace(P_low.ylo + GAP_V, Y_SILL, NV_L)
    yu = np.linspace(Y_SILL, 1.300, NV_S)
    # surround v nodes must land EXACTLY on the aperture edges. SNAP the nearest
    # existing node rather than INSERTING one: inserting produced sliver rows a
    # fraction of a millimetre tall next to their neighbours (the hatch's edge
    # length CV read 1.29 against the melt's 0.46 -- a rebuilt panel should be
    # MORE regular than what it replaces, not less).
    for tv in (AP_Y0, AP_Y1):
        yu[int(np.argmin(np.abs(yu - tv)))] = tv
    yu = np.unique(yu)
    ys = np.r_[yl[:-1], yu]
    NV = len(ys)
    ia0, ia1 = int(np.argmin(np.abs(ys - AP_Y0))), int(np.argmin(np.abs(ys - AP_Y1)))
    # ---- u nodes: land exactly on +-AP_U
    uu = np.linspace(-1, 1, NU)
    for tv in (-AP_U, AP_U):
        uu[int(np.argmin(np.abs(uu - tv)))] = tv
    uu = np.unique(uu)
    NU = len(uu)
    ja0, ja1 = int(np.argmin(np.abs(uu + AP_U))), int(np.argmin(np.abs(uu - AP_U)))

    def rows(margin_u, margin_v_bot):
        V = np.zeros((NV, NU, 3))
        for i, y in enumerate(ys):
            pat = P_low if y < Y_SILL - 1e-9 else P_sur
            yy = np.clip(y + (margin_v_bot if i == 0 else 0.0), 0.2, 1.5)
            v = pat.v_of_y(yy)
            lo, hi, xc, zc = pat.frame(yy)
            # shrink u to inset margin_u metres from the outline, per row
            ulo, uhi = row_u_limits(pat, yy, uu)
            span = pat.point(np.array([ulo, uhi]), np.array([v, v]))
            L = np.linalg.norm(span[1] - span[0])
            f = 1.0 - 2.0 * margin_u / max(L, 1e-6)
            umid, uhalf = 0.5 * (ulo + uhi), 0.5 * (uhi - ulo)
            un = umid + uu * uhalf * f
            if abs(y - Y_SILL) < 1e-9:      # SHARED SILL ROW: mean of both fits
                a = P_low.point(un, np.full(NU, P_low.v_of_y(yy)))
                b = P_sur.point(un, np.full(NU, P_sur.v_of_y(yy)))
                V[i] = 0.5 * (a + b)
            else:
                V[i] = pat.point(un, np.full(NU, v))
        return V

    Vo = apply_residual(rows(GAP, 0.0), "cart", "hatch_outer")
    Vi_s = apply_residual(rows(GAP - FLANGE, -FLANGE), "cart", "hatch_inner")
    N = orient_outward(Vo, grid_normals(Vo), (1.30, -0.07))
    Vi = Vi_s - T_HATCH * N
    mask = np.ones((NV - 1, NU - 1), bool)
    mask[ia0:ia1, ja0:ja1] = False
    nvert = NV * NU
    V = np.vstack([Vo.reshape(-1, 3), Vi.reshape(-1, 3)])
    F = [quads(NV, NU, mask, flip=False, base=0),
         quads(NV, NU, mask, flip=True, base=nvert)]
    F.append(np.array(stitch(Vo, Vi, ring_rect(0, NV - 1, 0, NU - 1), NU, +1, nvert), np.int64))
    F.append(np.array(stitch(Vo, Vi, ring_rect(ia0, ia1, ja0, ja1), NU, -1, nvert), np.int64))
    ngrp = [len(x) for x in F]
    F = np.vstack(F)
    ap = dict(ia0=ia0, ia1=ia1, ja0=ja0, ja1=ja1, NU=NU, NV=NV, uu=uu, ys=ys)
    return V, F, Vo, N, ap, (NV, NU), np.array(ngrp)


def build_glass(ap, Vo, N):
    """the backlight pane, cut from the tailgate's OWN aperture grid.

    Built by slicing the panel grid rather than re-evaluating the surface, so
    the pane and the aperture are the same curve by construction -- there is no
    way for them to disagree, which is the whole point: the boundary this gate
    is asked to clean was ragged because glass and body were two independent
    labels on melt.
    """
    ia0, ia1, ja0, ja1 = ap["ia0"], ap["ia1"], ap["ja0"], ap["ja1"]
    NV, NU = Vo.shape[0], Vo.shape[1]
    TUCK = 2                                   # grid cells tucked behind the frame
    r0, r1 = max(0, ia0 - TUCK), min(NV - 1, ia1 + TUCK)
    c0, c1 = max(0, ja0 - TUCK), min(NU - 1, ja1 + TUCK)
    G = Vo[r0:r1 + 1, c0:c1 + 1].copy()
    NG = N[r0:r1 + 1, c0:c1 + 1]
    G = G - GLASS_SETBACK * NG
    V = G.reshape(-1, 3)
    F = quads(G.shape[0], G.shape[1], None, flip=False, base=0)
    return V, F


def build_bumper():
    NU, NV = 221, 76
    env_lo, env_hi = ENV_LO, ENV_HI
    ys = np.linspace(P_bmp.ylo + GAP_V, P_bmp.yhi - GAP_V, NV)
    _, _, xc0, zc0 = P_bmp.frame(0.43)
    # plate recess, centred on the BUMPER'S OWN section centre (the body is
    # sheared; centring on z=0 would sit 70 mm off this panel's own middle)
    PZ, PY = zc0, 0.4305
    RZ, RY, RD, RW = 0.285, 0.082, 0.022, 0.010

    def rows(margin_u, margin_v_extra, recess):
        """ENVELOPE CLAMP, added after measurement: the smoothed outline
        extrapolates past the flank tangent (theta reached -90.8 deg), and the
        first build put the bumper's ends 15-22 mm PROUD of the car's own
        measured flank (z -0.915 against a body -0.900). A panel that sticks
        out through the body is not a rebuild. Each row's u range is now
        trimmed until the built point sits inside that height's own measured
        section -- per side, so the 130 mm shear is respected."""
        V = np.zeros((NV, NU, 3))
        for i, y in enumerate(ys):
            yy = y + (margin_v_extra if i == 0 else (-margin_v_extra if i == NV - 1 else 0))
            v = P_bmp.v_of_y(yy)
            us = np.linspace(-1, 1, 801)
            pts = P_bmp.point(us, np.full(801, v))
            zlo, zhi = env_lo(yy) + 0.003, env_hi(yy) - 0.003
            ok = (pts[:, 2] >= zlo) & (pts[:, 2] <= zhi)
            if ok.sum() < 50:
                u = arclen_u(P_bmp, v, NU, margin_u)
            else:
                a, b = us[ok][0], us[ok][-1]
                uu2 = np.linspace(a, b, 601)
                pp = P_bmp.point(uu2, np.full(601, v))
                d = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(pp, axis=0), axis=1))]
                S = d[-1]; m = np.clip(margin_u, -0.25 * S, 0.45 * S)
                u = np.interp(np.linspace(m, S - m, NU), d, uu2)
            V[i] = P_bmp.point(u, np.full(NU, v))
        return V

    Vo = apply_residual(rows(GAP, 0.0, True), "radial", "bumper_outer")
    Vi_s = apply_residual(rows(GAP - FLANGE, -FLANGE, True), "radial", "bumper_inner")
    N = orient_outward(Vo, grid_normals(Vo), (xc0, zc0))
    # ---- recess: smoothstep pocket, applied to BOTH skins so thickness holds
    def depth(V):
        dz = np.abs(V[..., 2] - PZ); dy = np.abs(V[..., 1] - PY)
        sz = np.clip((RZ - dz) / RW, 0, 1); sy = np.clip((RY - dy) / RW, 0, 1)
        s = (sz * sz * (3 - 2 * sz)) * (sy * sy * (3 - 2 * sy))
        return s
    so, si = depth(Vo), depth(Vi_s)
    Vo = Vo - (RD * so)[..., None] * N
    Vi = (Vi_s - (RD * si)[..., None] * N) - T_BUMPER * N
    nvert = NV * NU
    V = np.vstack([Vo.reshape(-1, 3), Vi.reshape(-1, 3)])
    _f = [quads(NV, NU, None, False, 0), quads(NV, NU, None, True, nvert),
          np.array(stitch(Vo, Vi, ring_rect(0, NV - 1, 0, NU - 1), NU, +1, nvert), np.int64)]
    bgrp = np.array([len(x) for x in _f]); F = np.vstack(_f)
    # ---- the plate itself, on the recess floor
    pz = np.linspace(PZ - 0.260, PZ + 0.260, 33)
    py = np.linspace(PY - 0.0555, PY + 0.0555, 9)
    PG = np.zeros((len(py), len(pz), 3))
    for i, y in enumerate(py):
        v = P_bmp.v_of_y(y)
        lo, hi, xcc, zcc = P_bmp.frame(y)
        th = np.degrees(np.arctan2(pz - zcc, 0.0 * pz + 1.0))
        u = (th - 0.5 * (lo + hi)) / (0.5 * (hi - lo))
        p = P_bmp.point(np.clip(u, -1, 1), np.full(len(pz), v))
        p[:, 2] = pz
        PG[i] = p
    PN = orient_outward(PG, grid_normals(PG), (xcc, zcc))
    PG = PG - (RD - 0.002) * PN
    PV = PG.reshape(-1, 3); PF = quads(len(py), len(pz), None, False, 0)
    return (V, F, bgrp), (PV, PF), dict(PZ=float(PZ), PY=float(PY), RZ=RZ, RY=RY, RD=RD,
                                  plate_w=0.520, plate_h=0.111)


import panel_fit as pfm
HV, HF, HVo, HN, AP, HSHAPE, HGRP = build_hatch()
GV, GF = build_glass(AP, HVo, HN)
(BV, BF, BGRP), (PV, PF), pinfo = build_bumper()
np.savez(f"{OUTD}/panels.npz",
         HV=HV, HF=HF, GV=GV, GF=GF, BV=BV, BF=BF, PV=PV, PF=PF,
         HGRP=HGRP, BGRP=BGRP, HVo=HVo, HN=HN, BNV=76, BNU=221,
         hatch_nvert=HSHAPE[0] * HSHAPE[1], NV=HSHAPE[0], NU=HSHAPE[1])
rep["hatch"] = {"verts": int(len(HV)), "faces": int(len(HF)),
                "grid": [int(HSHAPE[0]), int(HSHAPE[1])],
                "aperture_rows": [int(AP["ia0"]), int(AP["ia1"])],
                "aperture_cols": [int(AP["ja0"]), int(AP["ja1"])]}
rep["glass_backlight"] = {"verts": int(len(GV)), "faces": int(len(GF))}
rep["bumper"] = {"verts": int(len(BV)), "faces": int(len(BF))}
rep["plate"] = {"verts": int(len(PV)), "faces": int(len(PF)), **pinfo}
for k in ("hatch", "glass_backlight", "bumper", "plate"):
    v = {"hatch": HV, "glass_backlight": GV, "bumper": BV, "plate": PV}[k]
    rep[k]["bbox_min"] = [round(float(x), 4) for x in v.min(0)]
    rep[k]["bbox_max"] = [round(float(x), 4) for x in v.max(0)]
rep["built_waviness"] = {
    "hatch_outer": pfm.grid_waviness(HVo.reshape(-1, 3)),
    "bumper_outer": pfm.grid_waviness(BV[:len(BV) // 2])}
json.dump(rep, open(f"{OUTD}/build_report.json", "w"), indent=1)
print(json.dumps(rep, indent=1))
