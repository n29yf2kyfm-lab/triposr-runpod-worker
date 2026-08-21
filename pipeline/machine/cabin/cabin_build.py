#!/usr/bin/env python3
"""cabin_build.py — parametric low-detail cabin for car_rebound.glb.

EVERY dimension below is derived from a MEASUREMENT of this car, printed at the
top of the run, never from y=0 and never from a spec sheet. The measured frame:

  FLOOR  0.300  body floorpan between the sills (p10 of Body_Shell y = 0.263)
  BELT   0.980  minimum y of the side glazing
  WSBASE (-1.178, 0.997)  windscreen pane's forward-lower edge
  FAX   -1.2557  front axle (rim centres)   RAX +1.2177  rear axle
  half-width by height: measured table in HALFW below

ORIENTATION, derived not assumed:
  * nose at -X   — confirmed by three renders (az180 shows grille + headlamps)
  * up  at +Y    — glTF
  * vehicle RIGHT = forward x up = (-X) x (+Y) = -Z, so the RHD steering wheel
    goes at NEGATIVE z. (Node `Glass_Side_L` is therefore on the vehicle's
    RIGHT; the node names are inverted vs vehicle convention. Not renamed.)

IDENTITY: 2020 UK Golf Mk8 Style, RHD, five-door. This is an OWNER-AUTHORISED
ASSUMPTION, not a verification — nothing in the mesh proves the trim or the
market, and the wheelbase measures 2.474 m against a published 2.636 m.

Run: python3 cabin_build.py <out.npz>
"""
import json
import sys
import numpy as np
import trimesh

OUT = sys.argv[1] if len(sys.argv) > 1 else "cabin_kit.npz"

# ------------------------------------------------------------ measured frame
import os
_S = np.load(os.environ.get("CABIN_SURF", "body_surf.npz"))
_FR = json.loads(bytes(_S["frame"]).decode())
FLOOR = _FR["FLOOR"]
BELT = _FR["BELT"]
WSBASE = tuple(_FR["WSB"])
FAX, RAX = _FR["FAX"], _FR["RAX"]
RIGHT = -1.0                      # sign of z on the vehicle's right

# measured Body_Shell inner half-width by height, cabin x-span
HALFW = [tuple(r) for r in _FR["HALFW"]]
# measured roof underside by x
ROOFY = [tuple(r) for r in _FR["ROOFY"]]


def _bil(gridname, a, b, ea, eb):
    """Sample a measured body surface grid, clamped to its domain."""
    G = _S[gridname]
    ca = (ea[:-1] + ea[1:]) / 2
    cb = (eb[:-1] + eb[1:]) / 2
    ia = np.clip(np.searchsorted(ca, a) - 1, 0, len(ca) - 2)
    ib = np.clip(np.searchsorted(cb, b) - 1, 0, len(cb) - 2)
    ta = np.clip((a - ca[ia]) / (ca[ia + 1] - ca[ia]), 0, 1)
    tb = np.clip((b - cb[ib]) / (cb[ib + 1] - cb[ib]), 0, 1)
    return ((1 - ta) * ((1 - tb) * G[ia, ib] + tb * G[ia, ib + 1]) +
            ta * ((1 - tb) * G[ia + 1, ib] + tb * G[ia + 1, ib + 1]))


def zin(side, x, y):
    """Measured |z| of the body's inner flank surface. side -1 => z<0."""
    return _bil("ZIN_R" if side < 0 else "ZIN_L", np.atleast_1d(x),
                np.atleast_1d(y), _S["xe"], _S["ye"])


def ytop(x, z):
    """Measured roof underside."""
    return _bil("YTOP", np.atleast_1d(x), np.atleast_1d(z), _S["xe"], _S["ze"])


def interp(table, v):
    xs = np.array([t[0] for t in table])
    ys = np.array([t[1] for t in table])
    return float(np.interp(v, xs, ys))


BELTX = [tuple(r) for r in _FR["BELTX"]]
_sc0 = trimesh.load(os.environ.get("CABIN_CAR", "car_merged.glb"),
                    force="scene", process=False)
_T, _gn = _sc0.graph["Glass_Windscreen"]
_WS = trimesh.transform_points(_sc0.geometry[_gn].vertices, _T)


