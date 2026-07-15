"""Replace AI-generated wheel blobs with clean parametric wheels.

1. Detect axles + wheel radius from the mesh (same histogram method).
2. Delete generated wheel faces (cylinder around each axle, outboard only).
3. Build one parametric wheel: tyre torus + rim disc + 10 spokes + hub,
   instanced at all four corners; dark arch-liner disc closes the shell hole.
Materials: Wheel_Tyre (matte near-black), Wheel_Rim (machined silver),
Wheel_Dark (arch liner) — names the render worker excludes from recolour.
"""
import bpy, bmesh, math, sys
import numpy as np
from mathutils import Vector, Matrix

argv = sys.argv[sys.argv.index("--") + 1:]
SRC, DST = argv[0], argv[1]

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=SRC)
obj = [o for o in bpy.context.scene.objects if o.type == "MESH"][0]
me = obj.data
vs = np.array([v.co[:] for v in me.vertices])
lo, hi = vs.min(0), vs.max(0)
W, L, H = hi - lo
cx = (lo[0] + hi[0]) / 2

band = vs[vs[:, 2] < lo[2] + 0.22 * H]
histo, edges = np.histogram(band[:, 1], bins=40)
mid = (lo[1] + hi[1]) / 2
front = float(edges[np.argmax(histo * (edges[:-1] < mid))])
rear = float(edges[np.argmax(histo * (edges[:-1] >= mid))])
R = 0.085 * L
czw = lo[2] + R
wheel_top = lo[2] + 2.05 * R

# outer x of the existing wheels (per side) for placement
wheelverts = vs[(vs[:, 2] < wheel_top) &
                (np.minimum(np.abs(vs[:, 1] - front), np.abs(vs[:, 1] - rear)) < R * 1.2)]
x_out = float(np.percentile(np.abs(wheelverts[:, 0] - cx), 98))
print(f"axles {front:.3f}/{rear:.3f} R={R:.3f} outer-x={x_out:.3f}")

# ---- delete generated wheel faces -------------------------------------------
bm = bmesh.new(); bm.from_mesh(me)
doomed = []
for f in bm.faces:
    c = f.calc_center_median()
    if c.z > wheel_top or abs(c.x - cx) < 0.40 * (W / 2):
        continue
    for ay in (front, rear):
        if (c.y - ay) ** 2 + (c.z - czw) ** 2 < (R * 1.10) ** 2:
            doomed.append(f); break
bmesh.ops.delete(bm, geom=doomed, context="FACES")
bm.to_mesh(me); bm.free()
print("deleted wheel faces:", len(doomed))

def mat(name, rgba, rough, metal=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = rgba
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    return m

m_tyre = mat("Wheel_Tyre", (0.018, 0.018, 0.020, 1), 0.9)
m_rim = mat("Wheel_Rim", (0.62, 0.63, 0.66, 1), 0.28, 1.0)
m_dark = mat("Wheel_Dark", (0.02, 0.02, 0.022, 1), 0.8)

def build_wheel(name, ay, side):
    parts = []
    xw = cx + side * (x_out - 0.02 * R)
    rot = Matrix.Rotation(math.radians(90), 4, 'Y')     # cylinder axis -> x
    # tyre
    bpy.ops.mesh.primitive_torus_add(major_radius=R * 0.80, minor_radius=R * 0.20,
        major_segments=48, minor_segments=16, location=(xw - side * R * 0.12, ay, czw))
    t = bpy.context.object; t.rotation_euler = (0, math.radians(90), 0)
    t.data.materials.append(m_tyre); parts.append(t)
    # rim barrel + face
    bpy.ops.mesh.primitive_cylinder_add(radius=R * 0.60, depth=R * 0.22, vertices=48,
        location=(xw - side * R * 0.12, ay, czw))
    rimc = bpy.context.object; rimc.rotation_euler = (0, math.radians(90), 0)
    rimc.data.materials.append(m_dark); parts.append(rimc)
    # spokes: 10 thin boxes radiating on the outer face
    for k in range(10):
        a = k * math.pi / 5
        bpy.ops.mesh.primitive_cube_add(size=1, location=(
            xw, ay + math.cos(a) * R * 0.33, czw + math.sin(a) * R * 0.33))
        s = bpy.context.object
        s.scale = (R * 0.035, R * 0.052, R * 0.30)
        s.rotation_euler = (math.radians(90) + a, 0, math.radians(90))
        s.data.materials.append(m_rim); parts.append(s)
    # hub cap
    bpy.ops.mesh.primitive_cylinder_add(radius=R * 0.14, depth=R * 0.06, vertices=24,
        location=(xw + side * R * 0.02, ay, czw))
    h = bpy.context.object; h.rotation_euler = (0, math.radians(90), 0)
    h.data.materials.append(m_rim); parts.append(h)
    # arch liner disc behind the wheel closes the shell hole
    bpy.ops.mesh.primitive_cylinder_add(radius=R * 1.02, depth=R * 0.05, vertices=40,
        location=(cx + side * 0.42 * (W / 2), ay, czw))
    d = bpy.context.object; d.rotation_euler = (0, math.radians(90), 0)
    d.data.materials.append(m_dark); parts.append(d)
    for p in parts:
        for poly in p.data.polygons: poly.use_smooth = True
    return parts

for side in (-1, 1):
    for ay in (front, rear):
        build_wheel(f"wheel_{side}_{ay:.1f}", ay, side)

bpy.ops.object.select_all(action="SELECT")
bpy.ops.export_scene.gltf(filepath=DST, export_format="GLB", export_apply=True,
                          export_yup=True, export_normals=True, export_materials="EXPORT")
print("WHEELS_OK", DST)
