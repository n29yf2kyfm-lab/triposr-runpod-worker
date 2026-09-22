"""Convert ONE catalogue car into a Strip Bay car. Any family, one tool.

    blender -b --python sb_convert.py -- in.glb out.glb report.json

Output nodes are named `SB_<partId>__<n>` in the app's frame (+Y up, NOSE +Z,
car's LEFT +X, ground Y=0), which the app reads as convention 4 with no
per-car rules. Hinges, the paint material and every decision go in the report.

WHAT THE NAMES ARE TRUSTED FOR, AND WHAT THEY ARE NOT.
A name is trusted to say WHAT a part is — "this is a door", "this is the
bonnet". It is NOT trusted to say WHICH door: corners come from where the
part SITS after the frame is fixed. Every family spells corners differently
(FL, lf, dside_f, front_left, L1) and some rigs mirror them; position cannot
be misspelt. The same goes for wheels.

FAMILIES this was written against, all measured in the catalogue:
  game rig    skinned, one bone per part (Audi A6, Peugeot 308/508, M235i).
              Baked first: each mesh follows ONE bone at weight 1.0, so the
              skin carries no deformation and applying it changes nothing.
  sim-mod     `xc90_door_FL`, `hood`, `trunk`, `tailgate` (XC90, Panamera,
              Rolls-Royce Ghost, Fiat Tipo, Golf Mk6, CLS...).
  GTA-style   `door_lf_dummy` > `door_lf_ok`, `bonnet_dummy`, `boot_dummy`,
              with `_dam` damage twins that MUST be dropped or they z-fight
              with the good panels (Tesla Model 3, Superb, SX4, Amarok...).

REFUSES (writes nothing, exit 2) rather than shipping a car whose teardown
would silently not work: no doors, not four wheels, wheels above the glass,
or a frame it cannot decide.
"""
import bpy, bmesh, sys, json, re, math
from mathutils import Vector, Matrix

a = sys.argv[sys.argv.index('--') + 1:]
src, dst, outj = a[0], a[1], a[2]
rep = {'src': src.rsplit('/', 1)[-1]}
def refuse(msg):
    rep['refused'] = msg; json.dump(rep, open(outj, 'w'), indent=1)
    print('SB_REFUSED', msg); sys.exit(2)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)
bpy.context.view_layer.update()

# ── 0. BAKE any rigid skin (game rigs) ────────────────────────────────
arms = [o for o in bpy.data.objects if o.type == 'ARMATURE']
baked = 0
for o in list(bpy.data.objects):
    if o.type != 'MESH': continue
    mods = [m for m in o.modifiers if m.type == 'ARMATURE']
    if not mods: continue
    used = {}
    for v in o.data.vertices:
        for g in v.groups:
            if g.weight > 0:
                n = o.vertex_groups[g.group].name; used[n] = used.get(n, 0) + 1
    if len(used) > 1:
        refuse(f'{o.name} is skinned to {len(used)} bones — a deforming rig, not a parts rig')
    bpy.context.view_layer.objects.active = o
    for m in mods: bpy.ops.object.modifier_apply(modifier=m.name)
    o.vertex_groups.clear()
    if used: o['sb_bone'] = next(iter(used))      # the part is the BONE, not the mesh
    baked += 1
rep['baked'] = baked

# the name chain a part is judged by: bone (if baked), own name, then ancestors
def chain(o):
    out = []
    if 'sb_bone' in o: out.append(o['sb_bone'])
    n = o
    while n is not None:
        out.append(n.name); n = n.parent
    return out

# ── 1. DROP what must not render: damage twins, low LODs, shadow proxies ─
DROP = re.compile(r'(_dam\b|_dam[_.\d]|_vlo\b|_vlo[_.]|\blod[1-9]\b|_lod[1-9]|shadow|_l[12]_end|collision|\bcol_)', re.I)
dropped = 0
for o in list(bpy.data.objects):
    if o.type == 'MESH' and any(DROP.search(n) for n in chain(o)[:3]):
        bpy.data.objects.remove(o); dropped += 1
