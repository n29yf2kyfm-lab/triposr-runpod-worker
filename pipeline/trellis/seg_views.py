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
scn.use_nodes = True
nt = scn.node_tree; nt.nodes.clear()
rl = nt.nodes.new("CompositorNodeRLayers")
comp = nt.nodes.new("CompositorNodeComposite")
nt.links.new(rl.outputs["Image"], comp.inputs["Image"])
fo = nt.nodes.new("CompositorNodeOutputFile")
fo.base_path = OUT
fo.format.file_format = 'OPEN_EXR'; fo.format.color_depth = '32'
fo.file_slots[0].path = "depth_"
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
    fo.file_slots[0].path = f"depth_{i:02d}_"
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
