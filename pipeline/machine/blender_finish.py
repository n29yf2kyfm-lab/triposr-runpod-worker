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
import bmesh
import os
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
    # AUTO-SMOOTH MOVED IN BLENDER 4.1. `mesh.use_auto_smooth` and
    # `mesh.auto_smooth_angle` were REMOVED and replaced by the
    # `shade_auto_smooth` operator, which adds a "Smooth by Angle" modifier.
    # This line was written against the container's old stripped 4.0.2 (its own
    # comment said "Blender 4.0 API"); install_blender.sh now puts 4.5.12 in
    # /opt, so the stage died with
    #   AttributeError: 'Mesh' object has no attribute 'use_auto_smooth'
    # AFTER the weld had already run -- and Blender still printed "Blender
    # quit", which is exactly why premium.py refuses to trust an exit code and
    # requires the BLENDER_FINISH_DONE marker instead.
    # Both spellings are kept because this repo must run on whatever Blender
    # install_blender.sh last put in /opt.
    if hasattr(o.data, "use_auto_smooth"):         # Blender <= 4.0
        o.data.use_auto_smooth = True
        o.data.auto_smooth_angle = math.radians(40)
    else:                                          # Blender >= 4.1
        # NOT `bpy.ops.object.shade_auto_smooth()`. It returns success in
        # background mode and adds NOTHING -- verified on 4.5.12: the operator
        # reported FINISHED and `o.modifiers` was still empty, because the
        # "Smooth by Angle" node group it appends lives in an asset library
        # that headless Blender does not load. A silent no-op is worse here
        # than a crash, since the crumpled-foil shading it is meant to prevent
        # would ship looking like a mesh defect.
        # Marking sharp edges by dihedral angle is the same thing done
        # explicitly, with no asset dependency, and the WEIGHTED_NORMAL
        # modifier added below already has keep_sharp=True to honour it.
        bm = bmesh.new()
        bm.from_mesh(o.data)
        lim = math.radians(40)
        for e in bm.edges:
            e.smooth = not (len(e.link_faces) == 2 and e.calc_face_angle() > lim)
        bm.to_mesh(o.data)
        bm.free()
    name = (o.data.materials[0].name if o.data.materials else o.name).lower()
    # THE LAPLACIAN SMOOTH IS OFF BY DEFAULT AND MUST STAY OFF FOR premium.py.
    #
    # Measured 2026-08-25 on the Pixal Golf, by bisecting this stage's own
    # operations against renders of its input: the LAPLACIANSMOOTH alone shreds
    # the nose. s10 (this stage's input) is clean; with the laplacian the front
    # bumper, wings and A-pillar come back torn and speckled with holes; with it
    # disabled the output matches the input exactly. Sharp-edge marking was
    # tested in both states and is harmless either way -- I wrongly blamed it
    # first, and the bisect corrected that.
    #
    # WHY it damages here when the docstring above says it is safe: that comment
    # justifies it as "the bilateral already did the heavy lifting", and the
    # bilateral is surface_clean.py -- a stage in machine.py's chain, which
    # premium.py DOES NOT RUN. So in this chain a normalised, volume-preserving
    # Laplacian is applied to a mesh that was never bilaterally filtered and
    # still carries near-folded faces (dihedral p99 = 139.5 deg on this body).
    # Smoothing across those collapses them.
    #
    # Left opt-in rather than deleted, because on a bilaterally-filtered mesh
    # it is the panel-waviness fix it was written to be.
    if "carpaint" in name and os.environ.get("FINISH_LAPLACIAN") == "1":
        lap = o.modifiers.new("lap", 'LAPLACIANSMOOTH')
        lap.lambda_factor = float(os.environ.get("FINISH_LAP_LAMBDA", "0.35"))
        lap.iterations = int(os.environ.get("FINISH_LAP_ITERS", "4"))
        lap.use_volume_preserve = True
        lap.use_normalized = True
        print(f"  laplacian ENABLED on {name} (FINISH_LAPLACIAN=1)")
    wn = o.modifiers.new("wn", 'WEIGHTED_NORMAL')
    wn.mode = 'FACE_AREA_WITH_ANGLE'
    wn.keep_sharp = True
    o.select_set(False)
    print(f"finished {o.name}: mat={name}, verts={len(o.data.vertices)}")

bpy.ops.export_scene.gltf(filepath=OUT, export_format='GLB',
                          export_apply=True, export_normals=True)
print("BLENDER_FINISH_DONE", OUT)