def belt_at(x):
    return interp(BELTX, x)


# Packaging. TWO independent derivations of the front H-point height, reported
# so the choice is visible rather than asserted:
#   (a) from the measured floorpan: carpet ~55 mm above the pan underside, and a
#       C-segment H-point ~285 mm above the carpet
#   (b) from the local beltline: an occupant's shoulder sits at about the
#       beltline, ~450 mm above the H-point
# (b) governs, because what this gate is judged on is what reads THROUGH THE
# GLASS, and that is set by the seats' height relative to the windows, not to
# the floor. (a) is used only as a floor for the value.
_HPX = FAX + 0.640
_hp_floor = FLOOR + 0.055 + 0.285
_hp_belt = belt_at(_HPX) - 0.450
HP_F = (_HPX, max(_hp_belt, _hp_floor))
CARPET = max(HP_F[1] - 0.285, FLOOR + 0.040)
HP_R = (HP_F[0] + 0.860, CARPET + 0.325)
SEAT_Z = 0.360                              # seat centreline half-spacing
SW_RAD, SW_TUBE, SW_RAKE = 0.183, 0.0195, 24.0
_swx, _swz = HP_F[0] - 0.300, RIGHT * SEAT_Z


# The windscreen pane is fitted with a PLANE rather than sampled locally: at the
# wheel's own z=-0.36 the pane only carries verts for x in [-1.211,-1.132] — it
# is a narrow basal strip on the driver's side — so a local disc sample either
# found nothing or walked out far enough to swallow the pane's BASE and read
# 100 mm too low. Plane fit over all 1,491 verts: rms 11.9 mm.
#
# ADAPTATION 2026-08-21 (six-gate merge).  THAT NARROW BASAL STRIP WAS THE
# DEFECT THE GLASS GATE FIXES, and the plane was only ever a workaround for it.
# Measured on both files at the steering wheel's own station (x -0.92, z -0.36,
# a 120 mm disc): the unrepaired pane has **0 vertices** there, and 0 at every
# station along the wheel's x range; the repaired pane has 417-461.  So the
# local sample is now available and is better evidence than a plane.
#
# It also has to be, because the plane no longer fits: over the FLAT 75 mm cowl
# strip the unrepaired "windscreen" was, a plane scores 11.6 mm rms; over the
# real raked screen the glass gate restores (0.1622 -> 0.9894 m2, genuinely
# doubly curved) the same fit scores 33.1 mm and tripped this assertion.  That
# is the model being wrong, not the car — so the assertion now guards the
# FALLBACK path only, and the local sample is preferred wherever the pane
# actually carries geometry.
_A = np.c_[_WS[:, 0], _WS[:, 2], np.ones(len(_WS))]
_CO, _, _, _ = np.linalg.lstsq(_A, _WS[:, 1], rcond=None)
_RMS = float(np.sqrt((((_A @ _CO) - _WS[:, 1]) ** 2).mean()))
_WS_R = 0.12                      # local sample radius, m
_WS_NMIN = 60                     # verts needed before a local sample is trusted


def _screen_y(x, z):
    m = (np.abs(_WS[:, 0] - x) < _WS_R) & (np.abs(_WS[:, 2] - z) < _WS_R)
    if int(m.sum()) >= _WS_NMIN:
        # p20 of y = the pane's UNDERSIDE locally, which is what a cabin part
        # has to clear.  A mean would sit inside the glass.
        return float(np.percentile(_WS[m, 1], 20))
    assert _RMS < 0.03, (
        f"windscreen pane has only {int(m.sum())} verts within {_WS_R*1000:.0f} mm "
        f"of (x={x:.3f}, z={z:.3f}) so the local sample is unusable, AND the "
        f"plane fallback is not planar enough to fit ({_RMS:.4f} m)")
    return float(_CO[0] * x + _CO[1] * z + _CO[2])


