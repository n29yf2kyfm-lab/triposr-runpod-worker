"""Turn a baked game-rig car into Strip Bay's canonical part names and frame.

    blender -b --python rig_canon.py -- baked.glb out.glb canon.json

Input is bake_rig.py's output: one static object per former bone, named
`<bone>__<n>`. Output nodes are named `SB_<partId>__<n>`, where partId is the
app's own vocabulary (door_fl, panel_bonnet, tailgate, wheel_rl, glazing,
cabin, steering, lamps_front, ...). The app then needs no per-car rules at
all — convention 4 just reads the id off the name.

FRAME. Strip Bay's frame is +Y up, NOSE +Z, car's LEFT +X, ground at Y=0.
The nose end is decided from the file, not assumed: it is the end the
windscreen leans toward (windscreen centroid vs rear-screen centroid). The
car's left is then decided by the DRIVER'S DOOR: a game rig names doors
`dside`/`pside`, and the steering wheel says which side the driver sits.
Both are printed so a wrong frame is visible in the log.

PANELS. A game rig often carries the bonnet and boot lid as LOOSE PIECES
inside the paint mesh — no bone of their own, but not welded either. They
are found as connected components of the paint and gated on shape (width,
height band, facing up, which end). The tool REFUSES unless exactly one
component passes each gate; a panel guessed wrong is worse than no panel.

HINGES are derived from the part itself and written to canon.json:
  door      forward edge, at the outer skin
  bonnet    rear edge (the scuttle end), top surface
  boot lid  forward edge (the rear-screen end), top surface
"""
import bpy, bmesh, sys, json, re
from mathutils import Vector, Matrix
import math

a = sys.argv[sys.argv.index('--') + 1:]
src, dst, outj = a[0], a[1], a[2]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)
objs = [o for o in bpy.data.objects if o.type == 'MESH']
log = {}

def wverts(o):
    return [o.matrix_world @ v.co for v in o.data.vertices]
def G(v):          # Blender (x,y,z) Z-up  ->  glTF (x, z, -y) Y-up
    return Vector((v.x, v.z, -v.y))
def bbox(vs):
    return (Vector((min(v.x for v in vs), min(v.y for v in vs), min(v.z for v in vs))),
            Vector((max(v.x for v in vs), max(v.y for v in vs), max(v.z for v in vs))))
bone = lambda o: re.sub(r'__\d+$', '', o.name).split('.child')[0]

# ── 1. FRAME, measured in glTF space ──────────────────────────────────
def cen(pred):
    vs = [G(v) for o in objs if pred(bone(o)) for v in wverts(o)]
    assert vs, 'no geometry matched'
    return sum(vs, Vector()) / len(vs), vs
ws, _ = cen(lambda b: b.startswith('windscreen') and not b.startswith('windscreen_r'))
rs, _ = cen(lambda b: b.startswith('windscreen_r'))
nose_sign = 1 if ws.z > rs.z else -1          # windscreen is the NOSE end
sw, _ = cen(lambda b: b.startswith('steeringwheel'))
dfd, _ = cen(lambda b: b.startswith('door_dside_f'))
assert (sw.x > 0) == (dfd.x > 0), 'steering wheel and driver door disagree on side'
# after the yaw, is the driver on the car's LEFT (+X)? left = +X when nose = +Z
yaw = 0 if nose_sign > 0 else 180
drv_x_after = dfd.x if yaw == 0 else -dfd.x
driver_side = 'left' if drv_x_after > 0 else 'right'
log['frame'] = {'windscreen_z': round(ws.z, 3), 'rearscreen_z': round(rs.z, 3),
                'yaw_deg': yaw, 'driver_side': driver_side,
                'steering_x_after': round(sw.x if yaw == 0 else -sw.x, 3)}
print('CANON frame', log['frame'])

# apply the yaw (about glTF Y == Blender Z) and ground at Y=0
R = Matrix.Rotation(math.radians(yaw), 4, 'Z')
for o in objs:
    o.matrix_world = R @ o.matrix_world
bpy.context.view_layer.update()
allv = [G(v) for o in objs for v in wverts(o)]
lo, hi = bbox(allv)
ground = min(G(v).y for o in objs if bone(o).startswith('wheel') for v in wverts(o))
T = Matrix.Translation((0, 0, -ground))       # Blender Z is glTF Y
for o in objs:
    o.matrix_world = T @ o.matrix_world
