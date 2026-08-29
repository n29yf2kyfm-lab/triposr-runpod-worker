#!/usr/bin/env python3
"""interior_kit.py — simplified dark interior (Phase 5 of the brief).

Parametric cabin furniture so glass shows believable depth and parallax
instead of a flat dark backdrop: dashboard, front seats + headrests, rear
bench, centre console, steering wheel (RHD — UK car), cabin floor. All
positioned as fractions of the car's own measured frame, all dark matte
with slight tonal separation so shapes read through tinted glass.

Run: python3 interior_kit.py <car.glb> <out.npz>
"""
import json
import sys
import numpy as np
import trimesh

CAR, OUT = sys.argv[1], sys.argv[2]

sc = trimesh.load(CAR, force="scene")
# body node by NAME first, then by MATERIAL name, then the largest mesh —
# hybrid/labelled cars name the node 'body' with material 'carpaint'
_cands = [g for n, g in sc.geometry.items() if "carpaint" in n or n == "body"]
if not _cands:
    _cands = [g for g in sc.geometry.values()
              if getattr(getattr(g.visual, "material", None), "name", "")
              == "carpaint"]
if not _cands:
    _cands = [max(sc.geometry.values(), key=lambda g: len(g.faces))]
cp = _cands[0]
v = cp.vertices
GY = float(v[:, 1].min())
H = float(np.percentile(v[:, 1], 99.8)) - GY
HW = float(np.percentile(np.abs(v[:, 2]), 99.7))
XMIN, XMAX = float(v[:, 0].min()), float(v[:, 0].max())
print(f"frame: H {H:.3f} halfW {HW:.3f} x [{XMIN:.2f},{XMAX:.2f}]")

# THE BELTLINE IS THE ONLY DIMENSION THAT DECIDES WHAT A VIEWER SEES, and
# until now nothing measured it. Everything was placed as a fraction of car
# HEIGHT, so on this car the whole cabin landed below the side glass: seat
# cushions, bolsters, console, floor and rear bench were ENTIRELY under the
# door line, the dash cleared it by 5 mm and the steering wheel by 84 mm of
# its 370 mm. The only thing a viewer could actually see was a pair of
# headrests, which is exactly what the render showed — a floating headrest
# over fog. Measure the side glazing and hang the parts that must READ off
# that instead.
BELT, RAIL = None, None
_gl = [g for n, g in sc.geometry.items()
       if n == "glass" or getattr(getattr(g.visual, "material", None),
                                  "name", "") == "glass"]
if _gl:
    _g = _gl[0]
    _c, _n = _g.triangles_center, _g.face_normals
    _side = (np.abs(_n[:, 2]) > 0.6) & (np.abs(_c[:, 2]) > 0.55 * HW)
    if _side.sum() > 200:
        _y = _c[_side][:, 1]
        BELT = float(np.percentile(_y, 2))
        RAIL = float(np.percentile(_y, 98))
if BELT is None:                       # no glazing to measure — fall back
    BELT, RAIL = GY + 0.64 * H, GY + 0.87 * H
    print("NOTE: no side glazing found; beltline ESTIMATED from car height")
print(f"beltline {BELT:.3f}  roof rail {RAIL:.3f}  "
      f"visible band {1000*(RAIL-BELT):.0f} mm")

# THE SCUTTLE IS THE OTHER DIMENSION NOTHING MEASURED. The beltline fix
# stopped the cabin sinking under the door line; x placement was still
# hardcoded constants calibrated on one car. On the white Golf the dash
# front edge landed at x 1.140 against a windscreen base at x 0.831 - it
# protruded 310 mm THROUGH THE BONNET and rendered as a black slab lying on
# the paint, which is what the owner saw. Same shape of error as the
# beltline, one axis over: the dimension that decides placement was never
# measured. A dashboard's front edge meets the base of the windscreen, so
# measure that and hang the dash off it.
SCUT = None
if _gl:
    _nc = _gl[0].triangles_center
    _nose = _nc[_nc[:, 0] > 0.0]
    if len(_nose) > 200:
        _lo = np.percentile(_nose[:, 1], 3)
        SCUT = float(_nose[_nose[:, 1] <= _lo][:, 0].mean())