# The steering wheel is PLACED to clear the windscreen, not clamped into it.
# v3 put its rim 70 mm THROUGH the screen (hole_attrib attributed all 364
# GAINED silhouette pixels to Cabin_Wheel), and clamping the vertices merely
# flattened the rim — 178 of 480 verts hit the move cap. A component is moved
# rigidly or it is not moved.
_top_off = SW_RAD * np.cos(np.radians(SW_RAKE)) + SW_TUBE
_sy = _screen_y(_swx, _swz)
_swy = min(HP_F[1] + 0.300, _sy - 0.045 - _top_off)
SW_C = (_swx, _swy, _swz)
print(f"steering wheel: screen underside at x={_swx:.3f} is y={_sy:.3f}; "
      f"(plane fit rms {_RMS*1000:.1f} mm) wanted y={HP_F[1]+0.300:.3f}, PLACED y={_swy:.3f} "
      f"(rim top {_swy+_top_off:.3f}, clearance {_sy-(_swy+_top_off):.3f} m)")

parts = []


def add(name, mesh, mat):
    mesh = trimesh.Trimesh(np.asarray(mesh.vertices, np.float32),
                           np.asarray(mesh.faces, np.int64), process=False)
    parts.append((name, mesh, mat))


def rbox(ctr, ext, r=0.03, n=9):
    """Rounded box = convex hull of eight corner spheres. Watertight, cheap,
    and it shades smoothly, which is what makes a low-poly form read through
    tinted glass."""
    ctr = np.asarray(ctr, float)
    ext = np.asarray(ext, float)
    r = min(r, float(ext.min()) / 2.0 - 1e-4)
    h = ext / 2.0 - r
    pts = []
    sph = trimesh.creation.uv_sphere(radius=r, count=[n, n]).vertices
    for sx in (-1, 1):
        for sy in (-1, 1):
            for sz in (-1, 1):
                pts.append(sph + ctr + h * np.array([sx, sy, sz]))
    return trimesh.Trimesh(np.vstack(pts)).convex_hull


def rot(m, deg, axis, about):
    """NOTE the sign. A rotation about +Z by +theta moves a point ABOVE the
    pivot toward -x, and on this car -x is the NOSE — so +14 reclined every
    seat back FORWARD. Recline is NEGATIVE here. Caught when the front
    headrests swung to x=-0.46 and the windscreen clamp then crushed them by
    161 mm; the clamp was the symptom, the sign was the fault."""
    R = trimesh.transformations.rotation_matrix(np.radians(deg), axis, about)
    m = m.copy()
    m.apply_transform(R)
    return m


def loft(sections, close=True):
    """sections: list of (N,3) closed rings -> a tube, capped at both ends."""
    S = np.array(sections, float)
    K, N = S.shape[0], S.shape[1]
    V = S.reshape(-1, 3)
    F = []
    for k in range(K - 1):
        for i in range(N):
            j = (i + 1) % N
            a, b = k * N + i, k * N + j
            c, d = (k + 1) * N + i, (k + 1) * N + j
            F += [[a, b, d], [a, d, c]]
    if close:
        for k, base in ((0, 0), (K - 1, (K - 1) * N)):
            ctr = len(V)
            V = np.vstack([V, S[k].mean(0)])
            for i in range(N):
                j = (i + 1) % N
                if k == 0:
                    F.append([ctr, base + j, base + i])
                else:
                    F.append([ctr, base + i, base + j])
    return trimesh.Trimesh(V, np.array(F), process=False)