# default primitives left in the export — the A6 carries an `Icosphere`
# 0.7 m BELOW its own tyres that read as part of the car
PRIM = re.compile(r'^(icosphere|uv ?sphere|sphere|cube|plane|cylinder|cone|torus)(\.\d+)?$', re.I)
for o in list(bpy.data.objects):
    if o.type == 'MESH' and PRIM.match(o.name):
        bpy.data.objects.remove(o); dropped += 1
rep['dropped'] = dropped

# flatten: every mesh keeps its world pose, then the rig goes
for o in bpy.data.objects:
    o['sb_chain'] = '|'.join(chain(o))
for o in bpy.data.objects:
    if o.type == 'MESH' and o.parent is not None:
        mw = o.matrix_world.copy(); o.parent = None; o.matrix_world = mw
for o in [o for o in bpy.data.objects if o.type != 'MESH']:
    bpy.data.objects.remove(o)
objs = [o for o in bpy.data.objects if o.type == 'MESH' and len(o.data.vertices)]
if not objs: refuse('no geometry')

def G(v): return Vector((v.x, v.z, -v.y))           # Blender Z-up -> glTF Y-up
def wv(o): return [G(o.matrix_world @ v.co) for v in o.data.vertices]
def bbox(vs):
    return (Vector((min(v.x for v in vs), min(v.y for v in vs), min(v.z for v in vs))),
            Vector((max(v.x for v in vs), max(v.y for v in vs), max(v.z for v in vs))))
def centre(os_):
    vs = [v for o in os_ for v in wv(o)]; return sum(vs, Vector()) / len(vs)

# ── 2. WHAT each mesh is, from its name chain (nearest name wins) ─────
R = [
  ('steering', r'steer'),
  ('door',     r'(^|[^a-z])door(?!_?(mirror|handle_int|light_int|seal_body|frame_body|jamb|sill|step|trim_body|opening))|doorf|doorr|door_?[lr][fr]'),
  # no word boundary before hood: variants are GLUED (`carbonhood`), and a
  # variant left behind z-fights under the one that lifts (BMW M6)
  ('bonnet',   r'(hood|bonnet)(?!_?(piston|strut|latch|ornament|release|prop|scoop_body|vent_body|ie))'),
  ('tailgate', r'(^|[^a-z])(trunk|tailgate|hatch|bootlid|boot)(?!_?(divider|floor|panel|carpet|cam|liner|light_body|piston|strut|latch))'),
  ('wheel',    r'(^|[^a-z])(wheel|tyre|tire|rim)(?!_?(arch|house|well|cover|liner|trim_body|lip_body))'),
  # lamps BEFORE glazing, or `headlight_glass` becomes a window
  ('lamps_front', r'headl|foglight|extralight|(^|[^a-z])drl'),
  ('lamps_rear',  r'taill|brakel|reversingl|rearlight'),
  ('glazing',  r'windscreen|windshield|glass|window|vitre|(^|[^a-z])glaz'),
  # NOT `chassis`: a GTA-style car's `chassis` is its whole BODY SHELL, while
  # a game rig's is the floor and cabin. It means nothing reliable.
  ('cabin',    r'interior|seat|dash|carpet|console|headlin|pedal|gauge|speedo'),
  ('engine',   r'engine|engbay|intake|turbo|intercooler|radiator|airbox'),
]
R = [(k, re.compile(p, re.I)) for k, p in R]
SHIFTER_BOOT = re.compile(r'shifter_?boot|gear_?boot|gaiter', re.I)
def kind(o):
    for n in o['sb_chain'].split('|'):
        if SHIFTER_BOOT.search(n): return 'cabin'
        for k, rx in R:
            if rx.search(n): return k
    return 'body'
K = {o: kind(o) for o in objs}

# ── 3. FRAME: length along Z, nose +Z, up +Y, left +X, ground 0 ───────
allv = [v for o in objs for v in wv(o)]
lo, hi = bbox(allv)
if (hi.x - lo.x) > (hi.z - lo.z):                   # length lies on X: turn 90
    Rz = Matrix.Rotation(math.radians(90), 4, 'Z')
    for o in objs: o.matrix_world = Rz @ o.matrix_world
    bpy.context.view_layer.update(); rep['turn90'] = True
