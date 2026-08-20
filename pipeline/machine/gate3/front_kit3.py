#!/usr/bin/env python3
"""front_kit3.py -- GATE 3, production brief Phase 7: front rebuild.

Builds REAL component geometry for the front fascia of the gseg/Pixal car
and emits an add_parts-compatible kit npz:

  Head_Lens_R/L      closed lens solids, 14 mm thick, sitting in the aperture
  Head_Housing_R/L   closed housing boxes behind each lens (so the lens has
                     a body, and the melt cavity behind it is closed off)
  Head_Inner_R/L     bright inner reflector plate inside the housing, so the
                     unit reads as a lamp and not a black hole
  Grille_Frame       surround at the aperture rim
  Grille_Back        dark backing panel set 46 mm INTO the aperture
  Grille_Slat_0..n   horizontal slat solids between them -> real depth
  Front_Badge        proud disc on the centreline
  Intake_Frame/Back/Slat_*   lower intake, same three-layer construction
  Intake_Corner_R/L  corner air-curtain recesses
  Plate_Recess       four-walled recess box set into the bumper
  Front_Plate        the plate face inside that recess

FRAME, MEASURED ON THIS FILE, NOT ASSUMED:
  length on X, y up from ground, z lateral.  *** THE NOSE IS AT -X ***
  (verified by render: the -X end carries the badge, DRL bar and plate).
  The machine's canon frame is the opposite way round and
  pipeline/machine/front_kit.py builds at XMAX -- on this car that would
  put the entire front kit on the tailgate.
  Depth D is measured BACKWARD from the nose plane: x_world = XMIN + D.
  "Forward"/proud therefore means SMALLER D.

ORIENTATION COMES FROM CONSTRUCTION.  Every component is extruded along
-X (or a designed radial direction), never along a sampled body normal:
46% of body faces in the lamp band carry inverted normals, which built
three previous lens passes inside-out.  Positions come from the measured
depth field; only the direction field is synthetic.

SYMMETRY.  Built once on +z and mirrored.  The fascia's own features are
offset +0.05..+0.09 m in z (measured: fascia mask mirrors best at z=+0.051,
lamp band centre +0.049, badge +0.082, while the full front silhouette
mirrors at -0.028) -- the melt is skewed, the car is not.  Components are
therefore symmetric about z=0 and sized to COVER the union of both sides'
features, so no melt cavity edge is left peeking out on either side.

Run: python3 front_kit3.py <ftex.npz> <out.npz>
"""
import json
import sys
import numpy as np
from scipy import ndimage

TEX, OUT = sys.argv[1], sys.argv[2]
d = np.load(TEX, allow_pickle=True)
DM, ys, zs = d["DM"], d["ys"], d["zs"]
GY, H, HW, XMIN = float(d["GY"]), float(d["H"]), float(d["HW"]), float(d["XMIN"])
RES = float(ys[1] - ys[0])
print(f"frame: XMIN {XMIN:.4f} ground {GY:.4f} H {H:.4f} halfW {HW:.4f} "
      f"grid {DM.shape} @ {RES*1000:.0f}mm   NOSE AT -X")

SIL = np.isfinite(DM)
# shell depth field, clipped: cells that miss or run deep are "no shell here"
SHELL = np.where(SIL, DM, np.inf)

# ---------------------------------------------------------------- helpers


def sample(mask):
    """(y, z, depth) of shell cells under a mask."""
    r, c = np.nonzero(mask & SIL & (DM < 0.60))
    return ys[r], zs[c], DM[r, c]