def slab(x0, x1, y_at_x, half_at_x, thick=0.022, nx=14, nz=10, taper=1.0):
    """A horizontal-ish panel of real thickness (floor, parcel shelf, headliner).
    Sheets are given thickness on purpose: a zero-thickness sheet disappears
    from one side unless the material is doubleSided, which is a shading trick,
    not geometry."""
    xs = np.linspace(x0, x1, nx)
    V, F = [], []
    for xi, x in enumerate(xs):
        hw = half_at_x(x) * taper
        y = y_at_x(x)
        for zi, z in enumerate(np.linspace(-hw, hw, nz)):
            V.append([x, y, z])
    for xi, x in enumerate(xs):
        hw = half_at_x(x) * taper
        y = y_at_x(x) - thick
        for zi, z in enumerate(np.linspace(-hw, hw, nz)):
            V.append([x, y, z])
    V = np.array(V)
    top = lambda i, j: i * nz + j
    bot = lambda i, j: nx * nz + i * nz + j
    for i in range(nx - 1):
        for j in range(nz - 1):
            F += [[top(i, j), top(i, j + 1), top(i + 1, j + 1)],
                  [top(i, j), top(i + 1, j + 1), top(i + 1, j)]]
            F += [[bot(i, j), bot(i + 1, j + 1), bot(i, j + 1)],
                  [bot(i, j), bot(i + 1, j), bot(i + 1, j + 1)]]
    for i in range(nx - 1):                       # side skirts
        for a, b in ((0, 0), (nz - 1, nz - 1)):
            F += [[top(i, a), top(i + 1, a), bot(i + 1, b)],
                  [top(i, a), bot(i + 1, b), bot(i, b)]]
    for j in range(nz - 1):                       # end caps
        F += [[top(0, j), bot(0, j), bot(0, j + 1)],
              [top(0, j), bot(0, j + 1), top(0, j + 1)]]
        F += [[top(nx - 1, j), bot(nx - 1, j + 1), bot(nx - 1, j)],
              [top(nx - 1, j), top(nx - 1, j + 1), bot(nx - 1, j + 1)]]
    return trimesh.Trimesh(V, np.array(F), process=False)


# ------------------------------------------------------------------ MATERIALS
MAT = {
    "Cabin_Trim":     ([26, 26, 29], 0.85),
    "Cabin_Fabric":   ([40, 40, 44], 0.95),
    "Cabin_Bolster":  ([31, 31, 35], 0.95),
    "Cabin_Rim":      ([17, 17, 19], 0.55),
    "Cabin_Liner":    ([50, 50, 52], 0.95),
    "Cabin_Carpet":   ([21, 21, 23], 1.00),
}
for k in MAT:
    assert not any(w in k.lower() for w in
                   ("glass", "window", "screen", "glas", "scheibe", "fenster",
                    "light")), k

# --------------------------------------------------------------------- FLOOR
add("Cabin_Floor",
    slab(-1.05, 1.50, lambda x: CARPET + 0.015,
         lambda x: min(0.60, interp(HALFW, 0.40)) - 0.06, thick=0.03, nx=18, nz=12),
    "Cabin_Carpet")
# transmission tunnel
add("Cabin_Tunnel", rbox([0.05, CARPET + 0.07, 0.0], [1.9, 0.13, 0.22], r=0.05),
    "Cabin_Carpet")

# ---------------------------------------------------------------------- DASH
# swept profile: meets the windscreen base at WSBASE, sweeps back and down to
# the fascia face, then in under the wheel. Profile is (x, y) in the car frame.
prof = np.array([
    (WSBASE[0] + 0.010, WSBASE[1] - 0.058),   # at the screen base, below the demister line
    (WSBASE[0] + 0.115, WSBASE[1] - 0.062),   # dash top, nearly level
    (WSBASE[0] + 0.215, WSBASE[1] - 0.082),   # top rolls over
    (WSBASE[0] + 0.258, WSBASE[1] - 0.115),   # face
    (WSBASE[0] + 0.250, WSBASE[1] - 0.240),
    (WSBASE[0] + 0.205, WSBASE[1] - 0.330),   # under-dash
    (WSBASE[0] + 0.090, WSBASE[1] - 0.355),
    (WSBASE[0] + 0.010, WSBASE[1] - 0.300),
    (WSBASE[0] - 0.020, WSBASE[1] - 0.150),
])
secs = []
# densify the profile so the dash top reads as a curve, not a chamfer
_t = np.linspace(0, 1, len(prof))
_ti = np.linspace(0, 1, 26)
prof = np.stack([np.interp(_ti, _t, prof[:, 0]), np.interp(_ti, _t, prof[:, 1])], 1)
for z, s in [(-0.63, 0.88), (-0.575, 0.96), (-0.45, 1.0), (-0.30, 1.0),
             (-0.15, 1.0), (0.0, 1.0), (0.15, 1.0), (0.30, 1.0), (0.45, 1.0),
             (0.575, 0.96), (0.63, 0.88)]:
    ctr = prof.mean(0)
    p = (prof - ctr) * np.array([1.0, s]) + ctr
    secs.append(np.stack([p[:, 0], p[:, 1], np.full(len(p), z)], 1))