bpy.context.view_layer.update()
log['ground_shift'] = round(-ground, 4)

# ── 2. NAMES ──────────────────────────────────────────────────────────
D = {'dside': 'l' if driver_side == 'left' else 'r'}
D['pside'] = 'r' if D['dside'] == 'l' else 'l'
def canon(b):
    m = re.match(r'door_(dside|pside)_([fr])', b) or re.match(r'handle_(dside|pside)_([fr])', b)
    if m: return f'door_{m.group(2)}{D[m.group(1)]}'
    m = re.match(r'(?:window|doorlight)_([lr])([fr])', b)       # window_lf = left front
    if m: return f'door_{m.group(2)}{m.group(1)}'
    if b.startswith('windscreen') or b.startswith('windows'): return 'glazing'
    if b.startswith('steeringwheel'): return 'steering'
    if b.startswith('chassis') or b.startswith('bodyshell.001'): return 'cabin'
    if re.match(r'headlight|extralight|indicator_[lr]f', b): return 'lamps_front'
    if re.match(r'taillight|brakelight|reversinglight|indicator_[lr]r', b): return 'lamps_rear'
    if b.startswith('wheel'): return 'wheel'                    # cornered below
    return 'body'
parts = {}
for o in objs:
    parts.setdefault(canon(bone(o)), []).append(o)

# wheels into corners by POSITION (all four are instances named _lf)
for o in parts.pop('wheel'):
    c = sum((G(v) for v in wverts(o)), Vector()) / len(o.data.vertices)
    parts.setdefault('wheel_' + ('f' if c.z > 0 else 'r') + ('l' if c.x > 0 else 'r'), []).append(o)

# ── 3. PANELS out of the paint mesh ───────────────────────────────────
paint = [o for o in parts['body'] if any(s.material and 'paint' in s.material.name.lower()
                                          for s in o.material_slots)]
assert len(paint) == 1, f'expected one paint object, found {[o.name for o in paint]}'
paint = paint[0]
allv = [G(v) for o in objs for v in wverts(o)]
lo, hi = bbox(allv); L = hi.z - lo.z; W = hi.x - lo.x; H = hi.y - lo.y
bm = bmesh.new(); bm.from_mesh(paint.data); bm.faces.ensure_lookup_table()
tag = bm.faces.layers.int.new('orig')
for f in bm.faces: f[tag] = f.index
bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)   # weld seams for ISLANDS only
bm.faces.ensure_lookup_table()
mw = paint.matrix_world; nmw = mw.to_3x3()
seen, comps = set(), []
for f in bm.faces:
    if f.index in seen: continue
    stack, comp = [f], []
    seen.add(f.index)
    while stack:
        g = stack.pop(); comp.append(g)
        for e in g.edges:
            for h in e.link_faces:
                if h.index not in seen: seen.add(h.index); stack.append(h)
    comps.append(comp)
def shape(comp):
    vs = [G(mw @ v.co) for f in comp for v in f.verts]
    b0, b1 = bbox(vs)
    area = sum(f.calc_area() for f in comp)
    up = sum(G(nmw @ f.normal).y * f.calc_area() for f in comp) / max(area, 1e-9)
    return b0, b1, up
cands = {'panel_bonnet': [], 'tailgate': []}
info = []
for i, comp in enumerate(comps):
    b0, b1, up = shape(comp)
    info.append((b0, b1, [f[tag] for f in comp]))
    wide = (b1.x - b0.x) > 0.6 * W
    high = b0.y > lo.y + 0.25 * H             # above the bumpers
    topish = abs(up) > 0.55                   # mostly facing up (either winding)
    if not (wide and high and topish): continue
    if b1.z > hi.z - 0.15 * L: cands['panel_bonnet'].append(i)
    elif b0.z < lo.z + 0.15 * L: cands['tailgate'].append(i)
bm.free()
log['panel_candidates'] = {k: [len(info[i][2]) for i in v] for k, v in cands.items()}
print('CANON panels', log['panel_candidates'])
for k, v in cands.items():
    assert len(v) == 1, f'REFUSED: {k} has {len(v)} candidate components, need exactly 1'
