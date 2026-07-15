"""Recolour ONLY paint-named materials (Paint_Color/body/paint...) to a target
colour. Textured paint gets a multiply factor (shading survives); plain paint
gets its base colour set. Everything else untouched."""
import bpy, re, sys
argv = sys.argv[sys.argv.index("--") + 1:]
SRC, DST, HEX = argv[0], argv[1], argv[2].lstrip("#")
def lin(c):
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
RGB = tuple(lin(int(HEX[i:i+2], 16)) for i in (0, 2, 4))
PAINT = re.compile(r"paint|body|carpaint|lack|carros", re.I)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=SRC)
n = 0
for m in bpy.data.materials:
    if not (m and m.use_nodes and PAINT.search(m.name or "")):
        continue
    b = next((x for x in m.node_tree.nodes if x.type == "BSDF_PRINCIPLED"), None)
    if not b:
        continue
    links = [l for l in m.node_tree.links if l.to_socket == b.inputs["Base Color"]]
    if links:  # textured: insert multiply
        src_sock = links[0].from_socket
        m.node_tree.links.remove(links[0])
        mix = m.node_tree.nodes.new("ShaderNodeMix")
        mix.data_type = "RGBA"; mix.blend_type = "MULTIPLY"
        mix.inputs["Factor"].default_value = 1.0
        m.node_tree.links.new(src_sock, mix.inputs[6])
        mix.inputs[7].default_value = (*[min(1.0, c * 1.25) for c in RGB], 1.0)
        m.node_tree.links.new(mix.outputs[2], b.inputs["Base Color"])
    else:
        b.inputs["Base Color"].default_value = (*RGB, 1.0)
    n += 1
print("PAINT_MATS", n)
bpy.ops.object.select_all(action="SELECT")
bpy.ops.export_scene.gltf(filepath=DST, export_format="GLB", export_apply=True,
                          export_yup=True, export_normals=True, export_materials="EXPORT")
print("RECOLOUR_OK" if n else "RECOLOUR_SKIP", DST)
