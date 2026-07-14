"""add_plates.py — attach UK number plates to the Golf: white GB front,
yellow GB rear. Textured planes placed against the vertex-scanned bumper/
tailgate face at plate height, tilted to match panel rake.

Blender import convention for this file: x=width, y=length, z=height (Z-up).

blender -b -noaudio --python /tmp/add_plates.py -- \
  --in pipeline/build/golf_v15.glb --tex <dir> --out pipeline/build/golf_v16.glb \
  [--flipfront] [--fliprear]   (mirror-fix toggles, decided from render check)
"""
import bpy, sys, math
import numpy as np

argv = sys.argv[sys.argv.index("--") + 1:]
IN  = argv[argv.index("--in") + 1]
OUT = argv[argv.index("--out") + 1]
TEX = argv[argv.index("--tex") + 1]
FLIPF = "--flipfront" in argv
FLIPR = "--fliprear" in argv

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=IN)
scene = bpy.context.scene

allv = []
for o in scene.objects:
    if o.type != "MESH" or not len(o.data.vertices):
        continue
    n = len(o.data.vertices)
    co = np.empty(n * 3)
    o.data.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    M = np.array(o.matrix_world)
    allv.append(co @ M[:3, :3].T + M[:3, 3])
V = np.vstack(allv)
lo, hi = V.min(0), V.max(0)
size = hi - lo
ctr = (lo + hi) / 2
assert size[1] == size.max() and size[2] == size.min(), f"axis surprise: {size}"
Wd, Ln, H = size[0], size[1], size[2]
gz = lo[2]

# front direction along y from windscreen centroid
front_y = None
for o in scene.objects:
    if o.type == "MESH" and any((m and m.name == "front_glass_tint") for m in o.data.materials):
        n = len(o.data.vertices)
        co = np.empty(n * 3); o.data.vertices.foreach_get("co", co)
        M = np.array(o.matrix_world)
        front_y = (co.reshape(-1, 3) @ M[:3, :3].T + M[:3, 3])[:, 1].mean()
        break
fd = 1.0 if (front_y if front_y is not None else ctr[1] + 1) > ctr[1] else -1.0
if "--fd" in argv: fd = float(argv[argv.index("--fd") + 1])

pw = 0.52 / 1.79 * Wd            # UK plate 520mm on a 1.79m car
ph = pw * 111 / 520

def extreme_y(z0, z1, want_max):
    band = V[(V[:, 2] >= z0) & (V[:, 2] <= z1) & (np.abs(V[:, 0] - ctr[0]) < Wd * 0.30)]
    return band[:, 1].max() if want_max else band[:, 1].min()

def plate_mat(name, img_path):
    m = bpy.data.materials.new(name); m.use_nodes = True
    bsdf = m.node_tree.nodes["Principled BSDF"]
    tex = m.node_tree.nodes.new("ShaderNodeTexImage")
    tex.image = bpy.data.images.load(img_path)
    m.node_tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.35
    bsdf.inputs["Metallic"].default_value = 0.0
    return m

def add_plate(name, img, zc, y_face, facing, rake, flip):
    # Rx(+90) stands the plane upright, text upright, normal -y.
    # If it must face +y, turn the card about the vertical axis (Rz(pi)).
    bpy.ops.mesh.primitive_plane_add(size=1, location=(ctr[0], y_face, zc))
    o = bpy.context.active_object; o.name = name
    o.scale = (pw, ph, 1)
    rz = math.pi if facing > 0 else 0.0
    if flip:
        rz += math.pi
    rx = math.pi / 2 + (rake if facing < 0 else -rake)
    o.rotation_euler = (rx, 0, rz)
    bpy.ops.object.transform_apply(scale=True, rotation=True)
    o.data.materials.append(plate_mat(name + "_mat", img))
    return o

# FRONT (white): centre ~29% height, on the bumper face
fzc = gz + H * 0.29
yf_bot = extreme_y(fzc - ph / 2, fzc, fd > 0)
yf_top = extreme_y(fzc, fzc + ph / 2, fd > 0)
f_rake = max(-0.21, min(0.21, math.atan2(fd * (yf_top - yf_bot), ph)))
yf = (yf_bot + yf_top) / 2 + fd * Ln * 0.002
add_plate("plate_front", f"{TEX}/uk_plate_front.png", fzc, yf, fd, f_rake, FLIPF)

# REAR (yellow): Golf tailgate plate ~50% height
rzc = gz + H * (float(argv[argv.index("--rearh")+1]) if "--rearh" in argv else 0.50)
yr_bot = extreme_y(rzc - ph / 2, rzc, fd < 0)
yr_top = extreme_y(rzc, rzc + ph / 2, fd < 0)
r_rake = max(-0.21, min(0.21, math.atan2(-fd * (yr_top - yr_bot), ph)))
yr = (yr_bot + yr_top) / 2 - fd * Ln * 0.002
add_plate("plate_rear", f"{TEX}/uk_plate_rear.png", rzc, yr, -fd, r_rake, FLIPR)

bpy.ops.object.select_all(action="SELECT")
bpy.ops.export_scene.gltf(filepath=OUT, export_format="GLB", use_selection=False,
    export_apply=True, export_yup=True, export_normals=True, export_materials="EXPORT")
print(f"PLATES_OK {OUT} fd={fd} front y={yf:.3f} rake={math.degrees(f_rake):.1f} "
      f"rear y={yr:.3f} rake={math.degrees(r_rake):.1f} pw={pw:.3f} ph={ph:.3f}")
