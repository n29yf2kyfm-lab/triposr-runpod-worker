import bpy, math, sys, os
import numpy as np
from mathutils import Matrix, Vector

glb, outdir, tag = sys.argv[-3], sys.argv[-2], sys.argv[-1]
CANDS = [("id", None), ("x90", Matrix.Rotation(math.pi/2, 4, 'X')),
         ("xm90", Matrix.Rotation(-math.pi/2, 4, 'X')), ("x180", Matrix.Rotation(math.pi, 4, 'X')),
         ("y90", Matrix.Rotation(math.pi/2, 4, 'Y')), ("ym90", Matrix.Rotation(-math.pi/2, 4, 'Y'))]
for name, rot in CANDS:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=glb)
    if rot is not None:
        for o in [o for o in bpy.context.scene.objects if o.parent is None]:
            o.matrix_world = rot @ o.matrix_world
    bpy.context.view_layer.update()
    mins = np.array([1e9] * 3); maxs = np.array([-1e9] * 3)
    for o in bpy.context.scene.objects:
        if o.type == 'MESH':
            mw = o.matrix_world
            for c in o.bound_box:
                w = mw @ Vector(c)
                mins = np.minimum(mins, [w.x, w.y, w.z])
                maxs = np.maximum(maxs, [w.x, w.y, w.z])
    ctr = (mins + maxs) / 2; size = float(max(maxs - mins))
    cam_data = bpy.data.cameras.new("c"); cam = bpy.data.objects.new("c", cam_data)
    bpy.context.scene.collection.objects.link(cam)
    d = size * 1.6
    cam.location = Vector((ctr[0] + d * 0.7, ctr[1] - d * 0.9, ctr[2] + d * 0.45))
    cam.rotation_euler = (Vector(ctr) - cam.location).to_track_quat('-Z', 'Y').to_euler()
    cam_data.clip_end = d * 10
    bpy.context.scene.camera = cam
    sun_data = bpy.data.lights.new("s", type='SUN'); sun_data.energy = 4.0
    sun = bpy.data.objects.new("s", sun_data)
    bpy.context.scene.collection.objects.link(sun)
    sun.rotation_euler = (0.9, 0.2, 0.6)
    sc = bpy.context.scene
    w = bpy.data.worlds.new("w"); sc.world = w
    w.use_nodes = True
    bg = w.node_tree.nodes["Background"]
    bg.inputs[0].default_value = (0.9, 0.9, 0.9, 1.0); bg.inputs[1].default_value = 1.0
    sc.render.engine = 'CYCLES'
    sc.cycles.samples = 8
    sc.cycles.use_denoising = False
    sc.cycles.device = 'CPU'
    sc.render.resolution_x = 400; sc.render.resolution_y = 240
    sc.render.filepath = os.path.join(outdir, f"{tag}_{name}.png")
    bpy.ops.render.render(write_still=True)
print("PREVIEWS_OK", tag)
