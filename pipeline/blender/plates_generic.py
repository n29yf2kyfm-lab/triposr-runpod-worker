"""plates_generic.py — bake UK front (white) + rear (yellow) number plates onto
ANY car GLB by geometry, no per-model tuning.

Front/rear detection: a car's roof mass sits rear-of-centre (long low bonnet up
front), so the FRONT is the length-end furthest from the roof-band centroid
(same heuristic as platform/undercarriage.py). Plates are textured quads built
directly with bmesh (explicit verts + UVs — the reliable approach the render
worker uses), placed against the bumper face at ~30% (front) / ~48% (rear) of
car height, sized from a real 520x111mm plate scaled to the car width.

Run: blender -b -noaudio --python plates_generic.py -- in.glb out.glb tex_dir
"""
import sys

import bpy
import bmesh
import numpy as np

argv = sys.argv[sys.argv.index("--") + 1:]
SRC, DST, TEX = argv[0], argv[1], argv[2]

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=SRC)

allv = []
for o in bpy.context.scene.objects:
    if o.type != "MESH" or not len(o.data.vertices):
        continue
    co = np.empty(len(o.data.vertices) * 3)
    o.data.vertices.foreach_get("co", co)
    M = np.array(o.matrix_world)
    allv.append(co.reshape(-1, 3) @ M[:3, :3].T + M[:3, 3])
V = np.vstack(allv)
lo, hi = V.min(0), V.max(0)
size = hi - lo
ctr = (lo + hi) / 2
# Length and width are the two HORIZONTAL axes; z (2) is always height in
# this file's z-up convention. The previous version chose length from {x, z}
# and width as the other of that pair - so a car whose length lies on x got
# WA=2, and since the plate builder writes p[WA] and p[2] into the same slot,
# every plate degenerated to a zero-width vertical line (found 2026-07-28 on
# bmw-320i-2023-v1; the quads were in the file, 0.0 units wide).
LA = 0 if size[0] >= size[1] else 1        # length: the longer horizontal axis
WA = 1 - LA                                # width: the other horizontal axis
gz = lo[2]
H = size[2]
# Robust width and centreline. The raw bounding box is the wrong reference for
# BOTH: on fiat-500l-v1 two stray objects of 24 and 27 verts set the whole box
# and inflated the width by 13%, and any asymmetric part drags the midpoint off
# the car's real centreline. Clipping the outer 0.1% drops the strays while
# keeping the body (measured 2026-07-30 across five cars).
w_all = V[:, WA]
w_lo, w_hi = np.percentile(w_all, 0.1), np.percentile(w_all, 99.9)
Wd = float(w_hi - w_lo)
CW = float((w_lo + w_hi) / 2)              # centreline, not ctr[WA]

roof = V[V[:, 2] > gz + 0.80 * H]
roof_l = roof[:, LA].mean() if len(roof) > 30 else ctr[LA]
front_end = lo[LA] if abs(lo[LA] - roof_l) > abs(hi[LA] - roof_l) else hi[LA]
# SALOON TRAP (found 2026-07-28 on bmw-320i-2023-v1): the roof-of-a-hatchback
# heuristic picks the wrong end on a three-box saloon whose roof centroid sits
# toward the nose. The result is a yellow plate on the kidney grille with
# mirrored text - both symptoms from the one wrong pick, verified by render.
# --front lo|hi overrides the guess when a human has looked.
if "--front" in argv:
    front_end = lo[LA] if argv[argv.index("--front") + 1] == "lo" else hi[LA]
rear_end = hi[LA] if front_end == lo[LA] else lo[LA]

# idempotent: a re-bake must strip the previous bake's plates first, or the
# new quads z-fight the old ones and the old orientation wins on camera
for _o in [o for o in bpy.context.scene.objects
           if o.name.startswith(("plate_front", "plate_rear"))]:
    bpy.data.objects.remove(_o, do_unlink=True)

def body_width_at(zc, half):
    """Width of the car at plate height. Sizing a plate off the FULL car width
    includes the door mirrors, which sit well outboard of the bumper: on
    lexus-lm-hybrid-w5-v1 that produced a plate 29% of an over-mirror width,
    visibly larger than the plate recess the model was built with, and on
    fiat-500l-v1 it reached 33% of body width. At bumper height the mirrors are
    out of the band, so this is the honest reference."""
    band = V[(V[:, 2] >= zc - half) & (V[:, 2] <= zc + half)]
    if len(band) < 200:
        return Wd
    b_lo, b_hi = np.percentile(band[:, WA], 0.5), np.percentile(band[:, WA], 99.5)
    bw = float(b_hi - b_lo)
    # never trust a band narrower than half the car - that means the slice
    # caught a spoiler or an air intake rather than the bumper
    return bw if bw > 0.5 * Wd else Wd


def plate_half_dims(zc):
    guess = (0.52 / 1.80 * Wd) / 2         # first pass, to give the band a height
    bw = body_width_at(zc, guess * 111 / 520)
    pw = (0.52 / 1.80 * bw) / 2            # half-width of a 520mm plate
    return pw, pw * 111 / 520


def bumper_face(end_val, zc, pw, ph):
    band = V[(V[:, 2] >= zc - ph) & (V[:, 2] <= zc + ph) &
             (np.abs(V[:, WA] - CW) < pw)]
    if len(band) < 5:
        return end_val
    return band[:, LA].max() if end_val == hi[LA] else band[:, LA].min()


def plate_mat(name, img):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    t = m.node_tree.nodes.new("ShaderNodeTexImage")
    t.image = bpy.data.images.load(img)
    m.node_tree.links.new(t.outputs["Color"], b.inputs["Base Color"])
    b.inputs["Roughness"].default_value = 0.35
    b.inputs["Metallic"].default_value = 0.0
    return m


def add_plate(name, img, end_val, zc):
    pw, ph = plate_half_dims(zc)
    outward = 1.0 if end_val == hi[LA] else -1.0
    Lc = bumper_face(end_val, zc, pw, ph) + outward * size[LA] * 0.004
    Wc = CW
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()

    def V4(dw, dz):
        p = [0.0, 0.0, 0.0]
        p[LA] = Lc
        p[WA] = Wc + dw
        p[2] = zc + dz
        return bm.verts.new(p)
    vs = [V4(-pw, -ph), V4(-pw, ph), V4(pw, ph), V4(pw, -ph)]
    f = bm.faces.new(vs)
    uvl = bm.loops.layers.uv.new("UVMap")
    uvs = [(1, 0), (1, 1), (0, 1), (0, 0)] if outward > 0 \
        else [(0, 0), (0, 1), (1, 1), (1, 0)]
    for lp, uv in zip(f.loops, uvs):
        lp[uvl].uv = uv
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(ob)
    me.materials.append(plate_mat(name + "_m", img))


add_plate("plate_front", f"{TEX}/uk_plate_front.png", front_end, gz + 0.30 * H)
add_plate("plate_rear", f"{TEX}/uk_plate_rear.png", rear_end, gz + 0.48 * H)

bpy.ops.object.select_all(action="SELECT")
bpy.ops.export_scene.gltf(filepath=DST, export_format="GLB", export_apply=True,
                          export_yup=True, export_normals=True,
                          export_materials="EXPORT")
print(f"PLATES_GENERIC_OK front_end={front_end:.2f} rear_end={rear_end:.2f} LA={LA}")
