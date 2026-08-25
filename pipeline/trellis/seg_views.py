"""seg_views.py — Blender: render N calibrated views of a GLB for 2D-segmentation
label projection. Saves per view: RGB png, Z-depth EXR, and camera.json holding
the 4x4 world_to_camera matrix + focal length in pixels, so face centroids can
be projected back with a z-buffer visibility test.

Run:  blender -b --python seg_views.py -- <in.glb> <outdir> [res]
"""
import bpy, sys, os, json, math, mathutils

argv = sys.argv[sys.argv.index("--") + 1:]
INP, OUT = argv[0], argv[1]
RES = int(argv[2]) if len(argv) > 2 else 1024
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
scn.cycles.use_denoising = False          # local build has no OIDN
scn.render.resolution_x = RES; scn.render.resolution_y = RES
scn.view_settings.view_transform = 'Standard'   # AgX clips - measured 2026-08-10
scn.view_layers[0].use_pass_z = True

world = bpy.data.worlds.new("w"); world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (0.55, 0.55, 0.58, 1)
world.node_tree.nodes["Background"].inputs[1].default_value = 1.0
scn.world = world
sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
scn.collection.objects.link(sun); sun.data.energy = 3
sun.rotation_euler = (math.radians(50), 0, math.radians(30))

cam_data = bpy.data.cameras.new("cam"); cam_data.lens = 50
cam = bpy.data.objects.new("cam", cam_data)
scn.collection.objects.link(cam); scn.camera = cam

# compositor: route Z pass to an EXR alongside the RGB
#
# BLENDER 5.x MOVED THE COMPOSITOR. `scene.node_tree` was removed and the graph
# now lives in `scene.compositing_node_group`, a real node group that has to be
# CREATED and assigned -- on 5.2 the old line dies with
# "AttributeError: 'Scene' object has no attribute 'node_tree'" and the whole
# seg stage produces zero views. Both spellings are supported here because the
# repo is expected to run on whatever Blender install_blender.sh last put in
# /opt, and that is now version-discovering rather than pinned.
scn.use_nodes = True
if hasattr(scn, "node_tree") and scn.node_tree is not None:
    nt = scn.node_tree
    nt.nodes.clear()
else:                                   # Blender 5.x
    nt = bpy.data.node_groups.new("Compositor", "CompositorNodeTree")
    scn.compositing_node_group = nt
    nt.nodes.clear()
rl = nt.nodes.new("CompositorNodeRLayers")
# `CompositorNodeComposite` was also REMOVED in 5.x -- the compositing node
# GROUP's own output now terminates the graph, so the final image is wired to a
# NodeGroupOutput with an image socket declared on the group interface. Without
# this the render result never leaves the compositor and every view comes out
# blank, which is a far quieter failure than the AttributeError above.
try:
    comp = nt.nodes.new("CompositorNodeComposite")
    nt.links.new(rl.outputs["Image"], comp.inputs["Image"])
except RuntimeError:
    nt.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    comp = nt.nodes.new("NodeGroupOutput")
    nt.links.new(rl.outputs["Image"], comp.inputs[0])
fo = nt.nodes.new("CompositorNodeOutputFile")
# THIRD 5.x rename in this one block: `base_path` -> `directory` and
# `file_slots` -> `file_output_items`. Set whichever the build offers so the
# file writes to OUT either way; a wrong path here writes the depth EXRs
# somewhere else entirely and seg_project then fails on missing files rather
# than on anything to do with the mesh.
if hasattr(fo, "base_path"):
    fo.base_path = OUT
else:
    fo.directory = OUT
fo.format.file_format = 'OPEN_EXR'; fo.format.color_depth = '32'
slots = getattr(fo, "file_slots", None) or getattr(fo, "file_output_items", None)
slots[0].path = "depth_" if hasattr(slots[0], "path") else slots[0].name
nt.links.new(rl.outputs["Depth"], fo.inputs[0])

VIEWS = [(az, 18) for az in range(0, 360, 45)] + [(90, 40), (270, 40)]
cams = {}
for i, (az, el) in enumerate(VIEWS):
    a, e = math.radians(az), math.radians(el)
    d = size * 1.9
    cam.location = (ctr.x + d * math.cos(e) * math.sin(a),
                    ctr.y - d * math.cos(e) * math.cos(a),
                    ctr.z + d * math.sin(e))
    direction = mathutils.Vector(ctr) - cam.location
    cam.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()
    bpy.context.view_layer.update()
    scn.render.filepath = os.path.join(OUT, f"view_{i:02d}.png")
    _sl = getattr(fo, "file_slots", None) or getattr(fo, "file_output_items", None)
    try:
        _sl[0].path = f"depth_{i:02d}_"
    except AttributeError:
        _sl[0].name = f"depth_{i:02d}_"
    scn.frame_set(i)          # frame number lands in the EXR filename
    bpy.ops.render.render(write_still=True)
    f_px = cam_data.lens / cam_data.sensor_width * RES
    cams[f"view_{i:02d}"] = {
        "world_to_camera": [list(r) for r in cam.matrix_world.inverted()],
        "focal_px": f_px, "res": RES, "az": az, "elev": el,
        "depth_exr": f"depth_{i:02d}_{i:04d}.exr",
    }
json.dump(cams, open(os.path.join(OUT, "cameras.json"), "w"), indent=1)
print("SEG_VIEWS_DONE", len(VIEWS))
