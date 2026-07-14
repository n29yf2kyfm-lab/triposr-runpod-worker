"""palette_recolour.py — recolour a palette-textured car body to a target
colour by tracing the body object's UV footprint into its texture and
recolouring exactly those pixels (value-preserving), leaving badges,
interior and trim untouched.

blender -b -noaudio --python /tmp/palette_recolour.py -- \
  --in <glb> --out <glb> --rgb 0.05,0.10,0.35 [--body <object name>]
If --body is omitted, the largest-surface-area mesh is used.
"""
import bpy, sys
import numpy as np

argv = sys.argv[sys.argv.index("--") + 1:]
IN = argv[argv.index("--in") + 1]; OUT = argv[argv.index("--out") + 1]
RGB = tuple(float(x) for x in argv[argv.index("--rgb") + 1].split(","))
BODY = argv[argv.index("--body") + 1] if "--body" in argv else None

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=IN)

meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
def area(o):
    return sum(p.area for p in o.data.polygons)
body = bpy.data.objects[BODY] if BODY else max(meshes, key=area)
print(f"BODY OBJECT: {body.name} area={area(body):.1f} "
      f"mats={[m.name if m else '-' for m in body.data.materials]}")

# mark the UV pixels the body actually uses, per image
uvl = body.data.uv_layers.active.data
imgs = {}
for m in body.data.materials:
    if not (m and m.use_nodes):
        continue
    for n in m.node_tree.nodes:
        if n.type == "TEX_IMAGE" and n.image:
            imgs.setdefault(n.image.name, (n.image, set()))
for poly in body.data.polygons:
    m = body.data.materials[poly.material_index]
    if not (m and m.use_nodes):
        continue
    tgt = None
    for n in m.node_tree.nodes:
        if n.type == "TEX_IMAGE" and n.image:
            tgt = imgs[n.image.name]; break
    if not tgt:
        continue
    img, marks = tgt
    w, h = img.size
    for li in poly.loop_indices:
        u, v = uvl[li].uv
        marks.add((int((u % 1.0) * (w - 1)), int((v % 1.0) * (h - 1))))

for name, (img, marks) in imgs.items():
    if not marks:
        continue
    w, h = img.size
    px = np.array(img.pixels[:], dtype=np.float32).reshape(h, w, 4)
    mask = np.zeros((h, w), dtype=bool)
    R = max(1, w // 256)          # dilate marks so whole palette patch is hit
    for (x, y) in marks:
        mask[max(0, y - R):min(h, y + R + 1), max(0, x - R):min(w, x + R + 1)] = True
    v = px[..., :3].max(2)
    for i in range(3):
        ch = px[..., i]
        ch[mask] = np.clip(v[mask] * RGB[i] * 1.25, 0, 1)
        px[..., i] = ch
    img.pixels[:] = px.reshape(-1).tolist()
    img.pack()
    print(f"RECOLOURED {name}: {int(mask.sum())}/{w*h} px")

bpy.ops.object.select_all(action="SELECT")
bpy.ops.export_scene.gltf(filepath=OUT, export_format="GLB", use_selection=False,
    export_apply=True, export_yup=True, export_normals=True, export_materials="EXPORT")
print("PALETTE_OK", OUT)