def rim_fit(mask, ring=9):
    """Quadratic depth surface fitted to the shell on a RING around `mask`.

    The aperture interior is melt (a 200-320 mm cavity) and must not be
    fitted; the rim is the real bodywork the component has to sit in.
    Robust: two IRLS passes drop the crumpled outliers.
    """
    ringm = ndimage.binary_dilation(mask, np.ones((ring, ring))) & ~mask
    y, z, dep = sample(ringm)
    if len(y) < 60:
        raise SystemExit(f"rim_fit: only {len(y)} ring samples")
    A = np.stack([np.ones_like(y), z, y, z * z, y * y, y * z], 1)
    w = np.ones(len(y))
    for _ in range(3):
        coef, *_ = np.linalg.lstsq(A * w[:, None], dep * w, rcond=None)
        res = np.abs(A @ coef - dep)
        s = max(np.median(res), 1e-4)
        w = 1.0 / (1.0 + (res / (2.5 * s)) ** 2)
    print(f"    rim fit on {len(y)} ring cells, robust rms "
          f"{np.sqrt((w*(A@coef-dep)**2).sum()/w.sum())*1000:.1f}mm")
    return lambda Y, Z: (coef[0] + coef[1] * Z + coef[2] * Y + coef[3] * Z * Z
                         + coef[4] * Y * Y + coef[5] * Y * Z)


def shell_min(Y, Z, rad=0.014):
    """Most-FORWARD shell depth within `rad` of each (y,z) -- the envelope.

    A component placed behind this value is guaranteed not to be pierced by
    the melt's local relief when viewed from the front.  This is the
    depth-field form of rear_lamps4's envelope pass, which exists because
    a smoothed wrap is the low-pass of a bumpy nose and the bumps poke back
    through it.
    """
    k = int(round(rad / RES))
    E = ndimage.grey_erosion(np.where(np.isfinite(SHELL), SHELL, 9.0),
                             size=(2 * k + 1, 2 * k + 1))
    ri = np.clip(np.searchsorted(ys, Y), 0, len(ys) - 1)
    ci = np.clip(np.searchsorted(zs, Z), 0, len(zs) - 1)
    return E[ri, ci]


def grid_solid(Y, Z, Dfront, Dback, shape):
    """Closed solid between two depth sheets over a (ny,nz) grid."""
    ny, nz = shape
    n = ny * nz
    Yr, Zr = np.asarray(Y).ravel(), np.asarray(Z).ravel()
    Df = np.broadcast_to(np.asarray(Dfront), (ny, nz)).ravel()
    Db_ = np.broadcast_to(np.asarray(Dback), (ny, nz)).ravel()
    Vf = np.stack([XMIN + Df, Yr, Zr], 1)
    Vb = np.stack([XMIN + Db_, Yr, Zr], 1)
    V = np.vstack([Vf, Vb])
    F = []
    for j in range(ny - 1):
        for i in range(nz - 1):
            a = j * nz + i
            b = a + 1
            c = a + nz
            e = c + 1
            F += [[a, c, e], [a, e, b], [a + n, e + n, c + n], [a + n, b + n, e + n]]
    edge = ([j * nz for j in range(ny)] +
            [(ny - 1) * nz + i for i in range(1, nz)] +
            [j * nz + (nz - 1) for j in range(ny - 2, -1, -1)] +
            [i for i in range(nz - 2, 0, -1)])
    for k in range(len(edge)):
        a, b = edge[k], edge[(k + 1) % len(edge)]
        F += [[a, b, b + n], [a, b + n, a + n]]
    import trimesh
    m = trimesh.Trimesh(vertices=V, faces=np.array(F), process=True)
    m.fix_normals()
    return m


def mask_of(Yg, Zg):
    """Rasterise a component footprint onto the survey grid."""
    m = np.zeros(DM.shape, bool)
    ri = np.clip(np.searchsorted(ys, Yg.ravel()), 0, len(ys) - 1)
    ci = np.clip(np.searchsorted(zs, Zg.ravel()), 0, len(zs) - 1)
    m[ri, ci] = True
    return ndimage.binary_closing(ndimage.binary_dilation(m, np.ones((3, 3))),
                                  np.ones((5, 5)))


PARTS = []


def add(name, mesh, col, rough, metal=0.0):
    PARTS.append((name, mesh, col, rough, metal))
    print(f"  + {name:20s} {len(mesh.faces):6d} f  watertight={mesh.is_watertight}")