wheels = [o for o in objs if K[o] == 'wheel']
glass = [o for o in objs if K[o] == 'glazing']
if not wheels: refuse('no wheels named')
if glass and centre(wheels).y > centre(glass).y: refuse('wheels sit ABOVE the glass — upside down')
# nose: the end the bonnet is at; failing that, the end the steering wheel is nearer
cues = {}
bon = [o for o in objs if K[o] == 'bonnet']; tg = [o for o in objs if K[o] == 'tailgate']
st = [o for o in objs if K[o] == 'steering']
allv = [v for o in objs for v in wv(o)]; lo, hi = bbox(allv); mid = (lo + hi) / 2
if bon and tg: cues['bonnet_vs_boot'] = 1 if centre(bon).z > centre(tg).z else -1
if st: cues['steering'] = 1 if centre(st).z > mid.z else -1
hl = [o for o in objs if K[o] == 'lamps_front']; tl = [o for o in objs if K[o] == 'lamps_rear']
if hl and tl: cues['head_vs_tail_lamps'] = 1 if centre(hl).z > centre(tl).z else -1
if not cues: refuse('cannot decide the nose: no bonnet/boot pair, no lamps and no steering wheel')
# PRIORITY, not a vote. The steering wheel is the WEAKEST cue: it sits
# ahead of the car's midpoint on most cars and BEHIND it on a long-bonnet
# coupe — the GR Supra was refused for exactly that disagreement. The two
# ends of the car (bonnet vs boot, headlamps vs tail lamps) outrank it, and
# must not contradict each other.
ends = [cues[k] for k in ('bonnet_vs_boot', 'head_vs_tail_lamps') if k in cues]
if len(set(ends)) > 1: refuse(f'the two end cues disagree: {cues}')
nose = ends[0] if ends else cues['steering']
if len(set(cues.values())) > 1: rep['nose_overruled'] = cues
if nose < 0:
    R180 = Matrix.Rotation(math.pi, 4, 'Z')
    for o in objs: o.matrix_world = R180 @ o.matrix_world
    bpy.context.view_layer.update()
ground = min(v.y for o in wheels for v in wv(o))
T = Matrix.Translation((0, 0, -ground))
for o in objs: o.matrix_world = T @ o.matrix_world
bpy.context.view_layer.update()
allv = [v for o in objs for v in wv(o)]; lo, hi = bbox(allv); mid = (lo + hi) / 2
rep['frame'] = {'nose_cues': cues, 'yaw180': nose < 0, 'ground_shift': round(-ground, 4),
                'extent': [round(hi.x - lo.x, 3), round(hi.y - lo.y, 3), round(hi.z - lo.z, 3)]}
if st:
    rep['frame']['drive'] = 'LHD' if centre(st).x > 0 else 'RHD'
low = sorted(objs, key=lambda o: min(v.y for v in wv(o)))[:3]
rep['frame']['lowest'] = [(o['sb_chain'][:60], round(min(v.y for v in wv(o)), 3)) for o in low]

# ── 4. CORNERS by position ────────────────────────────────────────────
parts = {}
def put(pid, o): parts.setdefault(pid, []).append(o)
# doors: cluster by part root (the chain's door-matching name), then corner
doorkey = {}
for o in objs:
    if K[o] != 'door': continue
    root = next(n for n in o['sb_chain'].split('|') if R[1][1].search(n))
    root = re.sub(r'(_ok|_dummy|__\d+|\.\d+|_\d+)$', '', root, flags=re.I)
    doorkey.setdefault(root, []).append(o)
# a "door" cluster that is a thin trim strip is not a door: keep the big ones
dclusters = sorted(doorkey.values(), key=lambda os_: -sum(len(o.data.vertices) for o in os_))
DOOR = {}
for os_ in dclusters:
    c = centre(os_)
    side = 'l' if c.x > 0 else 'r'
    # front vs rear: a two-door car has only fronts; decide per side below
    DOOR.setdefault(side, []).append((c.z, os_))
