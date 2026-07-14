"""fix_bmw5.py — 5-Series (G30) cleanup:
1. delete the showroom platform (mis-named object "number_plate_front":
   deck + rails + yellow prop + show plates)
2. recolour the blue paint to black sapphire by remapping blue-hue pixels
   in the body-shell textures (chassis/badge textures untouched)
"""
import bpy, sys
import numpy as np
import colorsys

argv = sys.argv[sys.argv.index("--") + 1:]
IN = argv[argv.index("--in") + 1]; OUT = argv[argv.index("--out") + 1]

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=IN)

# 1) drop the platform assembly
for o in list(bpy.context.scene.objects):
    if o.type == "MESH" and o.name == "number_plate_front":
        bpy.data.objects.remove(o, do_unlink=True)
        print("REMOVED platform object")

# 2) blue -> black sapphire on shell textures only
SHELL_OBJS = {f"Object_{i}" for i in list(range(9, 21))}  # painted shell + trim parts
mats = set()
for o in bpy.context.scene.objects:
    if o.type == "MESH" and o.name in SHELL_OBJS:
        for m in o.data.materials:
            if m: mats.add(m)
done_imgs = set()
for m in mats:
    if not m.use_nodes: continue
    for n in m.node_tree.nodes:
        if n.type == "TEX_IMAGE" and n.image and n.image.name not in done_imgs:
            img = n.image
            done_imgs.add(img.name)
            w, h = img.size
            px = np.array(img.pixels[:], dtype=np.float32).reshape(-1, 4)
            rgb = px[:, :3]
            mx = rgb.max(1); mn = rgb.min(1)
            v = mx
            s = np.where(mx > 1e-6, (mx - mn) / np.maximum(mx, 1e-6), 0)
            # hue for blue detection
            r, g, b = rgb[:, 0], rgb[:, 1], rgb[:, 2]
            hue = np.zeros(len(rgb))
            d = mx - mn + 1e-9
            bm = (mx == b)
            gm = (mx == g) & ~bm
            rm = ~bm & ~gm
            hue[rm] = ((g - r*0)[rm]*0 + ((g[rm] - b[rm]) / d[rm]) % 6)
            hue[gm] = ((b[gm] - r[gm]) / d[gm]) + 2
            hue[bm] = ((r[bm] - g[bm]) / d[bm]) + 4
            hue /= 6.0
            mask = (hue > 0.52) & (hue < 0.76) & (s > 0.18) & (v > 0.02)
            if mask.sum() == 0: continue
            # black sapphire: keep shading (v), collapse chroma
            newv = v[mask] * 0.14
            px[mask, 0] = newv * 0.80
            px[mask, 1] = newv * 0.85
            px[mask, 2] = newv * 1.10
            img.pixels[:] = px.reshape(-1).tolist()
            img.pack()
            print(f"RECOLOURED {img.name}: {int(mask.sum())} px of {len(px)} ({m.name[:30]})")

bpy.ops.object.select_all(action="SELECT")
bpy.ops.export_scene.gltf(filepath=OUT, export_format="GLB", use_selection=False,
    export_apply=True, export_yup=True, export_normals=True, export_materials="EXPORT")
print("BMW5_OK", OUT)
