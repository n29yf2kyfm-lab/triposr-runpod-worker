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
LA = 0 if size[0] >= size[2] else 2       # length axis (x or z; Blender z-up)
WA = 2 if LA == 0 else 0                   # width axis
gz = lo[2]
H = size[2]
Wd = size[WA]

roof = V[V[:, 2] > gz + 0.80 * H]
roof_l = roof[:, LA].mean() if len(roof) > 30 else ctr[LA]
front_end = lo[LA] if abs(lo[LA] - roof_l) > abs(hi[LA] - roof_l) else hi[LA]
rear_end = hi[LA] if front_end == lo[LA] else lo[LA]

pw = (0.52 / 1.80 * Wd) / 2               # half-width of a 520mm plate
ph = (pw * 111 / 520)


def bumper_face(end_val, zc):
    band = V[(V[:, 2] >= zc - ph) & (V[:, 2] <= zc + ph) &
             (np.abs(V[:, WA] - ctr[WA]) < Wd * 0.28)]
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
    outward = 1.0 if end_val == hi[LA] else -1.0
    Lc = bumper_face(end_val, zc) + outward * size[LA] * 0.004
    Wc = ctr[WA]
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