add("Cabin_Dash", loft(secs), "Cabin_Trim")

# instrument binnacle, driver's side
add("Cabin_Binnacle",
    rot(rbox([WSBASE[0] + 0.245, WSBASE[1] - 0.075, RIGHT * SEAT_Z],
             [0.16, 0.13, 0.36], r=0.035), -14, [0, 0, 1],
        [WSBASE[0] + 0.245, WSBASE[1] - 0.075, RIGHT * SEAT_Z]),
    "Cabin_Trim")

# ------------------------------------------------------------ STEERING WHEEL
sw = trimesh.creation.torus(major_radius=SW_RAD, minor_radius=SW_TUBE,
                            major_sections=40, minor_sections=12)
sw.apply_transform(trimesh.transformations.rotation_matrix(
    np.radians(90), [0, 1, 0]))                       # into the x=const plane
sw.apply_transform(trimesh.transformations.rotation_matrix(
    np.radians(SW_RAKE), [0, 0, 1]))                  # column rake
sw.apply_translation(SW_C)
add("Cabin_Wheel", sw, "Cabin_Rim")
hub = trimesh.creation.cylinder(radius=0.062, height=0.052, sections=28)
hub.apply_transform(trimesh.transformations.rotation_matrix(
    np.radians(90), [0, 1, 0]))
hub.apply_transform(trimesh.transformations.rotation_matrix(
    np.radians(SW_RAKE), [0, 0, 1]))
hub.apply_translation(SW_C)
add("Cabin_Hub", hub, "Cabin_Trim")
spokes = []
for ang in (0, 120, 240):
    s = rbox([0, 0, 0], [0.020, 0.150, 0.030], r=0.008)
    s.apply_translation([0, 0.082, 0])
    s.apply_transform(trimesh.transformations.rotation_matrix(
        np.radians(ang + 90), [1, 0, 0]))
    spokes.append(s)
sp = trimesh.util.concatenate(spokes)
sp.apply_transform(trimesh.transformations.rotation_matrix(
    np.radians(SW_RAKE), [0, 0, 1]))
sp.apply_translation(SW_C)
add("Cabin_Spokes", sp, "Cabin_Rim")
col = trimesh.creation.cylinder(radius=0.036, height=0.20, sections=20)
col.apply_transform(trimesh.transformations.rotation_matrix(
    np.radians(90), [0, 1, 0]))
col.apply_transform(trimesh.transformations.rotation_matrix(
    np.radians(SW_RAKE), [0, 0, 1]))
col.apply_translation([SW_C[0] + 0.10, SW_C[1] + 0.045, SW_C[2]])
add("Cabin_Column", col, "Cabin_Trim")

# ------------------------------------------------------------------- CONSOLE
add("Cabin_Console",
    rbox([HP_F[0] + 0.06, CARPET + 0.15, 0.0], [0.86, 0.27, 0.235], r=0.045),
    "Cabin_Trim")

# --------------------------------------------------------------- FRONT SEATS
for tag, sgn in (("D", RIGHT), ("P", -RIGHT)):
    z = sgn * SEAT_Z
    add(f"Cabin_SeatF{tag}_Cush",
        rbox([HP_F[0] - 0.06, HP_F[1] - 0.045, z], [0.50, 0.115, 0.50], r=0.05),
        "Cabin_Fabric")
    br = rbox([HP_F[0] + 0.215, HP_F[1] + 0.245, z], [0.135, 0.60, 0.48], r=0.055)
    add(f"Cabin_SeatF{tag}_Back",
        rot(br, -14, [0, 0, 1], [HP_F[0] + 0.19, HP_F[1] + 0.02, z]),
        "Cabin_Fabric")
    # side bolsters, tonally separated so the backrest is not a flat slab
    for bs in (-1, 1):
        b = rbox([HP_F[0] + 0.195, HP_F[1] + 0.245, z + bs * 0.215],
                 [0.175, 0.55, 0.075], r=0.033)
        add(f"Cabin_SeatF{tag}_Bol{'A' if bs > 0 else 'B'}",
            rot(b, -14, [0, 0, 1], [HP_F[0] + 0.19, HP_F[1] + 0.02, z]),
            "Cabin_Bolster")
    hr = rbox([HP_F[0] + 0.30, HP_F[1] + 0.615, z], [0.105, 0.175, 0.235],
              r=0.045)
    add(f"Cabin_SeatF{tag}_Head",
        rot(hr, -14, [0, 0, 1], [HP_F[0] + 0.19, HP_F[1] + 0.02, z]),
        "Cabin_Bolster")