def mirror(name, mesh, col, rough, metal=0.0):
    m2 = mesh.copy()
    m2.vertices = m2.vertices * [1, 1, -1]
    m2.faces = m2.faces[:, ::-1]
    m2.fix_normals()
    add(name, m2, col, rough, metal)


# ================================================================ HEADLAMPS
# outline: inner |z| 0.255 -> outer 0.700; covers the union of the two
# measured cavities (left 0.263..0.653, right 0.367..0.742)
NU, NV = 34, 14
u = np.linspace(0, 1, NU)
ZC = 0.255 + u * (0.700 - 0.255)
HH = 0.030 + (0.058 - 0.030) * u ** 0.7
YC = 0.7925 + 0.004 * u
Yl = np.stack([np.linspace(YC[k] - HH[k], YC[k] + HH[k], NV) for k in range(NU)])
Zl = np.repeat(ZC[:, None], NV, 1)
lampmask = mask_of(Yl, Zl)
print("headlamp:")
rim = rim_fit(lampmask, ring=11)
Dr = rim(Yl, Zl)
print(f"    rim depth over lamp {Dr.min()*1000:.0f}..{Dr.max()*1000:.0f}mm")
PROUD, LENS_T, HOUS_T = 0.006, 0.014, 0.075
Dlens = Dr - PROUD
env = shell_min(Yl, Zl, 0.014) - 0.004          # stay in front of the melt
pierced = int((Dlens > env).sum())
# CONSTRAINT FIRST, then smooth, then re-apply the constraint.  A max-proud
# clamp applied AFTER the envelope would push the outer end of the lens back
# BEHIND the corner bodywork -- the same inside-out class that fragmented
# three earlier lamp passes.  The shell is the authority; the design is not.
Dlens = np.minimum(Dlens, env)
Dlens = np.minimum(ndimage.gaussian_filter(Dlens, 0.9, mode="nearest"), env)
print(f"    envelope: {pierced} of {Dlens.size} grid points pulled forward "
      f"(max {(Dr - PROUD - Dlens).max()*1000:.0f}mm); "
      f"lens depth {Dlens.min()*1000:.0f}..{Dlens.max()*1000:.0f}mm")
add("Head_Lens_R", grid_solid(Yl, Zl, Dlens, Dlens + LENS_T, (NU, NV)),
    [26, 27, 30], 0.06)
mirror("Head_Lens_L", PARTS[-1][1], [26, 27, 30], 0.06)
# housing: same outline, slightly inset, running back past the cavity mouth
IN = 0.9
Yh = YC[:, None] + (Yl - YC[:, None]) * IN
Zh = Zl * 1.0
add("Head_Housing_R", grid_solid(Yh, Zh, Dlens + LENS_T,
                                 Dlens + LENS_T + HOUS_T, (NU, NV)),
    [18, 18, 20], 0.55)
mirror("Head_Housing_L", PARTS[-1][1], [18, 18, 20], 0.55)
# inner reflector: a bright plate inside the housing, visible through the lens
Yi = YC[:, None] + (Yl - YC[:, None]) * 0.62
add("Head_Inner_R", grid_solid(Yi, Zh, Dlens + LENS_T + 0.030,
                               Dlens + LENS_T + 0.040, (NU, NV)),
    [196, 199, 205], 0.20, 0.85)
mirror("Head_Inner_L", PARTS[-1][1], [196, 199, 205], 0.20, 0.85)

