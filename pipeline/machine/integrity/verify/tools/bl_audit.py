#!/usr/bin/env python3
"""
BLENDER-SIDE integrity audit.  Run in a BRAND-NEW Blender process:

    blender -b --factory-startup --python bl_audit.py -- <in.glb> <out.json> [label]

Every geometric number is taken from TRANSFORMED vertices
(`obj.matrix_world @ v.co`) after evaluating the dependency graph, never from
`obj.bound_box` and never from node-local coordinates.  CLAUDE.md records a
gate that passed a car whose front tyres were 183 mm in the air because it read
a WHOLE-MODEL bbox minimum; per-object tyre minima are therefore reported
separately and are the grounding witness.
"""
import bpy, sys, json, math, os
from mathutils import Vector

argv = sys.argv[sys.argv.index('--') + 1:]
SRC, DST = argv[0], argv[1]
LABEL = argv[2] if len(argv) > 2 else os.path.basename(SRC)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=SRC)

TYREY = ('tyre', 'tire', 'rubber')
RIMY = ('rim', 'wheel', 'alloy', 'hub', 'spoke')
GLASSY = ('glass', 'window', 'windscreen', 'windshield', 'screen', 'glazing', 'pane')
NOTGLASS = ('lamp', 'light', 'surr', 'frame', 'trim', 'mirror', 'rearview',
            'icon', 'button', 'instrument', 'dash', 'seal', 'wiper')


def cls_of(name, matnames):
    for src in (name or '',) + tuple(matnames):
        n = src.lower()
        if any(k in n for k in TYREY) and 'arch' not in n:
            return 'tyre'
        if any(k in n for k in RIMY):
            return 'rim'
        if any(k in n for k in GLASSY) and not any(k in n for k in NOTGLASS):
            return 'glass'
    return 'other'


dg = bpy.context.evaluated_depsgraph_get()
objs = [o for o in bpy.context.scene.objects if o.type == 'MESH']

gmin = Vector((1e30,) * 3)
gmax = Vector((-1e30,) * 3)
rows = []
tot_tris = 0
tot_verts = 0
loose_report = []

for o in objs:
    ev = o.evaluated_get(dg)
    me = ev.to_mesh()
    me.calc_loop_triangles()
    mw = o.matrix_world
    omin = Vector((1e30,) * 3)
    omax = Vector((-1e30,) * 3)
    for v in me.vertices:
        w = mw @ v.co
        for k in range(3):
            if w[k] < omin[k]:
                omin[k] = w[k]
            if w[k] > omax[k]:
                omax[k] = w[k]
            if w[k] < gmin[k]:
                gmin[k] = w[k]
            if w[k] > gmax[k]:
                gmax[k] = w[k]
    ntri = len(me.loop_triangles)
    nvert = len(me.vertices)
    tot_tris += ntri
    tot_verts += nvert
    # area in world units
    area = 0.0
    for t in me.loop_triangles:
        a, b, c = (mw @ me.vertices[i].co for i in t.vertices)
        area += (b - a).cross(c - a).length * 0.5
    mats = [m.name if m else '' for m in o.data.materials]
    det = mw.to_3x3().determinant()
    rows.append({
        'name': o.name, 'tris': ntri, 'verts': nvert,
        'area_m2': round(area, 6),
        'det': round(det, 9),
        'scale': [round(v, 6) for v in o.matrix_world.to_scale()],
        'materials': mats,
        'class': cls_of(o.name, mats),
        'wmin': [round(v, 6) for v in omin],
        'wmax': [round(v, 6) for v in omax],
        'hide_render': o.hide_render,
        'prim_slots': len(o.data.materials),
    })
    ev.to_mesh_clear()

by_class = {}
for r in rows:
    c = r['class']
    e = by_class.setdefault(c, {'tris': 0, 'area_m2': 0.0, 'zmin': 1e30, 'n': 0, 'names': []})
    e['tris'] += r['tris']
    e['area_m2'] = round(e['area_m2'] + r['area_m2'], 6)
    e['zmin'] = min(e['zmin'], r['wmin'][2])
    e['n'] += 1
    e['names'].append(r['name'])

tyres = [r for r in rows if r['class'] == 'tyre']
tyre_ground = {
    'n_tyre_objects': len(tyres),
    'per_tyre_world_zmin_m': {r['name']: r['wmin'][2] for r in tyres},
    'max_tyre_zmin_m': (max(r['wmin'][2] for r in tyres) if tyres else None),
    'min_tyre_zmin_m': (min(r['wmin'][2] for r in tyres) if tyres else None),
    'note': 'grounding is judged from the WORST tyre (max of per-tyre z-min), '
            'not from the whole-model bbox minimum.',
}

out = {
    'label': LABEL,
    'source': os.path.basename(SRC),
    'blender': bpy.app.version_string,
    'objects_total': len(bpy.context.scene.objects),
    'mesh_objects': len(objs),
    'materials': len(bpy.data.materials),
    'images': len(bpy.data.images),
    'cameras': len([o for o in bpy.context.scene.objects if o.type == 'CAMERA']),
    'lights': len([o for o in bpy.context.scene.objects if o.type == 'LIGHT']),
    'triangles': tot_tris,
    'vertices': tot_verts,
    'world_bbox_min': [round(v, 6) for v in gmin],
    'world_bbox_max': [round(v, 6) for v in gmax],
    'world_bbox_size': [round(gmax[k] - gmin[k], 6) for k in range(3)],
    'negative_det_objects': [r['name'] for r in rows if r['det'] < 0],
    'hidden_at_render': [r['name'] for r in rows if r['hide_render']],
    'by_class': by_class,
    'tyre_ground': tyre_ground,
    'objects': rows,
}
with open(DST, 'w') as f:
    json.dump(out, f, indent=1)
print('BL_AUDIT objs=%d tris=%d bbox=%s..%s' % (len(objs), tot_tris,
                                                out['world_bbox_min'], out['world_bbox_max']))
print('BL_AUDIT tyre zmins: %s' % tyre_ground['per_tyre_world_zmin_m'])
