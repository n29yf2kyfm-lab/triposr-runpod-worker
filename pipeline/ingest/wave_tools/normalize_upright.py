"""Canonicalize a car GLB: bake all transforms into vertices, then apply the
same conservative upright rescue as the render worker (fire ONLY when the
vertical extent is clearly the largest - car standing on its nose/tail), plus
the bottom-wider 180-degree disambiguation. Export plain (no draco - the
plates step re-imports this immediately).

blender -b -noaudio --python normalize_upright.py -- in.glb out.glb
"""
import bpy, math, sys
import numpy as np
from mathutils import Matrix, Vector

inp, outp = sys.argv[-2], sys.argv[-1]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=inp)
dg = bpy.context.evaluated_depsgraph_get()
baked = []
for o in list(bpy.context.scene.objects):
    if o.type == 'MESH':
        ev = o.evaluated_get(dg)
        me = bpy.data.meshes.new_from_object(ev)
        me.transform(o.matrix_world)
        no = bpy.data.objects.new(o.name + "_n", me)
        bpy.context.scene.collection.objects.link(no)
        baked.append(no)
for o in list(bpy.context.scene.objects):
    if o not in baked:
        bpy.data.objects.remove(o, do_unlink=True)
for a in list(bpy.data.actions):
    bpy.data.actions.remove(a)

def spans():
    lo = np.array([1e9] * 3); hi = np.array([-1e9] * 3)
    for o in bpy.context.scene.objects:
        vs = np.array([v.co[:] for v in o.data.vertices])
        if len(vs):
            lo = np.minimum(lo, vs.min(0)); hi = np.maximum(hi, vs.max(0))
    return lo, hi

def rot_all(axis, deg):
    R = Matrix.Rotation(math.radians(deg), 4, axis)
    for o in bpy.context.scene.objects:
        o.data.transform(R)

lo, hi = spans()
ext = hi - lo
rotated = False
if ext[2] > 1.25 * max(ext[0], ext[1]):
    rot_all('X', 90)
    rotated = True
    lo, hi = spans(); ext = hi - lo
    if int(np.argmin(ext)) != 2:
        rot_all('Y', 90)
        lo, hi = spans(); ext = hi - lo

if rotated:
    # 180 ambiguity: car is wider at the bottom (wheels/body) than the top
    pts = []
    for o in bpy.context.scene.objects:
        vs = np.array([v.co[:] for v in o.data.vertices])
        if len(vs):
            pts.append(vs)
        if sum(len(p) for p in pts) > 60000:
            break
    P = np.vstack(pts)
    zlo, zhi = P[:, 2].min(), P[:, 2].max()
    span = (zhi - zlo) or 1.0
    def wid(a, b):
        sel = P[(P[:, 2] >= zlo + a * span) & (P[:, 2] <= zlo + b * span)]
        if len(sel) == 0:
            return 0.0
        return max(sel[:, 0].max() - sel[:, 0].min(), sel[:, 1].max() - sel[:, 1].min())
    if wid(0.66, 1.0) > 1.15 * wid(0.0, 0.34):
        axis = 'X' if ext[0] >= ext[1] else 'Y'
        rot_all(axis, 180)

print("NORMALIZE_OK rotated=", rotated)
bpy.ops.export_scene.gltf(filepath=outp, export_format='GLB')
