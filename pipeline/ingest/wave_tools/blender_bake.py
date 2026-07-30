import bpy, sys
import numpy as np
from mathutils import Matrix, Vector
glb, out, mode = sys.argv[-3], sys.argv[-2], sys.argv[-1]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=glb)
dg = bpy.context.evaluated_depsgraph_get()
baked = []
for o in list(bpy.context.scene.objects):
    if o.type == 'MESH':
        ev = o.evaluated_get(dg)
        me = bpy.data.meshes.new_from_object(ev)
        me.transform(o.matrix_world)
        no = bpy.data.objects.new(o.name + "_b", me)
        bpy.context.scene.collection.objects.link(no)
        baked.append(no)
for o in list(bpy.context.scene.objects):
    if o not in baked:
        bpy.data.objects.remove(o, do_unlink=True)
for a in list(bpy.data.actions):
    bpy.data.actions.remove(a)
if mode == "outlier_scale":
    info = []
    for o in baked:
        pts = np.array([v.co[:] for v in o.data.vertices]) if len(o.data.vertices) else None
        if pts is None: continue
        mins, maxs = pts.min(0), pts.max(0)
        info.append((o, mins, maxs, float(np.prod(np.maximum(maxs - mins, 1e-9)))))
    main = max(info, key=lambda t: t[3])
    mctr = (main[1] + main[2]) / 2
    mdiag = float(np.linalg.norm(main[2] - main[1]))
    kept = []
    for o, mins, maxs, vol in info:
        if np.linalg.norm((mins + maxs) / 2 - mctr) > mdiag * 1.5:
            bpy.data.objects.remove(o, do_unlink=True)
        else:
            kept.append((mins, maxs))
    mins = np.min([k[0] for k in kept], axis=0); maxs = np.max([k[1] for k in kept], axis=0)
    s = 4.6 / float(max(maxs - mins))
    for o in bpy.context.scene.objects:
        o.data.transform(Matrix.Scale(s, 4))
    print("OUTLIER_SCALE kept", len(kept), "of", len(info), "scale", s)
bpy.ops.export_scene.gltf(filepath=out, export_format='GLB',
                          export_draco_mesh_compression_enable=True)
print("BAKE_OK", mode)
