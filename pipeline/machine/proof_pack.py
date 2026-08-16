"""proof_pack.py — component-existence proof renders (the P23 standard).

Six passes x four fixed cameras against a checkerboard backdrop:
  full / glass_only / interior_only / no_body / wireframe / exploded
(glass raised 250mm, wheels pushed outboard). Local Cycles CPU — this is
evidence, not a beauty render.

Run: blender -b --python proof_pack.py -- <in.glb> <outdir>
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
scn.cycles.samples = 32
scn.cycles.use_denoising = False
scn.view_settings.view_transform = 'Standard'
scn.render.resolution_x = 760; scn.render.resolution_y = 460
scn.render.film_transparent = False

world = bpy.data.worlds.new("w"); world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (0.75, 0.75, 0.78, 1)
scn.world = world
sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
scn.collection.objects.link(sun); sun.data.energy = 3.5
sun.rotation_euler = (math.radians(55), 0, math.radians(35))


def checker_mat():
    m = bpy.data.materials.new("checker"); m.use_nodes = True
    nt = m.node_tree
    ck = nt.nodes.new("ShaderNodeTexChecker")
    ck.inputs["Scale"].default_value = 40.0
    ck.inputs["Color1"].default_value = (0.85, 0.85, 0.85, 1)
    ck.inputs["Color2"].default_value = (0.35, 0.35, 0.38, 1)
    b = nt.nodes["Principled BSDF"]
    b.inputs["Roughness"].default_value = 1.0
    nt.links.new(ck.outputs["Color"], b.inputs["Base Color"])
    return m


for nm, loc, rot, sz in (("floor", (ctr.x, ctr.y, mn.z - 0.001), (0, 0, 0), size * 8),
                         ("wall", (ctr.x, ctr.y + size * 2.2, ctr.z), (math.pi / 2, 0, 0), size * 8)):
    bpy.ops.mesh.primitive_plane_add(size=sz, location=loc, rotation=rot)
    p = bpy.context.active_object; p.name = f"bg_{nm}"
    p.data.materials.append(checker_mat())

cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
scn.collection.objects.link(cam); scn.camera = cam
CAMS = [("front34", 35), ("front34_L", 125), ("side", 0), ("rear34", 215)]

GLASS = ("glass", "frit_band", "aperture_backstop")
INTER = ("interior", "cabin_occluder")
BODY = ("carpaint", "Lamp_Lens")
WHEELS = ("Tyre_Rubber", "Rim_Alloy", "disc_", "cal_", "Arch_Cavity")


def carparts():
    return [o for o in bpy.data.objects
            if o.type == 'MESH' and not o.name.startswith("bg_")]


def match(o, keys):
    return any(o.name.startswith(k) or k in o.name for k in keys)


def wire_mat():
    m = bpy.data.materials.new("wire"); m.use_nodes = True
    nt = m.node_tree; nt.nodes.clear()
    wf = nt.nodes.new("ShaderNodeWireframe"); wf.inputs[0].default_value = 0.0015
    e1 = nt.nodes.new("ShaderNodeEmission"); e1.inputs["Color"].default_value = (1, 1, 1, 1)
    e2 = nt.nodes.new("ShaderNodeEmission"); e2.inputs["Color"].default_value = (0, 0, 0, 1)
    mix = nt.nodes.new("ShaderNodeMixShader")
    outn = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(wf.outputs[0], mix.inputs[0])
    nt.links.new(e1.outputs[0], mix.inputs[1])
    nt.links.new(e2.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], outn.inputs[0])
    return m


def render_pass(tag, show=None, hide=None, override=None, explode=False):
    moved = []
    for o in carparts():
        vis = True
        if show is not None:
            vis = match(o, show)
        if hide is not None and match(o, hide):
            vis = False
        o.hide_render = not vis
    if explode:
        for o in carparts():
            if match(o, ("glass", "frit_band")):
                o.location.z += 0.25; moved.append((o, (0, 0, -0.25)))
            elif match(o, ("Tyre_Rubber", "Rim_Alloy", "disc_", "cal_")):
                dy = 0.4 if o.location.y >= 0 else -0.4
                cy = sum(v.co.y for v in o.data.vertices) / max(1, len(o.data.vertices))
                dy = 0.4 if cy >= 0 else -0.4
                o.location.y += dy; moved.append((o, (0, -dy, 0)))
    vl = scn.view_layers[0]
    vl.material_override = override
    for name, az in CAMS:
        a, e = math.radians(az), math.radians(12)
        d = size * 1.9
        cam.location = (ctr.x + d * math.cos(e) * math.sin(a),
                        ctr.y - d * math.cos(e) * math.cos(a),
                        ctr.z + d * math.sin(e))
        cam.rotation_euler = (mathutils.Vector(ctr) - cam.location
                              ).to_track_quat('-Z', 'Y').to_euler()
        scn.render.filepath = os.path.join(OUT, f"proof_{tag}_{name}.png")
        bpy.ops.render.render(write_still=True)
    for o, dl in moved:
        o.location.x += dl[0]; o.location.y += dl[1]; o.location.z += dl[2]
    vl.material_override = None


render_pass("full")
render_pass("glass_only", show=GLASS)
render_pass("interior_only", show=INTER)
render_pass("no_body", hide=BODY)
render_pass("wireframe", override=wire_mat())
render_pass("exploded", explode=True)
print("PROOF_PACK_DONE")
