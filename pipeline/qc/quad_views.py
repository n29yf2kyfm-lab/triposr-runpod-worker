"""quad_views.py — four ortho views of a GLB (side, front34, rear34, top).

A local eyeball rig for judging a staged or shipped GLB without spending a GPU
wave render. Lives in the repo deliberately: it was rebuilt three times in one
session after container rollbacks wiped the scratchpad copy.

Two rig traps are baked in, both of which produced WRONG verdicts before:
  * Standard view transform, not Blender 4's default AgX. AgX plus these light
    energies clipped a dark tyre to pure white and manufactured tyre failures.
  * Camera up is the MODEL's up axis, not world Z. A Y-up glb otherwise renders
    rotated, which is how a correct car once read as "on its side".

The top view is worth rendering even when it looks redundant — it is the view
that settles roof questions, and a specular highlight on a 3/4 view has been
misread as an unpainted roof.

Usage:
  xvfb-run -a blender -b --factory-startup -noaudio \
    -P pipeline/qc/quad_views.py -- <in.glb> <out_prefix.png> [samples]
"""
import bpy, sys, mathutils
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
src, out = argv[0], argv[1]
SAMPLES = int(argv[2]) if len(argv) > 2 else 16

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)

objs = [o for o in bpy.context.scene.objects if o.type == "MESH"]
if not objs:
    raise SystemExit("no meshes")

mn = Vector((1e18,) * 3); mx = Vector((-1e18,) * 3)
for o in objs:
    for c in o.bound_box:
        w = o.matrix_world @ Vector(c)
        for i in range(3):
            mn[i] = min(mn[i], w[i]); mx[i] = max(mx[i], w[i])
ctr = (mn + mx) / 2
dim = mx - mn
radius = max(dim) / 2
print("DIM", [round(v, 3) for v in dim])

world = bpy.data.worlds.new("W")
bpy.context.scene.world = world
world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (0.22, 0.22, 0.24, 1)
world.node_tree.nodes["Background"].inputs[1].default_value = 1.0


def add_light(loc, energy):
    d = bpy.data.lights.new("L", type="AREA")
    d.energy = energy
    d.size = radius * 2
    ob = bpy.data.objects.new("L", d)
    ob.location = loc
    bpy.context.collection.objects.link(ob)
    tr = ob.constraints.new("TRACK_TO")
    e = bpy.data.objects.new("T", None); e.location = ctr
    bpy.context.collection.objects.link(e)
    tr.target = e


p = radius * 4
add_light((ctr.x + p, ctr.y - p, ctr.z + p), 700 * radius * radius)
add_light((ctr.x - p, ctr.y + p, ctr.z + p * 0.6), 380 * radius * radius)
add_light((ctr.x, ctr.y - p, ctr.z + p * 0.2), 260 * radius * radius)

cam_d = bpy.data.cameras.new("C")
cam_d.type = "ORTHO"
cam = bpy.data.objects.new("C", cam_d)
bpy.context.collection.objects.link(cam)
bpy.context.scene.camera = cam

sc = bpy.context.scene
sc.render.engine = "CYCLES"
sc.cycles.device = "CPU"
sc.cycles.samples = SAMPLES
sc.cycles.use_denoising = False
sc.render.film_transparent = False
sc.render.image_settings.file_format = "PNG"
sc.view_settings.view_transform = "Standard"
sc.view_settings.look = "None"

order = sorted(range(3), key=lambda i: -dim[i])
LONG, WIDE, UP = order[0], order[1], order[2]
print("AXES long=%d wide=%d up=%d" % (LONG, WIDE, UP))
dist = radius * 3.0


def mk(dl, dw, du):
    v = [ctr.x, ctr.y, ctr.z]
    v[LONG] += dl; v[WIDE] += dw; v[UP] += du
    return tuple(v)


def look_at(camobj, loc, target, up_idx):
    loc = mathutils.Vector(loc)
    fwd = (mathutils.Vector(target) - loc).normalized()
    up = mathutils.Vector((0, 0, 0)); up[up_idx] = 1.0
    right = fwd.cross(up)
    if right.length < 1e-6:
        up = mathutils.Vector((0, 0, 0)); up[(up_idx + 1) % 3] = 1.0
        right = fwd.cross(up)
    right.normalize()
    trueup = right.cross(fwd).normalized()
    camobj.matrix_world = mathutils.Matrix((
        (right.x, trueup.x, -fwd.x, loc.x),
        (right.y, trueup.y, -fwd.y, loc.y),
        (right.z, trueup.z, -fwd.z, loc.z),
        (0, 0, 0, 1)))


VIEWS = {
    "side": (mk(0, -dist, radius * 0.25), UP),
    "f34":  (mk(dist * 0.75, -dist * 0.75, radius * 0.45), UP),
    "r34":  (mk(-dist * 0.75, -dist * 0.75, radius * 0.45), UP),
    "top":  (mk(0, 0, dist), LONG),
}

for name, (loc, upax) in VIEWS.items():
    look_at(cam, loc, ctr, upax)
    cam_d.clip_start = max(radius * 0.001, 1e-4)
    cam_d.clip_end = radius * 50
    sc.render.resolution_x = 900
    sc.render.resolution_y = 900
    cam_d.ortho_scale = max(dim) * 1.12
    sc.render.filepath = out.replace(".png", f"_{name}.png")
    bpy.ops.render.render(write_still=True)
    print("rendered", name)
print("OK")
