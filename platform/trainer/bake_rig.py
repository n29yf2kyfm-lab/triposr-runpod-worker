"""Bake a RIGIDLY-SKINNED game-rig car into one static mesh per part.

    blender -b --python bake_rig.py -- in.glb out.glb rig.json

Some catalogue cars are game-vehicle rigs (the Audi A6 C8 is one): each door,
the body shell, the chassis and every lamp is a separate skinned mesh bound
100% to ONE bone, and the bone is the part. Measured on the A6 before writing
this: 125 skinned primitives, every vertex at weight 1.0 on a single joint,
no mesh spanning two bones. So the skin carries no deformation at all — it is
a parts hierarchy stored in the most awkward possible form.

Strip Bay moves parts by rotating a group about a hinge. A skinned mesh
ignores its group transform (its vertices follow the BONES), so the car has
to be baked first: apply each armature modifier, name the object after the
bone that owned it, drop the armature. Geometry is not changed — the bake is
the same pose the file already renders in.

Also writes the bone HEAD positions in glTF space (+Y up) to rig.json. A game
rig puts a door bone ON THE HINGE, because that is what the game rotates it
about, so those positions are the pivots — taken from the file, not guessed.
"""
import bpy, sys, json, mathutils

a = sys.argv[sys.argv.index('--') + 1:]
src, dst, rigp = a[0], a[1], a[2]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)

arms = [o for o in bpy.data.objects if o.type == 'ARMATURE']
assert len(arms) == 1, f'expected one armature, found {len(arms)}'
arm = arms[0]
bpy.context.view_layer.update()

# Blender Z-up -> glTF Y-up: (x, y, z) -> (x, z, -y)
to_gltf = lambda v: [round(v.x, 5), round(v.z, 5), round(-v.y, 5)]
heads = {b.name: to_gltf(arm.matrix_world @ b.head_local) for b in arm.data.bones}

baked, counts = 0, {}
for o in list(bpy.data.objects):
    if o.type != 'MESH':
        continue
    mods = [m for m in o.modifiers if m.type == 'ARMATURE']
    if not mods:
        continue
    # which bone owns this mesh: the single group carrying weight
    used = {}
    for v in o.data.vertices:
        for g in v.groups:
            if g.weight > 0:
                n = o.vertex_groups[g.group].name
                used[n] = used.get(n, 0) + 1
    assert len(used) == 1, f'{o.name} is bound to {len(used)} bones: {list(used)[:4]} — not a rigid rig'
    bone = next(iter(used))
    bpy.context.view_layer.objects.active = o
    for m in mods:
        bpy.ops.object.modifier_apply(modifier=m.name)
    mw = o.matrix_world.copy()
    o.parent = None
    o.matrix_world = mw
    o.vertex_groups.clear()
    k = counts.get(bone, 0); counts[bone] = k + 1
    o.name = f'{bone}__{k}'
    baked += 1

# non-skinned meshes parented under the armature must keep their world pose
for o in bpy.data.objects:
    if o.type == 'MESH' and o.parent is not None:
        mw = o.matrix_world.copy(); o.parent = None; o.matrix_world = mw
bpy.data.objects.remove(arm)
for o in [o for o in bpy.data.objects if o.type == 'EMPTY']:
    bpy.data.objects.remove(o)

print(f'BAKE baked={baked} bones={len(counts)}')
json.dump({'heads': heads, 'parts': counts}, open(rigp, 'w'), indent=1)
bpy.ops.export_scene.gltf(filepath=dst, export_format='GLB', export_apply=True,
                          export_normals=True, export_skins=False,
                          export_animations=False)
print('BAKE_DONE')
