"""blender_finish.py — Blender-side surface finishing for machine cars.

The external QC review of the gseg Golf (owner-relayed, 2026-08-16) called
the fix list: weighted normals, panel-surface repair, hard edges preserved,
proper shading. This stage does the Blender-native version of it, all
UV-safe (UVs are LOOP data in Blender, so merging duplicate vertices and
recomputing normals never touches the texture mapping):

  * every mesh: merge fragment-seam duplicates, shade smooth with
    auto-smooth at 40 deg (hard edges where the geometry is genuinely
    sharp, smooth panels elsewhere), Weighted Normal modifier
    (face-area-with-angle, keep_sharp).
  * the body (carpaint) additionally gets a light Laplacian smooth with
    volume preservation — calms mid-frequency panel waviness the bilateral
    filter leaves. Deliberately light: the bilateral already did the heavy
    lifting, and grille slats are body geometry that must survive.

Run: blender -b --python blender_finish.py -- <in.glb> <out.glb>
"""
import bpy
import sys
import math

argv = sys.argv[sys.argv.index("--") + 1:]
INP, OUT = argv[0], argv[1]

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=INP)

for o in [o for o in bpy.data.objects if o.type == 'MESH']:
    bpy.context.view_layer.objects.active = o
    o.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.remove_doubles(threshold=1e-5)
    bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.shade_smooth()
    o.data.use_auto_smooth = True                  # Blender 4.0 API
    o.data.auto_smooth_angle = math.radians(40)
    name = (o.data.materials[0].name if o.data.materials else o.name).lower()
    if "carpaint" in name:
        lap = o.modifiers.new("lap", 'LAPLACIANSMOOTH')
        lap.lambda_factor = 0.35
        lap.iterations = 4
        lap.use_volume_preserve = True
        lap.use_normalized = True
    wn = o.modifiers.new("wn", 'WEIGHTED_NORMAL')
    wn.mode = 'FACE_AREA_WITH_ANGLE'
    wn.keep_sharp = True
    o.select_set(False)
    print(f"finished {o.name}: mat={name}, verts={len(o.data.vertices)}")

bpy.ops.export_scene.gltf(filepath=OUT, export_format='GLB',
                          export_apply=True, export_normals=True)
print("BLENDER_FINISH_DONE", OUT)