# ----------------------------------------------------------------- REAR SEAT
add("Cabin_BenchCush",
    rbox([HP_R[0] - 0.09, HP_R[1] - 0.05, 0.0], [0.50, 0.12, 1.20], r=0.05),
    "Cabin_Fabric")
bb = rbox([HP_R[0] + 0.235, HP_R[1] + 0.235, 0.0], [0.14, 0.58, 1.22], r=0.055)
add("Cabin_BenchBack", rot(bb, -18, [0, 0, 1], [HP_R[0] + 0.20, HP_R[1], 0.0]),
    "Cabin_Fabric")
for tag, z in (("R", RIGHT * 0.345), ("L", -RIGHT * 0.345)):
    hr = rbox([HP_R[0] + 0.325, HP_R[1] + 0.575, z], [0.10, 0.155, 0.225],
              r=0.042)
    add(f"Cabin_BenchHead_{tag}",
        rot(hr, -18, [0, 0, 1], [HP_R[0] + 0.20, HP_R[1], 0.0]), "Cabin_Bolster")

# --------------------------------------------------------- SHELF / BOOT / LID
add("Cabin_ParcelShelf",
    slab(HP_R[0] + 0.46, 1.44, lambda x: belt_at(x) + 0.040,
         lambda x: interp(HALFW, belt_at(x) + 0.02) - 0.085, thick=0.025, nx=10, nz=12),
    "Cabin_Trim")
add("Cabin_BootFloor",
    slab(HP_R[0] + 0.40, 1.86, lambda x: CARPET + 0.22,
         lambda x: interp(HALFW, 0.60) - 0.10, thick=0.03, nx=12, nz=12),
    "Cabin_Carpet")

# ------------------------------------------------------------------ DOORCARDS
# Built ON the body's own measured inner flank surface, inset 32 mm. v1 used a
# single half-width for the whole cabin and drove a grey slab through the rear
# quarter panel (11,357 px over 3 views).
DC_INSET = 0.032
for tag, sgn in (("R", RIGHT), ("L", -RIGHT)):
    xs = np.linspace(-1.02, 1.20, 26)
    ys = np.array([CARPET + 0.02, CARPET + 0.22,
                   belt_at(0.0) - 0.27, belt_at(0.0) - 0.22, belt_at(0.0) - 0.012])
    prof_in = np.array([0.028, 0.006, 0.000, 0.030, 0.055])   # extra inset (armrest)
    V, F = [], []
    for yi, (y, extra) in enumerate(zip(ys, prof_in)):
        zc = zin(sgn, xs, np.full_like(xs, y)) - DC_INSET - extra
        zc = np.maximum(zc, 0.10)
        for i, x in enumerate(xs):
            V.append([x, y, sgn * zc[i]])
    V = np.array(V)
    nx = len(xs)
    for yi in range(len(ys) - 1):
        for i in range(nx - 1):
            a, b = yi * nx + i, yi * nx + i + 1
            c, d = (yi + 1) * nx + i, (yi + 1) * nx + i + 1
            if sgn > 0:
                F += [[a, b, d], [a, d, c]]
            else:
                F += [[a, d, b], [a, c, d]]
    card = trimesh.Trimesh(V, np.array(F), process=False)
    card = trimesh.util.concatenate(
        [card, trimesh.Trimesh(V + np.array([0, 0, sgn * 0.026]),
                               np.array(F)[:, ::-1], process=False)])
    add(f"Cabin_DoorCard_{tag}", card, "Cabin_Trim")

