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

parts = []


def box(name, x0, x1, y0, y1, z0, z1, col, rough=0.9):
    b = trimesh.creation.box(extents=[x1 - x0, y1 - y0, z1 - z0])
    b.apply_translation([(x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2])
    parts.append((name, b, col, rough))


def yf(f):
    return GY + f * H


# cabin floor
box("Int_Floor", -1.15, 1.05, yf(0.19), yf(0.225), -0.62, 0.62, [20, 20, 22])
# dashboard: full-width block with a raked top
dash = trimesh.creation.box(extents=[0.42, 0.30, 1.30])
dash.apply_translation([0.94, yf(0.47), 0.0])
parts.append(("Int_Dash", dash, [24, 24, 27], 0.85))
# centre console
box("Int_Console", -0.10, 0.78, yf(0.225), yf(0.38), -0.11, 0.11, [27, 27, 30])
# front seats (cushion + backrest + headrest), both sides
for z in (0.36, -0.36):
    tag = "R" if z > 0 else "L"
    box(f"Int_SeatF{tag}_C", -0.12, 0.38, yf(0.30), yf(0.40), z - 0.235, z + 0.235, [30, 30, 33])
    br = trimesh.creation.box(extents=[0.12, 0.46, 0.46])
    br.apply_transform(trimesh.transformations.rotation_matrix(np.radians(-12), [0, 0, 1]))
    br.apply_translation([-0.16, yf(0.55), z])
    parts.append((f"Int_SeatF{tag}_B", br, [30, 30, 33], 0.9))
    box(f"Int_SeatF{tag}_H", -0.28, -0.16, yf(0.70), yf(0.79), z - 0.11, z + 0.11, [26, 26, 29])
# rear bench + backrest
box("Int_BenchC", -0.95, -0.50, yf(0.30), yf(0.40), -0.60, 0.60, [30, 30, 33])
br = trimesh.creation.box(extents=[0.12, 0.52, 1.20])
br.apply_transform(trimesh.transformations.rotation_matrix(np.radians(-15), [0, 0, 1]))
br.apply_translation([-1.02, yf(0.56), 0.0])
parts.append(("Int_BenchB", br, [30, 30, 33], 0.9))
# steering wheel — RHD (UK): right side of the car is +z (forward x cross up y)
sw = trimesh.creation.torus(major_radius=0.185, minor_radius=0.021)
sw.apply_transform(trimesh.transformations.rotation_matrix(np.radians(90 - 24), [0, 0, 1]))
sw.apply_translation([0.55, yf(0.50), 0.36])
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
