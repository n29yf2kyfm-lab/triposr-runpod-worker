import bpy, math, sys, json
import numpy as np
from mathutils import Matrix, Vector
glb, out, mode = sys.argv[-3], sys.argv[-2], sys.argv[-1]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=glb)
roots = [o for o in bpy.context.scene.objects if o.parent is None]
ROT = {"xm90": Matrix.Rotation(-math.pi/2, 4, 'X'), "x180": Matrix.Rotation(math.pi, 4, 'X'), "id": None}
if mode == "outlier_scale":
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    info = []
    for o in meshes:
        mw = o.matrix_world
        pts = [mw @ Vector(c) for c in o.bound_box]
        mins = np.min([[p.x, p.y, p.z] for p in pts], axis=0)
        maxs = np.max([[p.x, p.y, p.z] for p in pts], axis=0)
        info.append((o, mins, maxs, float(np.prod(np.maximum(maxs - mins, 1e-9)))))
    main = max(info, key=lambda t: t[3])
    mctr = (main[1] + main[2]) / 2
    mdiag = float(np.linalg.norm(main[2] - main[1]))
    kept = []
    for o, mins, maxs, vol in info:
        ctr = (mins + maxs) / 2
        if np.linalg.norm(ctr - mctr) > mdiag * 3:
            bpy.data.objects.remove(o, do_unlink=True)
        else:
            kept.append((mins, maxs))
    mins = np.min([k[0] for k in kept], axis=0); maxs = np.max([k[1] for k in kept], axis=0)
    length = float(max(maxs - mins))
    s = 4.6 / length if length > 0 else 1.0
    scale_m = Matrix.Scale(s, 4)
    for o in [o for o in bpy.context.scene.objects if o.parent is None]:
        o.matrix_world = scale_m @ o.matrix_world
    print("OUTLIER_SCALE", len(info), "->", len(kept), "scale", s)
else:
    rot = ROT[mode]
    if rot is not None:
        for o in roots:
            o.matrix_world = rot @ o.matrix_world
bpy.context.view_layer.update()
bpy.ops.export_scene.gltf(filepath=out, export_format='GLB',
                          export_draco_mesh_compression_enable=True)
print("FIX_OK", mode)