for side, lst in DOOR.items():
    lst.sort(key=lambda t: -t[0])                  # most forward first
    size = lambda t: sum(len(o.data.vertices) for o in t[1])
    biggest = max(size(t) for t in lst)
    # ANCHORS ARE THE TWO LARGEST clusters, not the two most forward: on the
    # BMW M6 a door-glass cluster sat just behind the front door skin, took
    # the second anchor slot, failed the gap test, and the rear door was
    # merged into the front one — both swung open as a single 2 m panel.
    bysize = sorted(lst, key=size, reverse=True)
    anchors = [bysize[0][0]]
    for t in bysize[1:]:
        if size(t) > 0.35 * biggest and abs(t[0] - anchors[0]) > 0.35:
            anchors.append(t[0]); break
    anchors.sort(reverse=True)                     # front first
    for z, os_ in lst:
        k = min(range(len(anchors)), key=lambda i: abs(anchors[i] - z))
        for o in os_: put(f"door_{'fr'[k]}{side}", o)
nd = sum(1 for k in parts if k.startswith('door_'))
if nd < 2: refuse(f'only {nd} door part(s) found')
for o in wheels:
    c = centre([o]); put('wheel_' + ('f' if c.z > mid.z else 'r') + ('l' if c.x > 0 else 'r'), o)
if sorted(k for k in parts if k.startswith('wheel_')) != ['wheel_fl', 'wheel_fr', 'wheel_rl', 'wheel_rr']:
    refuse(f"wheels do not fill four corners: {[k for k in parts if k.startswith('wheel_')]}")
for o in objs:
    k = K[o]
    if k in ('door', 'wheel'): continue
    put({'bonnet': 'panel_bonnet'}.get(k, k), o)

# glass and handles INSIDE a door's box travel with the door
for pid in [k for k in parts if k.startswith('door_')]:
    b0, b1 = bbox([v for o in parts[pid] for v in wv(o)])
    for other in ('glazing', 'body'):
        keep = []
        for o in parts.get(other, []):
            c = centre([o]); ob0, ob1 = bbox(wv(o))
            inside = all(b0[i] - .02 <= ob0[i] and ob1[i] <= b1[i] + .02 for i in range(3))
            (parts[pid] if inside else keep).append(o)
        if other in parts: parts[other] = keep

# ── 5. PAINT: the material covering most of the bonnet (or the doors) ─
def mat_area(os_):
    A = {}
    for o in os_:
        sc = o.matrix_world.to_scale(); s = abs(sc.x * sc.y * sc.z) ** (2 / 3)
        for p in o.data.polygons:
            if p.material_index < len(o.material_slots) and o.material_slots[p.material_index].material:
                m = o.material_slots[p.material_index].material; A[m] = A.get(m, 0) + p.area * s
    return A
src_paint = parts.get('panel_bonnet') or [o for k in parts if k.startswith('door_') for o in parts[k]]
A = mat_area(src_paint)
paint = max(A, key=A.get) if A else None
if paint:
    rep['paint'] = {'material': paint.name, 'from': 'bonnet' if parts.get('panel_bonnet') else 'doors',
                    'share': round(A[paint] / sum(A.values()), 3)}
    if 'paint' not in paint.name.lower():
        paint.name = paint.name + '_paint'     # the app finds paint by this word
        rep['paint']['renamed'] = paint.name

# ── 6. BONNET / BOOT from the paint mesh if no part carries them ──────
def islands(o):
    bm = bmesh.new(); bm.from_mesh(o.data); bm.faces.ensure_lookup_table()
    tag = bm.faces.layers.int.new('orig')
    for f in bm.faces: f[tag] = f.index
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5); bm.faces.ensure_lookup_table()
    seen, comps = set(), []
    for f in bm.faces:
        if f.index in seen: continue
        st_, comp = [f], []; seen.add(f.index)
        while st_:
            g = st_.pop(); comp.append(g)
            for e in g.edges:
                for h in e.link_faces:
                    if h.index not in seen: seen.add(h.index); st_.append(h)
        mw = o.matrix_world; n3 = mw.to_3x3()
        vs = [G(mw @ v.co) for g in comp for v in g.verts]
        area = sum(g.calc_area() for g in comp)
        up = sum(G(n3 @ g.normal).y * g.calc_area() for g in comp) / max(area, 1e-9)
        comps.append((bbox(vs), up, [g[tag] for g in comp]))
    bm.free(); return comps
