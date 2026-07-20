"""Bake a DVLA colour into a GLB's body-paint materials (flat respray: set base
colour, drop any base-colour texture so it's a clean solid), leave everything
else untouched. Blender headless. Usage:
  bake_colour.py in.glb out.glb R,G,B(linear) name1,name2,...(body mats)"""
import bpy, sys
inp, outp, rgb_s, mats_s = sys.argv[-4], sys.argv[-3], sys.argv[-2], sys.argv[-1]
R, G, B = [float(x) for x in rgb_s.split(",")]
body = set(mats_s.split(","))
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=inp)

done = []
for m in bpy.data.materials:
    if m.name not in body or not m.use_nodes:
        continue
    bsdf = next((n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
    if not bsdf:
        continue
    bc = bsdf.inputs["Base Color"]
    # drop any base-colour texture link so the respray is a clean flat colour
    for l in list(bc.links):
        m.node_tree.links.remove(l)
    bc.default_value = (R, G, B, 1.0)
    if "Metallic" in bsdf.inputs: bsdf.inputs["Metallic"].default_value = 0.6
    if "Roughness" in bsdf.inputs: bsdf.inputs["Roughness"].default_value = 0.35
    done.append(m.name)

print("RECOLOURED:", done)
bpy.ops.export_scene.gltf(filepath=outp, export_format='GLB',
    export_draco_mesh_compression_enable=True, export_draco_mesh_compression_level=6,
    export_apply=True, use_selection=False, export_yup=True)
print("EXPORTED", outp)
