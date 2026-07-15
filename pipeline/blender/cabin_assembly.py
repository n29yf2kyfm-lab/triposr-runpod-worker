"""cabin_assembly.py — assembly stage for generated car shells.

Upgrades a fused AI mesh toward the library gates the honest way games do:
  1. glass faces split to Glass_Tint with REAL alpha-blend transparency
     (G2: alphaMode BLEND, alpha < 0.9) — you can see through the windows
  2. a parametric interior behind that glass: floor pan, dashboard, front
     seats, rear bench, parcel shelf — genuine dark geometry (G3), reads as
     silhouettes through the tint exactly like low-LOD game interiors
  3. wheels split to Wheel_Dark (recolour-excluded)
Door articulation is NOT attempted here (stage 2: shutline cut + hinge).

Run: blender -b -noaudio --python cabin_assembly.py -- in.glb out.glb
"""
import bpy, math, sys
import numpy as np

argv = sys.argv[sys.argv.index("--") + 1:]
SRC, DST = argv[0], argv[1]

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=SRC)
obj = [o for o in bpy.context.scene.objects if o.type == "MESH"][0]
me = obj.data
vs = np.array([v.co[:] for v in me.vertices])
lo, hi = vs.min(0), vs.max(0)
d = hi - lo
LA = int(np.argmax([d[0], d[1], 0]))          # length axis among x,y
WA = 1 - LA
L, W, H = d[LA], d[WA], d[2]
cx_w = (lo[WA] + hi[WA]) / 2
cl = (lo[LA] + hi[LA]) / 2

def mat(name, rgba, rough, metal=0.0, alpha=1.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = rgba
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    if alpha < 1.0:
        b.inputs["Alpha"].default_value = alpha
        m.blend_method = "BLEND"
    return m

# keep original material at 0, add ours
m_glass = mat("Glass_Tint", (0.03, 0.035, 0.045, 1), 0.05, alpha=0.72)
m_wheel = mat("Wheel_Dark", (0.03, 0.03, 0.033, 1), 0.5, 0.3)
m_int = mat("Interior_Dark", (0.045, 0.045, 0.05, 1), 0.9)
me.materials.append(m_glass)   # idx n
gi = len(me.materials) - 1
me.materials.append(m_wheel)
wi = len(me.materials) - 1

# ---- classify glass + wheels on the shell (length-axis aware) --------------
band = vs[vs[:, 2] < lo[2] + 0.22 * H]
histo, edges = np.histogram(band[:, LA], bins=40)
front = edges[np.argmax(histo * (edges[:-1] < cl))]
rear = edges[np.argmax(histo * (edges[:-1] >= cl))]
R = 0.085 * L
czw = lo[2] + R
belt_z = lo[2] + 0.60 * H
shoulder = W / 2
nglass = nwheel = 0
for p in me.polygons:
    c = np.zeros(3)
    for vi_ in p.vertices:
        c += vs[vi_]
    c /= len(p.vertices)
    n = np.array(p.normal[:])
    inwheel = any((c[LA] - ay) ** 2 + (c[2] - czw) ** 2 < (R * 1.18) ** 2
                  for ay in (front + R * 0.2, rear - R * 0.2))
    if inwheel and c[2] < lo[2] + 0.42 * H:
        p.material_index = wi; nwheel += 1
        continue
    if c[2] > belt_z:
        yf = (c[LA] - lo[LA]) / L
        side = abs(n[WA]) > 0.55 and abs(c[WA] - cx_w) < 0.84 * shoulder and 0.30 < yf < 0.88
        fs = abs(n[LA]) > 0.35 and 0.22 < n[2] < 0.85 and 0.20 < yf < 0.50 and c[2] > lo[2] + 0.62 * H
        rs = abs(n[LA]) > 0.40 and 0.28 < n[2] < 0.82 and yf > 0.86 and c[2] > lo[2] + 0.70 * H
        if side or fs or rs:
            p.material_index = gi; nglass += 1
print(f"shell: {nglass} glass faces, {nwheel} wheel faces")

# ---- parametric interior -----------------------------------------------------
# cabin span along length: between axles, biased rearward (bonnet excluded)
cab0 = front + (rear - front) * 0.18
cab1 = front + (rear - front) * 0.92
floor_z = lo[2] + 0.30 * H
belt = lo[2] + 0.58 * H
iw = 0.62 * W

def box(name, center, size, m, seg=3):
    bpy.ops.mesh.primitive_cube_add(size=1)
    o = bpy.context.object
    o.name = name
    sc = [0, 0, 0]; loc = [0, 0, 0]
    sc[WA], sc[LA], sc[2] = size[0], size[1], size[2]
    loc[WA], loc[LA], loc[2] = center[0], center[1], center[2]
    o.scale = sc; o.location = loc
    md = o.modifiers.new("sub", "SUBSURF"); md.levels = seg; md.render_levels = seg
    md.subdivision_type = "SIMPLE"
    o.data.materials.append(m)
    return o

parts = []
span = cab1 - cab0
# floor pan
parts.append(box("int_floor", (cx_w, cab0 + span * 0.5, floor_z), (iw, span, 0.02 * H), m_int))
# dashboard (front of cabin, under windscreen)
parts.append(box("int_dash", (cx_w, cab0 + span * 0.08, floor_z + 0.16 * H), (iw, span * 0.14, 0.16 * H), m_int))
# front seats (pair)
for s in (-1, 1):
    parts.append(box(f"int_seat{s}", (cx_w + s * iw * 0.26, cab0 + span * 0.42, floor_z + 0.10 * H),
                     (iw * 0.30, span * 0.18, 0.12 * H), m_int))
    parts.append(box(f"int_back{s}", (cx_w + s * iw * 0.26, cab0 + span * 0.50, floor_z + 0.22 * H),
                     (iw * 0.30, span * 0.05, 0.20 * H), m_int))
# rear bench + backrest
parts.append(box("int_bench", (cx_w, cab0 + span * 0.72, floor_z + 0.09 * H), (iw * 0.86, span * 0.16, 0.10 * H), m_int))
parts.append(box("int_bench_back", (cx_w, cab0 + span * 0.80, floor_z + 0.20 * H), (iw * 0.86, span * 0.05, 0.18 * H), m_int))
# parcel shelf
parts.append(box("int_shelf", (cx_w, cab0 + span * 0.90, belt - 0.02 * H), (iw * 0.9, span * 0.12, 0.015 * H), m_int))
for o in parts:
    for pl in o.data.polygons:
        pl.use_smooth = False

bpy.ops.object.select_all(action="SELECT")
bpy.ops.export_scene.gltf(filepath=DST, export_format="GLB", export_apply=True,
                          export_yup=True, export_normals=True, export_materials="EXPORT")
print("ASSEMBLY_OK", DST)