if SCUT is None:
    SCUT = XMIN + 0.72 * (XMAX - XMIN)
    print("NOTE: no glazing to find the scuttle; ESTIMATED from length")
print(f"scuttle (windscreen base) x {SCUT:.3f}")

parts = []


def box(name, x0, x1, y0, y1, z0, z1, col, rough=0.9):
    b = trimesh.creation.box(extents=[x1 - x0, y1 - y0, z1 - z0])
    b.apply_translation([(x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2])
    parts.append((name, b, col, rough))


def yf(f):
    return GY + f * H


def rbox(name, x0, x1, y0, y1, z0, z1, col, rough=0.9, soft=10):
    """A ROUNDED box. Upholstery has no sharp arrises, and the first pass
    built every seat as a hard-edged slab — through the glass that read as
    packing crates rather than a cabin, which is most of why the owner said
    the interior looked wrong even after the lean and the wheel axis were
    fixed. Subdivide, Taubin-smooth (volume preserving, so corners round
    without the part collapsing), then rescale back to the asked-for extents
    because smoothing shrinks it."""
    ext = np.array([x1 - x0, y1 - y0, z1 - z0], float)
    b = trimesh.creation.box(extents=ext)
    for _ in range(3):
        b = b.subdivide()
    trimesh.smoothing.filter_taubin(b, lamb=0.6, nu=-0.62, iterations=soft)
    cur = b.extents.copy()
    cur[cur < 1e-9] = 1.0
    b.apply_scale(ext / cur)
    b.apply_translation(np.array([(x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2])
                        - b.bounds.mean(axis=0))
    parts.append((name, b, col, rough))
    return b


# cabin floor
box("Int_Floor", -1.15, 1.05, yf(0.19), yf(0.225), -0.62, 0.62, [20, 20, 22])
# dashboard: full-width block with a raked top
dash = trimesh.creation.box(extents=[0.42, 0.30, 1.30])
# front face AT the scuttle, body extending rearward — never through the
# bonnet. Top still at the beltline.
dash.apply_translation([SCUT - 0.21, BELT + 0.015 - 0.15, 0.0])
parts.append(("Int_Dash", dash, [24, 24, 27], 0.85))
# centre console
box("Int_Console", -0.10, 0.78, yf(0.225), yf(0.38), -0.11, 0.11, [27, 27, 30])
# front seats (cushion + backrest + headrest), both sides
for z in (0.36, -0.36):
    tag = "R" if z > 0 else "L"
    rbox(f"Int_SeatF{tag}_C", -0.12, 0.38, yf(0.30), yf(0.40),
         z - 0.235, z + 0.235, [30, 30, 33])
    # SIDE BOLSTERS. A flat cushion has no shoulder, so the seat reads as a
    # plank end-on; two raised rails give it the shape the eye expects.
    for sgn in (1, -1):
        rbox(f"Int_SeatF{tag}_Bol{'R' if sgn > 0 else 'L'}",
             -0.10, 0.34, yf(0.335), yf(0.425),
             z + sgn * 0.185, z + sgn * 0.245, [27, 27, 30], soft=8)
    br = trimesh.creation.box(extents=[0.12, 0.46, 0.46])
    for _ in range(3):
        br = br.subdivide()
    trimesh.smoothing.filter_taubin(br, lamb=0.6, nu=-0.62, iterations=10)
    # SIGN: +12 leans the TOP of the backrest toward -x (the tail), which is
    # how a seat reclines. -12 tipped every seat FORWARD, and the owner spotted
    # it through the glass before any measurement did ("interior build wrong,
    # it's backward"). Verified after the fix by comparing the mean x of the
    # backrest's top half against its bottom half.
    br.apply_transform(trimesh.transformations.rotation_matrix(np.radians(12), [0, 0, 1]))
    br.apply_translation([-0.16, BELT + 0.12 - 0.23, z])   # top at BELT+120mm
    parts.append((f"Int_SeatF{tag}_B", br, [30, 30, 33], 0.9))
    rbox(f"Int_SeatF{tag}_H", -0.30, -0.16, BELT + 0.13, BELT + 0.29,
         z - 0.125, z + 0.125, [26, 26, 29], soft=12)
# rear bench + backrest
rbox("Int_BenchC", -0.95, -0.50, yf(0.30), yf(0.40), -0.60, 0.60, [30, 30, 33])
br = trimesh.creation.box(extents=[0.12, 0.52, 1.20])
for _ in range(3):
    br = br.subdivide()
trimesh.smoothing.filter_taubin(br, lamb=0.6, nu=-0.62, iterations=10)
br.apply_transform(trimesh.transformations.rotation_matrix(np.radians(15), [0, 0, 1]))
br.apply_translation([-1.02, BELT + 0.10 - 0.26, 0.0])
parts.append(("Int_BenchB", br, [30, 30, 33], 0.9))
# REAR HEADRESTS were missing entirely. They sit squarely in the visible
# band and are one of the most recognisable things in a cabin seen from
# outside, so their absence cost more than their size suggests.
for z in (0.34, -0.34):
    rbox(f"Int_HeadR{'R' if z > 0 else 'L'}", -1.14, -1.01,
         BELT + 0.11, BELT + 0.25, z - 0.115, z + 0.115, [26, 26, 29], soft=12)
# PARCEL SHELF — a strong horizontal that reads through the rear quarter
# glass and the backlight, and gives the tail some depth.
# SHRUNK AND ROUNDED 2026-08-29. The first shelf was 470 x 1120 mm with
# sharp arrises and it dominated the back glass — measured in the render it
# came out at mean luma 142 against the tailgate's 83, i.e. the brightest
# thing in the tail and brighter than the bodywork. A real parcel shelf is
# dark carpet you can barely pick out through a tinted screen.
rbox("Int_Shelf", -1.42, -1.10, BELT + 0.010, BELT + 0.038, -0.46, 0.46,
     [12, 12, 14], soft=6)
# steering wheel — RHD (UK): right side of the car is +z (forward x cross up y)
# trimesh's torus lies in the XY plane with its AXIS along +Z. Here +Z is
# LATERAL, so the wheel came out edge-on to the driver — a 409x412mm disc
# spanning length and height with only 42mm of width, mounted like a road
# wheel. A steering wheel's disc spans LATERAL and UP; its axis points
# fore-aft toward the driver, raked back ~24 degrees from vertical.
# Rotating about Z alone can never fix that: it spins the torus in its own
# plane and leaves the axis where it was. Swing the axis onto X first.
sw = trimesh.creation.torus(major_radius=0.185, minor_radius=0.021)
sw.apply_transform(trimesh.transformations.rotation_matrix(np.radians(90), [0, 1, 0]))
sw.apply_transform(trimesh.transformations.rotation_matrix(np.radians(24), [0, 0, 1]))
sw.apply_translation([SCUT - 0.50, BELT - 0.04, 0.36])  # rim top ~BELT+145mm
parts.append(("Int_Wheel", sw, [16, 16, 18], 0.6))

out = {}
manifest = []
for name, m, col, rough in parts:
    out[f"{name}_v"] = m.vertices
    out[f"{name}_f"] = m.faces
    manifest.append({"name": name, "v": f"{name}_v", "f": f"{name}_f",
                     "color": col, "metallic": 0.0, "rough": rough})
    print(f"  {name}: {len(m.faces)} faces")
out["manifest"] = np.frombuffer(json.dumps(manifest).encode(), dtype=np.uint8)
np.savez(OUT, **out)
print("wrote", OUT, f"({len(parts)} parts)")