def lift(o, fidx, pid):
    att = o.data.attributes.new('sb_lift', 'INT', 'FACE')
    for i in fidx: att.data[i].value = 1
    bpy.ops.object.select_all(action='DESELECT')
    bpy.context.view_layer.objects.active = o; o.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT'); bpy.ops.mesh.select_mode(type='FACE')
    bpy.ops.mesh.select_all(action='DESELECT')
    ebm = bmesh.from_edit_mesh(o.data); lay = ebm.faces.layers.int['sb_lift']
    for f in ebm.faces:
        if f[lay] == 1: f.select_set(True)
    ebm.select_flush_mode(); bmesh.update_edit_mesh(o.data)
    bpy.ops.mesh.separate(type='SELECTED'); bpy.ops.object.mode_set(mode='OBJECT')
    new = [x for x in bpy.context.selected_objects if x is not o][0]
    o.data.attributes.remove(o.data.attributes['sb_lift'])
    put(pid, new); return new
need = [p for p in ('panel_bonnet', 'tailgate') if not parts.get(p)]
if need and paint:
    L, W, H = hi.z - lo.z, hi.x - lo.x, hi.y - lo.y
    for o in list(parts.get('body', [])):
        if not any(s.material is paint for s in o.material_slots): continue
        progress = True
        while need and progress:           # re-read islands after every lift:
            progress = False               # face indices shift when one is cut
            comps = islands(o)
            for pid in list(need):
                cand = [c for c in comps if (c[0][1].x - c[0][0].x) > .6 * W and c[0][0].y > lo.y + .25 * H
                        and abs(c[1]) > .55 and (c[0][1].z > hi.z - .15 * L if pid == 'panel_bonnet'
                                                   else c[0][0].z < lo.z + .15 * L)]
                rep.setdefault('island_candidates', {})[pid] = len(cand)
                if len(cand) == 1:
                    lift(o, cand[0][2], pid); need.remove(pid)
                    rep.setdefault('lifted', {})[pid] = len(cand[0][2])
                    progress = True; break
        if not need: break
rep['missing'] = [p for p in ('panel_bonnet', 'tailgate') if not parts.get(p)]

# ── 7. HINGES from the parts ──────────────────────────────────────────
hinge = {}
for pid in [k for k in parts if k.startswith('door_')]:
    vs = [v for o in parts[pid] for v in wv(o)]; b0, b1 = bbox(vs)
    edge = [v for v in vs if v.z > b1.z - .06]
    xs = sorted(abs(v.x) for v in edge); x = xs[int(.9 * (len(xs) - 1))]
    hinge[pid] = {'x': round(x if pid[-1] == 'l' else -x, 4), 'y': round((b0.y + b1.y) / 2, 4), 'z': round(b1.z, 4)}
if parts.get('panel_bonnet'):
    vs = [v for o in parts['panel_bonnet'] for v in wv(o)]; b0, b1 = bbox(vs)
    hinge['panel_bonnet'] = {'x': 0, 'y': round(max(v.y for v in vs if v.z < b0.z + .06), 4), 'z': round(b0.z, 4)}
if parts.get('tailgate'):
    vs = [v for o in parts['tailgate'] for v in wv(o)]; b0, b1 = bbox(vs)
    hinge['tailgate'] = {'x': 0, 'y': round(max(v.y for v in vs if v.z > b1.z - .06), 4), 'z': round(b1.z, 4)}
rep['hinge'] = hinge

# ── 8. GLASS: say what the file claims, the render decides ────────────
gm = {}
for o in parts.get('glazing', []) + [o for k in parts if k.startswith('door_') for o in parts[k]]:
    for s in o.material_slots:
        m = s.material
        if m and re.search(r'glass|window|vitre|screen', m.name, re.I):
            gm[m.name] = m.blend_method if hasattr(m, 'blend_method') else '?'
rep['glass_materials'] = gm

# ── 9. NAME and EXPORT ────────────────────────────────────────────────
for pid, os_ in parts.items():
    for k, o in enumerate(os_):
        o.name = f'SB_{pid}__{k}'; o.data.name = o.name
rep['parts'] = {k: len(v) for k, v in sorted(parts.items())}
json.dump(rep, open(outj, 'w'), indent=1)
bpy.ops.export_scene.gltf(filepath=dst, export_format='GLB', export_normals=True,
                          export_skins=False, export_animations=False, export_apply=True)
print('SB_DONE', json.dumps(rep['parts']), 'missing', rep['missing'])