# split each chosen island off the paint by its ORIGINAL face indices —
# the weld above was only to find islands; the written mesh is not welded.
# Indices are stamped into a face attribute FIRST, because separating the
# bonnet renumbers every face after it and the boot lid's indices go stale
# (measured: index 20747 out of range on the second panel).
att = paint.data.attributes.new('sb_panel', 'INT', 'FACE')
PID = {pid: k + 1 for k, pid in enumerate(cands)}
for pid, (ci,) in cands.items():
    for fi in info[ci][2]: att.data[fi].value = PID[pid]
for pid, (ci,) in cands.items():
    b0, b1, fidx = info[ci]
    want = set(fidx)
    bpy.ops.object.select_all(action='DESELECT')
    bpy.context.view_layer.objects.active = paint; paint.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_mode(type='FACE')
    bpy.ops.mesh.select_all(action='DESELECT')
    # selection is set on the EDIT bmesh — flags written in object mode are
    # not what edit mode reads, and the first run separated the whole paint
    ebm = bmesh.from_edit_mesh(paint.data); ebm.faces.ensure_lookup_table()
    lay = ebm.faces.layers.int['sb_panel']
    for f in ebm.faces:
        if f[lay] == PID[pid]: f.select_set(True)
    ebm.select_flush_mode(); bmesh.update_edit_mesh(paint.data)
    assert sum(f.select for f in ebm.faces) == len(want)
    bpy.ops.mesh.separate(type='SELECTED')
    bpy.ops.object.mode_set(mode='OBJECT')
    new = [o for o in bpy.context.selected_objects if o is not paint][0]
    nv = [G(v) for v in wverts(new)]; n0, n1 = bbox(nv)
    assert len(new.data.polygons) == len(want), f'{pid}: separated {len(new.data.polygons)} faces, wanted {len(want)}'
    assert (n1 - n0 - (b1 - b0)).length < 0.01, f'{pid}: separated piece does not match the island'
    parts.setdefault(pid, []).append(new)
    log.setdefault('panels', {})[pid] = {'faces': len(new.data.polygons),
        'min': [round(x, 3) for x in n0], 'max': [round(x, 3) for x in n1]}
print('CANON panels cut', log['panels'])

# ── 4. HINGES from the parts ──────────────────────────────────────────
hinge = {}
for pid in ('door_fl', 'door_fr', 'door_rl', 'door_rr'):
    vs = [G(v) for o in parts[pid] for v in wverts(o)]
    b0, b1 = bbox(vs)
    edge = [v for v in vs if v.z > b1.z - 0.06]            # the forward edge
    xs = sorted(abs(v.x) for v in edge)
    x = xs[int(0.9 * (len(xs) - 1))] * (1 if pid[-1] == 'l' else -1)
    hinge[pid] = {'x': round(x, 4), 'y': round((b0.y + b1.y) / 2, 4), 'z': round(b1.z, 4)}
vs = [G(v) for o in parts['panel_bonnet'] for v in wverts(o)]; b0, b1 = bbox(vs)
hinge['panel_bonnet'] = {'x': 0, 'y': round(max(v.y for v in vs if v.z < b0.z + 0.06), 4), 'z': round(b0.z, 4)}
vs = [G(v) for o in parts['tailgate'] for v in wverts(o)]; b0, b1 = bbox(vs)
hinge['tailgate'] = {'x': 0, 'y': round(max(v.y for v in vs if v.z > b1.z - 0.06), 4), 'z': round(b1.z, 4)}
log['hinge'] = hinge
print('CANON hinges', hinge)

# ── 5. NAME and EXPORT ────────────────────────────────────────────────
for pid, os_ in parts.items():
    for k, o in enumerate(os_):
        o.name = f'SB_{pid}__{k}'; o.data.name = o.name
log['parts'] = {k: len(v) for k, v in parts.items()}
allv = [G(v) for o in bpy.data.objects if o.type == 'MESH' for v in wverts(o)]
lo, hi = bbox(allv)
log['extent'] = {'min': [round(x, 3) for x in lo], 'max': [round(x, 3) for x in hi]}
json.dump(log, open(outj, 'w'), indent=1)
bpy.ops.export_scene.gltf(filepath=dst, export_format='GLB', export_normals=True,
                          export_skins=False, export_animations=False)
print('CANON_DONE', log['parts'])