# =================================================================== GRILLE
GZ, GY0, GY1 = 0.250, 0.752, 0.838
NZ, NY = 40, 10
Zg = np.repeat(np.linspace(-GZ, GZ, NZ)[None, :], NY, 0)
Yg = np.repeat(np.linspace(GY0, GY1, NY)[:, None], NZ, 1)
gm = mask_of(Yg, Zg)
print("grille:")
grim = rim_fit(gm, ring=11)
Dg = grim(Yg, Zg)
print(f"    rim depth over grille {Dg.min()*1000:.0f}..{Dg.max()*1000:.0f}mm")
genv = shell_min(Yg, Zg, 0.012) - 0.004
# frame: a 16 mm lip around the aperture, flush with the rim
FR = 0.016
Yf = np.repeat(np.linspace(GY0 - FR, GY1 + FR, NY)[:, None], NZ, 1)
Zf = np.repeat(np.linspace(-GZ - FR, GZ + FR, NZ)[None, :], NY, 0)
Dfr = np.minimum(grim(Yf, Zf) - 0.004, shell_min(Yf, Zf, 0.012) - 0.004)
add("Grille_Frame", grid_solid(Yf, Zf, Dfr, Dfr + 0.012, (NY, NZ)),
    [22, 22, 24], 0.35)
Dback = np.maximum(Dg + 0.046, genv + 0.010)
add("Grille_Back", grid_solid(Yg, Zg, Dback, Dback + 0.010, (NY, NZ)),
    [10, 10, 11], 0.85)
for k, yy in enumerate(np.linspace(GY0 + 0.014, GY1 - 0.014, 3)):
    Ys = np.repeat(np.linspace(yy - 0.007, yy + 0.007, 4)[:, None], NZ, 1)
    Zs = np.repeat(np.linspace(-GZ + 0.006, GZ - 0.006, NZ)[None, :], 4, 0)
    Ds = np.minimum(grim(Ys, Zs) + 0.014, shell_min(Ys, Zs, 0.010) - 0.004)
    add(f"Grille_Slat_{k}", grid_solid(Ys, Zs, Ds, Ds + 0.011, (4, NZ)),
        [16, 16, 18], 0.30)

# ==================================================================== BADGE
BR, BY = 0.048, 0.795
th = np.linspace(0, 2 * np.pi, 40, endpoint=False)
rr = np.linspace(0.10, 1.0, 6)
Yb = BY + np.outer(rr, np.cos(th)) * BR
Zb = np.outer(rr, np.sin(th)) * BR
Db = np.minimum(grim(Yb, Zb) - 0.012, shell_min(Yb, Zb, 0.010) - 0.006)
add("Front_Badge", grid_solid(Yb, Zb, Db, Db + 0.026, (6, 40)),
    [205, 208, 214], 0.14, 0.90)

# ============================================================= PLATE RECESS
PZ, PY0, PY1 = 0.262, 0.583, 0.697
NZ2, NY2 = 30, 10
Zp = np.repeat(np.linspace(-PZ, PZ, NZ2)[None, :], NY2, 0)
Yp = np.repeat(np.linspace(PY0, PY1, NY2)[:, None], NZ2, 1)
pm = mask_of(Yp, Zp)
print("plate:")
prim = rim_fit(pm, ring=9)
Dp = prim(Yp, Zp)
penv = shell_min(Yp, Zp, 0.012) - 0.004
print(f"    rim depth over plate {Dp.min()*1000:.0f}..{Dp.max()*1000:.0f}mm")
RCESS = 0.020
Dpb = np.maximum(Dp + RCESS, penv + 0.008)
# recess box: walls from rim to backing (grid_solid's perimeter wall IS the
# recess wall, so one solid gives frame + floor)
Zw = np.repeat(np.linspace(-PZ - 0.014, PZ + 0.014, NZ2)[None, :], NY2, 0)
Yw = np.repeat(np.linspace(PY0 - 0.014, PY1 + 0.014, NY2)[:, None], NZ2, 1)
Dw = np.minimum(prim(Yw, Zw) - 0.004, shell_min(Yw, Zw, 0.012) - 0.004)
add("Plate_Recess",
    grid_solid(Yw, Zw, Dw, np.maximum(Dpb, Dw + 0.014), (NY2, NZ2)),
    [24, 24, 26], 0.60)
add("Front_Plate", grid_solid(Yp, Zp, Dpb - 0.004, Dpb + 0.003, (NY2, NZ2)),
    [232, 232, 224], 0.45)

