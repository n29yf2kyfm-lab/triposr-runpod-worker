#!/usr/bin/env python3
"""r1_ground.py — REPAIR 1: level the car and put its tyres on the ground.

ROOT CAUSE, measured in Stage 1, not inferred. The front tyres sit at world
z_min +193.8 mm and the rear at +11.5 mm, over a 2.540 m wheelbase: the car is
pitched NOSE-UP 4.11 deg. The whole-model z_min reads +0.3 mm because the
interior dips lowest, which is exactly why a bounding-box grounding test passes
this car -- the failure mode this project has already paid for once.

The fix is a rigid transform of the whole scene: rotate about Y until the two
axle contact points are level, then drop so the lowest TYRE touches z=0. Nothing
is deformed, so no other defect can be introduced by it.

Verification is built in: front and rear tyre z_min must both land within TOL of
zero, and the transform must be proven RIGID.

The first rigidity test compared axis-aligned bounding-box extents and reported
FAIL at 9.2 mm on X and 12.2 mm on Z. That test was wrong, not the transform: an
AABB is not rotation-invariant, so rotating a car 4.3 deg necessarily changes its
axis-aligned extents even though nothing moved relative to anything else. The
test now compares TOTAL TRIANGLE AREA, which is genuinely invariant under
rotation and translation -- if that shifts, the transform really did deform
something.

Run: blender -b --python r1_ground.py -- in.glb out.glb report.json
"""
import json
import math
import sys

import bpy
import numpy as np

argv = sys.argv[sys.argv.index("--") + 1:]
SRC, DST, REPORT = argv[0], argv[1], argv[2]
TOL_MM = 2.0
TYRE = "Tyre_Rubber"

bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
bpy.ops.import_scene.gltf(filepath=SRC)


def world_points():
    out = {}
    for o in sc.objects:
        if o.type != "MESH":
            continue
        me = o.to_mesh()
        M = np.array(o.matrix_world.to_4x4())
        V = np.array([v.co[:] for v in me.vertices], dtype=float)
        if len(V):
            out[o.name] = V @ M[:3, :3].T + M[:3, 3]
        o.to_mesh_clear()
    return out


def axle_contacts(pts):
    """Lowest tyre point in each half, and the x it sits at."""
    P = pts[TYRE]
    mid = (P[:, 0].min() + P[:, 0].max()) / 2
    res = {}
    for nm, sel in (("front", P[:, 0] < mid), ("rear", P[:, 0] >= mid)):
        Q = P[sel]
        i = int(np.argmin(Q[:, 2]))
        res[nm] = (float(Q[i, 0]), float(Q[i, 2]))
    return res


pts0 = world_points()
allP0 = np.vstack(list(pts0.values()))
size0 = allP0.max(0) - allP0.min(0)


def total_area():
    """Rotation- and translation-invariant. The honest rigidity witness."""
    tot = 0.0
    for o in sc.objects:
        if o.type != "MESH":
            continue
        me = o.to_mesh()
        M = o.matrix_world
        for poly in me.polygons:
            vs = [M @ me.vertices[i].co for i in poly.vertices]
            for t in range(1, len(vs) - 1):
                a = vs[t] - vs[0]
                b = vs[t + 1] - vs[0]
                tot += a.cross(b).length * 0.5
        o.to_mesh_clear()
    return tot


area0 = total_area()
c0 = axle_contacts(pts0)
fx, fz = c0["front"]
rx, rz = c0["rear"]
wb = abs(rx - fx)
pitch = math.atan2(fz - rz, rx - fx)      # >0 means the FRONT is high
print(f"R1_BEFORE front=({fx:+.3f}, {fz*1000:+.1f}mm) rear=({rx:+.3f}, {rz*1000:+.1f}mm) "
      f"wheelbase={wb:.3f}m pitch={math.degrees(pitch):+.3f}deg")

# rotate about Y about the world origin, then drop. Applied to every ROOT node,
# so parented children follow and nothing is deformed.
R = np.array([[math.cos(-pitch), 0, math.sin(-pitch)],
              [0, 1, 0],
              [-math.sin(-pitch), 0, math.cos(-pitch)]])
Rm = bpy.data.objects.new("tmp", None)          # reuse Blender maths, not mine
bpy.data.objects.remove(Rm, do_unlink=True)
import mathutils
Rot = mathutils.Matrix.Rotation(-pitch, 4, "Y")
for o in sc.objects:
    if o.parent is None:
        o.matrix_world = Rot @ o.matrix_world

bpy.context.view_layer.update()
pts1 = world_points()
c1 = axle_contacts(pts1)
drop = min(c1["front"][1], c1["rear"][1])
T = mathutils.Matrix.Translation((0, 0, -drop))
for o in sc.objects:
    if o.parent is None:
        o.matrix_world = T @ o.matrix_world
bpy.context.view_layer.update()

pts2 = world_points()
c2 = axle_contacts(pts2)
allP2 = np.vstack(list(pts2.values()))
size2 = allP2.max(0) - allP2.min(0)
fz2 = c2["front"][1] * 1000
rz2 = c2["rear"][1] * 1000
size_delta = np.abs(size2 - size0) * 1000
area2 = total_area()
area_ppm = abs(area2 - area0) / area0 * 1e6 if area0 else 0.0
print(f"R1_AFTER  front={fz2:+.2f}mm rear={rz2:+.2f}mm  "
      f"residual_pitch={math.degrees(math.atan2(c2['front'][1]-c2['rear'][1], wb)):+.4f}deg")
print(f"R1_RIGID  total area {area0:.6f} -> {area2:.6f} m2  delta = {area_ppm:.3f} ppm")
print(f"R1_AABB   aabb extents moved {size_delta[0]:.3f}, {size_delta[1]:.3f}, "
      f"{size_delta[2]:.3f} mm — EXPECTED under rotation, not a defect")

bpy.ops.export_scene.gltf(filepath=DST, export_format="GLB", export_yup=True)
print("R1_EXPORTED", DST)

ok_ground = abs(fz2) <= TOL_MM and abs(rz2) <= TOL_MM
ok_rigid = area_ppm <= 50.0        # 50 ppm of surface area
json.dump({
    "repair": "R1 ground and level",
    "root_cause": "scene pitched nose-up; front tyres airborne",
    "before": {"front_tyre_zmin_mm": round(fz * 1000, 2),
               "rear_tyre_zmin_mm": round(rz * 1000, 2),
               "wheelbase_m": round(wb, 4),
               "pitch_deg": round(math.degrees(pitch), 4)},
    "after": {"front_tyre_zmin_mm": round(fz2, 3),
              "rear_tyre_zmin_mm": round(rz2, 3)},
    "total_area_m2_before": round(area0, 6),
    "total_area_m2_after": round(area2, 6),
    "area_delta_ppm": round(area_ppm, 4),
    "aabb_extent_change_mm": [round(float(x), 4) for x in size_delta],
    "aabb_note": "AABB is not rotation-invariant; extent change is expected",
    "tolerance_mm": TOL_MM,
    "PASS_grounded": ok_ground,
    "PASS_rigid": ok_rigid,
    "RESULT": "PASS" if (ok_ground and ok_rigid) else "FAIL",
}, open(REPORT, "w"), indent=2)
print("R1_RESULT", "PASS" if (ok_ground and ok_rigid) else "FAIL")
