"""qc_turntables.py — neutral validation renders per the QC review standard.

Three passes x four azimuths: CLAY (neutral grey — surface truth without
paint gloss hiding or exaggerating anything), NORMAL (world normals as
colour — shading discontinuities and broken normals show as banding), and
MATERIAL-ID (flat colour per material — label bleed is instantly visible).
These are diagnostic artefacts: judge surface and labels here BEFORE any
showroom render is taken.

Run: blender -b --python qc_turntables.py -- <in.glb> <outdir>
"""
import bpy
import sys
import os
import math
import mathutils

argv = sys.argv[sys.argv.index("--") + 1:]
INP, OUT = argv[0], argv[1]
os.makedirs(OUT, exist_ok=True)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=INP)
meshes = [o for o in bpy.data.objects if o.type == 'MESH']

mn = mathutils.Vector((1e9,) * 3); mx = mathutils.Vector((-1e9,) * 3)
for o in meshes:
    for c in o.bound_box:
        w = o.matrix_world @ mathutils.Vector(c)
        mn = mathutils.Vector(map(min, mn, w)); mx = mathutils.Vector(map(max, mx, w))
ctr = (mn + mx) / 2; size = max(mx - mn)

scn = bpy.context.scene
scn.render.engine = 'CYCLES'
scn.cycles.device = 'CPU'
scn.cycles.samples = 24
scn.cycles.use_denoising = False
scn.view_settings.view_transform = 'Standard'
scn.render.resolution_x = 800; scn.render.resolution_y = 500

world = bpy.data.worlds.new("w"); world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (0.65, 0.65, 0.67, 1)
scn.world = world
sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
scn.collection.objects.link(sun); sun.data.energy = 3
sun.rotation_euler = (math.radians(50), 0, math.radians(30))

cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
scn.collection.objects.link(cam); scn.camera = cam


def clay_material():
    m = bpy.data.materials.new("qc_clay"); m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (0.55, 0.55, 0.55, 1)
    b.inputs["Roughness"].default_value = 0.6
    return m


def normal_material():
    m = bpy.data.materials.new("qc_normal"); m.use_nodes = True
    nt = m.node_tree; nt.nodes.clear()
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    vm = nt.nodes.new("ShaderNodeVectorMath"); vm.operation = 'MULTIPLY_ADD'
    vm.inputs[1].default_value = (0.5, 0.5, 0.5)
    vm.inputs[2].default_value = (0.5, 0.5, 0.5)
    em = nt.nodes.new("ShaderNodeEmission")
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(geo.outputs["Normal"], vm.inputs[0])
    nt.links.new(vm.outputs[0], em.inputs["Color"])
    nt.links.new(em.outputs[0], out.inputs["Surface"])
    return m


PALETTE = {"carpaint": (0.85, 0.10, 0.10), "glass": (0.10, 0.45, 0.95),
           "Tyre_Rubber": (0.10, 0.10, 0.10), "Rim_Alloy": (0.95, 0.75, 0.10),
           "Lamp_Lens": (0.95, 0.35, 0.75), "interior": (0.10, 0.75, 0.35)}


def render_pass(tag, override):
    vl = scn.view_layers[0]
    vl.material_override = override
    for i, az in enumerate((35, 125, 215, 305)):
        a, e = math.radians(az), math.radians(14)
        d = size * 1.85
        cam.location = (ctr.x + d * math.cos(e) * math.sin(a),
                        ctr.y - d * math.cos(e) * math.cos(a),
                        ctr.z + d * math.sin(e))
        cam.rotation_euler = (mathutils.Vector(ctr) - cam.location
                              ).to_track_quat('-Z', 'Y').to_euler()
        scn.render.filepath = os.path.join(OUT, f"qc_{tag}_{i}.png")
        bpy.ops.render.render(write_still=True)


render_pass("clay", clay_material())
render_pass("normal", normal_material())

# material-ID: recolour each real material to its flat palette colour
for mat in bpy.data.materials:
    col = PALETTE.get(mat.name.split(".")[0])
    if col is None:
        continue
    mat.use_nodes = True
    nt = mat.node_tree; nt.nodes.clear()
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = (*col, 1)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(em.outputs[0], out.inputs["Surface"])
render_pass("matid", None)
print("QC_TURNTABLES_DONE")