# ----------------------------------------------------------------- HEADLINER
# Sampled on the measured roof underside (x, z) instead of a single half-width.
# v1's constant half-width pushed the liner's outer edge through the roof skin.
HL_DROP = 0.030
nxh, nzh = 26, 18
xs = np.linspace(-0.38, 1.50, nxh)
V, F = [], []
for i, x in enumerate(xs):
    hw = max(interp(HALFW, 1.35) - 0.07, 0.12)
    zs = np.linspace(-hw, hw, nzh)
    yy = ytop(np.full_like(zs, x), zs) - HL_DROP
    for j, z in enumerate(zs):
        V.append([x, yy[j], z])
for i, x in enumerate(xs):
    hw = max(interp(HALFW, 1.35) - 0.07, 0.12)
    zs = np.linspace(-hw, hw, nzh)
    yy = ytop(np.full_like(zs, x), zs) - HL_DROP - 0.022
    for j, z in enumerate(zs):
        V.append([x, yy[j], z])
V = np.array(V)
tp = lambda i, j: i * nzh + j
bt = lambda i, j: nxh * nzh + i * nzh + j
for i in range(nxh - 1):
    for j in range(nzh - 1):
        F += [[tp(i, j), tp(i, j + 1), tp(i + 1, j + 1)],
              [tp(i, j), tp(i + 1, j + 1), tp(i + 1, j)]]
        F += [[bt(i, j), bt(i + 1, j + 1), bt(i, j + 1)],
              [bt(i, j), bt(i + 1, j), bt(i + 1, j + 1)]]
for i in range(nxh - 1):
    for a in (0, nzh - 1):
        F += [[tp(i, a), tp(i + 1, a), bt(i + 1, a)],
              [tp(i, a), bt(i + 1, a), bt(i, a)]]
for j in range(nzh - 1):
    F += [[tp(0, j), bt(0, j), bt(0, j + 1)],
          [tp(0, j), bt(0, j + 1), tp(0, j + 1)]]
    F += [[tp(nxh - 1, j), bt(nxh - 1, j + 1), bt(nxh - 1, j)],
          [tp(nxh - 1, j), tp(nxh - 1, j + 1), bt(nxh - 1, j + 1)]]
add("Cabin_Headliner", trimesh.Trimesh(V, np.array(F), process=False),
    "Cabin_Liner")

# ------------------------------------------------------------------- EXPORT
out = {}
manifest = []
tot = 0
print(f"measured frame: FLOOR(pan) {FLOOR:.4f}  CARPET {CARPET:.4f}  "
      f"BELT(min) {BELT:.4f}  belt@driver {belt_at(_HPX):.4f}  WSBASE "
      f"({WSBASE[0]:.4f},{WSBASE[1]:.4f})")
print(f"H-point height: from floor {_hp_floor:.4f} | from beltline "
      f"{_hp_belt:.4f} | USED {HP_F[1]:.4f}")
print(f"front H-point {HP_F}  rear {HP_R}  wheel {tuple(round(v,3) for v in SW_C)}")
print(f"vehicle RIGHT = {RIGHT:+.0f} z  -> steering wheel at z={SW_C[2]:+.3f}\n")
for name, m, mat in parts:
    m.fix_normals()
    v = np.asarray(m.vertices, np.float32)
    f = np.asarray(m.faces, np.uint32)
    n = np.asarray(m.vertex_normals, np.float32)
    assert np.isfinite(v).all() and np.isfinite(n).all(), name
    ln = np.linalg.norm(n, axis=1)
    assert (ln > 0.5).all(), f"{name}: {int((ln<=0.5).sum())} zero-length normals"
    out[f"{name}__v"] = v
    out[f"{name}__f"] = f
    out[f"{name}__n"] = n
    col, rough = MAT[mat]
    manifest.append({"name": name, "material": mat, "color": col,
                     "rough": rough, "faces": int(len(f))})
    tot += len(f)
    print(f"  {name:24s} {len(f):6d} faces  {mat}")
mats = {k: {"color": v[0], "rough": v[1]} for k, v in MAT.items()}
out["manifest"] = np.frombuffer(json.dumps(
    {"parts": manifest, "materials": mats}).encode(), dtype=np.uint8)
np.savez(OUT, **out)
print(f"\n{len(parts)} parts, {tot} faces -> {OUT}")