# ============================================================= LOWER INTAKE
IZ, IY0, IY1 = 0.545, 0.352, 0.420
NZ3, NY3 = 46, 9
Zi = np.repeat(np.linspace(-IZ, IZ, NZ3)[None, :], NY3, 0)
Yi2 = np.repeat(np.linspace(IY0, IY1, NY3)[:, None], NZ3, 1)
im = mask_of(Yi2, Zi)
print("lower intake:")
irim = rim_fit(im, ring=13)
Di = irim(Yi2, Zi)
ienv = shell_min(Yi2, Zi, 0.012) - 0.004
print(f"    rim depth over intake {Di.min()*1000:.0f}..{Di.max()*1000:.0f}mm")
Yif = np.repeat(np.linspace(IY0 - 0.016, IY1 + 0.016, NY3)[:, None], NZ3, 1)
Zif = np.repeat(np.linspace(-IZ - 0.016, IZ + 0.016, NZ3)[None, :], NY3, 0)
Dif = np.minimum(irim(Yif, Zif) - 0.004, shell_min(Yif, Zif, 0.012) - 0.004)
add("Intake_Frame", grid_solid(Yif, Zif, Dif, Dif + 0.014, (NY3, NZ3)),
    [20, 20, 22], 0.45)
Dib = np.maximum(Di + 0.060, ienv + 0.012)
add("Intake_Back", grid_solid(Yi2, Zi, Dib, Dib + 0.010, (NY3, NZ3)),
    [9, 9, 10], 0.88)
for k, yy in enumerate(np.linspace(IY0 + 0.014, IY1 - 0.014, 2)):
    Ys = np.repeat(np.linspace(yy - 0.008, yy + 0.008, 4)[:, None], NZ3, 1)
    Zs = np.repeat(np.linspace(-IZ + 0.008, IZ - 0.008, NZ3)[None, :], 4, 0)
    Ds = np.minimum(irim(Ys, Zs) + 0.018, shell_min(Ys, Zs, 0.010) - 0.004)
    add(f"Intake_Slat_{k}", grid_solid(Ys, Zs, Ds, Ds + 0.012, (4, NZ3)),
        [15, 15, 17], 0.35)

# =========================================================== CORNER INTAKES
CZ0, CZ1, CY0, CY1 = 0.505, 0.652, 0.455, 0.600
NZ4, NY4 = 12, 12
Zc = np.repeat(np.linspace(CZ0, CZ1, NZ4)[None, :], NY4, 0)
Yc = np.repeat(np.linspace(CY0, CY1, NY4)[:, None], NZ4, 1)
cm = mask_of(Yc, Zc)
print("corner intake:")
crim = rim_fit(cm, ring=9)
Dc = crim(Yc, Zc)
cenv = shell_min(Yc, Zc, 0.012) - 0.004
Dcf = np.minimum(Dc - 0.004, cenv)
add("Intake_Corner_R", grid_solid(Yc, Zc, Dcf,
                                  np.maximum(Dc + 0.055, cenv + 0.014),
                                  (NY4, NZ4)), [16, 16, 18], 0.55)
mirror("Intake_Corner_L", PARTS[-1][1], [16, 16, 18], 0.55)

# ==================================================================== write
out, manifest = {}, []
for name, m, col, rough, metal in PARTS:
    out[f"{name}_v"] = m.vertices
    out[f"{name}_f"] = m.faces
    manifest.append({"name": name, "v": f"{name}_v", "f": f"{name}_f",
                     "color": col, "metallic": metal, "rough": rough,
                     "doubleSided": False})
out["manifest"] = np.frombuffer(json.dumps(manifest).encode(), dtype=np.uint8)
np.savez_compressed(OUT, **out)
nf = sum(len(m.faces) for _, m, _, _, _ in PARTS)
print(f"FRONT_KIT_DONE {OUT}: {len(PARTS)} parts, {nf} faces, "
      f"{sum(m.is_watertight for _, m, _, _, _ in PARTS)}/{len(PARTS)} watertight")
