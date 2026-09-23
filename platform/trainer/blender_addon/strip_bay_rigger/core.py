"""Strip Bay rigger — the conversion itself. One car in, one rigged car out.

`convert(objects, rep)` works on the objects ONE glTF import created and on
nothing else, so it is safe inside an artist's open scene. It returns
`(parts, hinge)` and fills `rep` with every decision it made; it raises
`Refused` rather than guess. `process_file()` wraps it with import/export for
the batch runner and the command line.

Output nodes are named `SB_<partId>__<n>` in Strip Bay's frame (+Y up, NOSE +Z,
car's LEFT +X, ground Y=0 — in glTF terms; Blender shows the same car Z-up).

WHAT THE NAMES ARE TRUSTED FOR, AND WHAT THEY ARE NOT.
A name is trusted to say WHAT a part is — "this is a door", "this is the
bonnet". It is NOT trusted to say WHICH door: corners come from where the part
SITS after the frame is fixed. Every family spells corners differently (FL,
lf, dside_f, front_left, L1) and some rigs mirror them; position cannot be
misspelt. The same goes for wheels.

FAMILIES this was written against, all measured in the catalogue:
  game rig    skinned, one bone per part (Audi A6, Peugeot 308/508, M235i).
              Baked first: each mesh follows ONE bone at weight 1.0, so the
              skin carries no deformation and applying it changes nothing.
  sim-mod     `xc90_door_FL`, `hood`, `trunk`, `tailgate` (XC90, Panamera,
              Rolls-Royce Ghost, Fiat Tipo, CLS...).
  GTA-style   `door_lf_dummy` > `door_lf_ok`, `bonnet_dummy`, `boot_dummy`,
              with `_dam` damage twins that MUST be dropped or they z-fight
              with the good panels (Superb, Amarok, Micra...).

REFUSES rather than shipping a car whose teardown would silently not work:
no doors, not four road wheels, wheels above the glass, or a frame it cannot
decide. Of the 1,044 catalogue cars a survey found ~40 with separately named
doors; a car whose doors are welded into its body shell cannot be opened by
any renaming, and is refused, not cut along a guessed line.
"""
import bpy, bmesh, json, re, math, os
from mathutils import Vector, Matrix

VERSION = '1.0.0'


class Refused(Exception):
    """The car cannot be rigged safely. The message says why."""


# ── helpers ─────────────────────────────────────────────────────────────
def G(v):
    """Blender (x, y, z) Z-up  ->  glTF (x, z, -y) Y-up."""
    return Vector((v.x, v.z, -v.y))


def B(v):
    """glTF (x, y, z) Y-up  ->  Blender (x, -z, y) Z-up."""
    return Vector((v[0], -v[2], v[1]))


def wv(o):
    return [G(o.matrix_world @ v.co) for v in o.data.vertices]


def bbox(vs):
    return (Vector((min(v.x for v in vs), min(v.y for v in vs), min(v.z for v in vs))),
            Vector((max(v.x for v in vs), max(v.y for v in vs), max(v.z for v in vs))))


def centre(os_):
    vs = [v for o in os_ for v in wv(o)]
    return sum(vs, Vector()) / len(vs)


# ── what each mesh is, from its name chain (nearest name wins) ──────────
RULES = [
    ('steering', r'steer'),
    ('door',     r'(^|[^a-z])door(?!_?(mirror|handle_int|light_int|seal_body|frame_body|jamb|sill|step|trim_body|opening))|doorf|doorr|door_?[lr][fr]'),
    # no word boundary before hood: variants are GLUED (`carbonhood`), and a
    # variant left behind z-fights under the one that lifts (BMW M6)
    ('bonnet',   r'(hood|bonnet)(?!_?(piston|strut|latch|ornament|release|prop|scoop_body|vent_body|ie))'),
    ('tailgate', r'(^|[^a-z])(trunk|tailgate|hatch|bootlid|boot)(?!_?(divider|floor|panel|carpet|cam|liner|light_body|piston|strut|latch))'),
    ('wheel',    r'(^|[^a-z])(wheel|tyre|tire|rim)(?!_?(arch|house|well|cover|liner|trim_body|lip_body))'
                 # abbreviated corners: `wfl_0`, `wrr_3` (Mercedes Vito), `whl_fl`
                 r'|(^|[^a-z])(w[fr][lr]|whl)([^a-z]|$)'),
    # lamps BEFORE glazing, or `headlight_glass` becomes a window
    ('lamps_front', r'headl|foglight|extralight|(^|[^a-z])drl'),
    ('lamps_rear',  r'taill|brakel|reversingl|rearlight'),
    ('glazing',  r'windscreen|windshield|glass|window|vitre|(^|[^a-z])glaz'),
    # NOT `chassis`: a GTA-style car's `chassis` is its whole BODY SHELL, while
    # a game rig's is the floor and cabin. It means nothing reliable.
    ('cabin',    r'interior|seat|dash|carpet|console|headlin|pedal|gauge|speedo'),
    ('engine',   r'engine|engbay|intake|turbo|intercooler|radiator|airbox'),
]
RULES = [(k, re.compile(p, re.I)) for k, p in RULES]
DOOR_RX = dict(RULES)['door']
SHIFTER_BOOT = re.compile(r'shifter_?boot|gear_?boot|gaiter', re.I)
DROP = re.compile(r'(_dam\b|_dam[_.\d]|_vlo\b|_vlo[_.]|\blod[1-9]\b|_lod[1-9]|shadow|_l[12]_end|collision|\bcol_)', re.I)
# default primitives left in the export — the A6 carries an `Icosphere`
# 0.7 m BELOW its own tyres that read as part of the car
PRIM = re.compile(r'^(icosphere|uv ?sphere|sphere|cube|plane|cylinder|cone|torus)(\.\d+)?$', re.I)
SLIDE_NAME = re.compile(r'slid', re.I)


def _chain(o):
    out = []
    if 'sb_bone' in o:
        out.append(o['sb_bone'])
    n = o
    while n is not None:
        out.append(n.name)
        n = n.parent
    return out


def _kind(o):
    for n in o['sb_chain'].split('|'):
        if SHIFTER_BOOT.search(n):
            return 'cabin'
        for k, rx in RULES:
            if rx.search(n):
                return k
    return 'body'


def _select_only(objs):
    """Select exactly `objs` and make the first active. Operators like mesh
    separate and the glTF exporter read the REAL selection, not an override."""
    vl = bpy.context.view_layer
    for o in vl.objects:
        if o.select_get():
            o.select_set(False)
    for o in objs:
        o.select_set(True)
    vl.objects.active = objs[0]


def _remove(objs):
    for o in objs:
        try:
            bpy.data.objects.remove(o, do_unlink=True)
        except ReferenceError:
            pass


# ═════════════════════════════════════════════════════════════════════════
def convert(imported, rep, override=None):
    """Rig the objects one import created. Returns (parts, hinge).

    `imported` is the list of objects the glTF import added. Nothing outside
    it is read, moved or deleted.
    """
    imported = list(imported)

    # ── 0. BAKE any rigid skin (game rigs) ─────────────────────────────
    baked = 0
    for o in imported:
        if o.type != 'MESH':
            continue
        mods = [m for m in o.modifiers if m.type == 'ARMATURE']
        if not mods:
            continue
        used = {}
        for v in o.data.vertices:
            for g in v.groups:
                if g.weight > 0:
                    n = o.vertex_groups[g.group].name
                    used[n] = used.get(n, 0) + 1
        if len(used) > 1:
            raise Refused(f'{o.name} is skinned to {len(used)} bones — a deforming rig, not a parts rig')
        _select_only([o])
        for m in mods:
            bpy.ops.object.modifier_apply(modifier=m.name)
        o.vertex_groups.clear()
        if used:
            o['sb_bone'] = next(iter(used))        # the part is the BONE, not the mesh
        baked += 1
    rep['baked'] = baked

    # ── 1. DROP what must not render ───────────────────────────────────
    dropped = [o for o in imported if o.type == 'MESH'
               and (any(DROP.search(n) for n in _chain(o)[:3]) or PRIM.match(o.name))]
    rep['dropped'] = len(dropped)
    # the keep-list is taken BEFORE deleting: touching a removed object
    # afterwards raises ReferenceError
    imported = [o for o in imported if o not in dropped]
    _remove(dropped)

    # flatten: every mesh keeps its world pose, then the rig goes
    for o in imported:
        o['sb_chain'] = '|'.join(_chain(o))
    for o in imported:
        if o.type == 'MESH' and o.parent is not None:
            mw = o.matrix_world.copy()
            o.parent = None
            o.matrix_world = mw
    objs = [o for o in imported if o.type == 'MESH' and len(o.data.vertices)]
    _remove([o for o in imported if o.type != 'MESH' or not len(o.data.vertices)])
    if not objs:
        raise Refused('no geometry')
    K = {o: _kind(o) for o in objs}

    # ── 2. FRAME: length along Z, nose +Z, up +Y, left +X, ground 0 ────
    lo, hi = bbox([v for o in objs for v in wv(o)])
    if (hi.x - lo.x) > (hi.z - lo.z):               # length lies on X: turn 90
        Rz = Matrix.Rotation(math.radians(90), 4, 'Z')
        for o in objs:
            o.matrix_world = Rz @ o.matrix_world
        bpy.context.view_layer.update()
        rep['turn90'] = True
    wheels = [o for o in objs if K[o] == 'wheel']
    glass = [o for o in objs if K[o] == 'glazing']
    if not wheels:
        raise Refused('no wheels named')
    if glass and centre(wheels).y > centre(glass).y:
        raise Refused('wheels sit ABOVE the glass — upside down')
    cues = {}
    bon = [o for o in objs if K[o] == 'bonnet']
    tg = [o for o in objs if K[o] == 'tailgate']
    st = [o for o in objs if K[o] == 'steering']
    lo, hi = bbox([v for o in objs for v in wv(o)])
    mid = (lo + hi) / 2
    if bon and tg:
        cues['bonnet_vs_boot'] = 1 if centre(bon).z > centre(tg).z else -1
    if st:
        cues['steering'] = 1 if centre(st).z > mid.z else -1
    hl = [o for o in objs if K[o] == 'lamps_front']
    tl = [o for o in objs if K[o] == 'lamps_rear']
    if hl and tl:
        cues['head_vs_tail_lamps'] = 1 if centre(hl).z > centre(tl).z else -1
    if not cues:
        raise Refused('cannot decide the nose: no bonnet/boot pair, no lamps and no steering wheel')
    # PRIORITY, not a vote. The steering wheel is the WEAKEST cue: it sits
    # BEHIND the midpoint on a long-bonnet coupe (the GR Supra). The two ends
    # of the car outrank it, and must not contradict each other.
    ends = [cues[k] for k in ('bonnet_vs_boot', 'head_vs_tail_lamps') if k in cues]
    if len(set(ends)) > 1:
        raise Refused(f'the two end cues disagree: {cues}')
    nose = ends[0] if ends else cues['steering']
    if len(set(cues.values())) > 1:
        rep['nose_overruled'] = cues
    if nose < 0:
        R180 = Matrix.Rotation(math.pi, 4, 'Z')
        for o in objs:
            o.matrix_world = R180 @ o.matrix_world
        bpy.context.view_layer.update()
    ground = min(v.y for o in wheels for v in wv(o))
    T = Matrix.Translation((0, 0, -ground))
    for o in objs:
        o.matrix_world = T @ o.matrix_world
    bpy.context.view_layer.update()
    lo, hi = bbox([v for o in objs for v in wv(o)])
    mid = (lo + hi) / 2
    rep['frame'] = {'nose_cues': cues, 'yaw180': nose < 0, 'ground_shift': round(-ground, 4),
                    'extent': [round(hi.x - lo.x, 3), round(hi.y - lo.y, 3), round(hi.z - lo.z, 3)]}
    if st:
        rep['frame']['drive'] = 'LHD' if centre(st).x > 0 else 'RHD'

    # ── 3. CORNERS by position ─────────────────────────────────────────
    parts = {}

    def put(pid, o):
        parts.setdefault(pid, []).append(o)

    doorkey = {}
    for o in objs:
        if K[o] != 'door':
            continue
        root = next(n for n in o['sb_chain'].split('|') if DOOR_RX.search(n))
        root = re.sub(r'(_ok|_dummy|__\d+|\.\d+|_\d+)$', '', root, flags=re.I)
        doorkey.setdefault(root, []).append(o)
    size = lambda t: sum(len(o.data.vertices) for o in t[1])
    DOOR = {}
    L, W = hi.z - lo.z, hi.x - lo.x
    for os_ in doorkey.values():
        c = centre(os_)
        b0, b1 = bbox([v for o in os_ for v in wv(o)])
        # A door across the BACK of a van runs sideways, not lengthways: the
        # Vito's `door_rear_left/right` are barn doors, and assigning them by
        # position made them rear SIDE doors that swung through the body.
        if c.z < lo.z + .15 * L and (b1.z - b0.z) < .5 * (b1.x - b0.x):
            if abs(c.x) < .15 * W:                  # one full-width door = tailgate
                for o in os_:
                    put('tailgate', o)
            else:
                for o in os_:
                    put('door_b' + ('l' if c.x > 0 else 'r'), o)
            continue
        DOOR.setdefault('l' if c.x > 0 else 'r', []).append((c.z, os_))
    for side, lst in DOOR.items():
        lst.sort(key=lambda t: -t[0])
        biggest = max(size(t) for t in lst)
        # ANCHORS ARE THE TWO LARGEST clusters, not the two most forward: on
        # the BMW M6 a door-glass cluster took the second anchor slot and the
        # rear door was merged into the front — both swung as one 2 m panel.
        bysize = sorted(lst, key=size, reverse=True)
        anchors = [bysize[0][0]]
        for t in bysize[1:]:
            if size(t) > 0.35 * biggest and abs(t[0] - anchors[0]) > 0.35:
                anchors.append(t[0])
                break
        anchors.sort(reverse=True)
        for z, os_ in lst:
            k = min(range(len(anchors)), key=lambda i: abs(anchors[i] - z))
            for o in os_:
                put(f"door_{'fr'[k]}{side}", o)
    nd = sum(1 for k in parts if k.startswith('door_') and k[5] in 'fr')
    if nd < 2:
        raise Refused(f'only {nd} door part(s) found — the doors are not separate objects in this file')

    # A WHEEL MUST BE WHEEL-SHAPED. On the Rolls-Royce Ghost, parts NAMED for
    # the wheel but reaching 1.6 m put its measured front track at 0.91 m.
    def shape_ok(o):
        b0, b1 = bbox(wv(o))
        h, l, w = b1.y - b0.y, b1.z - b0.z, b1.x - b0.x
        return .35 < h < 1.0 and .75 < l / max(h, 1e-6) < 1.3 and w < .65 * h
    prim = [o for o in wheels if shape_ok(o)]
    boxes = [bbox(wv(o)) for o in prim]
    rest = []
    for o in wheels:
        if o in prim:
            continue
        b0, b1 = bbox(wv(o))
        c = (b0 + b1) / 2
        inside = any(all(pb0[i] - .03 <= c[i] <= pb1[i] + .03 for i in range(3))
                     and (b1 - b0).length < (pb1 - pb0).length for pb0, pb1 in boxes)
        (prim if inside else rest).append(o)
    rep['wheel_rejects'] = [o['sb_chain'][:50] for o in rest][:8]
    for o in rest:
        K[o] = 'body'
    for o in prim:
        c = centre([o])
        put('wheel_' + ('f' if c.z > mid.z else 'r') + ('l' if c.x > 0 else 'r'), o)
    got = sorted(k for k in parts if k.startswith('wheel_'))
    if got != ['wheel_fl', 'wheel_fr', 'wheel_rl', 'wheel_rr']:
        raise Refused(f'wheels do not fill four corners ({got}) — often ONE wheel the game copies at run time')
    for o in objs:
        if K[o] in ('door', 'wheel') or any(o in v for v in parts.values()):
            continue
        put({'bonnet': 'panel_bonnet'}.get(K[o], K[o]), o)

    # glass and handles INSIDE a door's box travel with the door
    for pid in [k for k in parts if k.startswith('door_')]:
        b0, b1 = bbox([v for o in parts[pid] for v in wv(o)])
        for other in ('glazing', 'body'):
            keep = []
            for o in parts.get(other, []):
                ob0, ob1 = bbox(wv(o))
                inside = all(b0[i] - .02 <= ob0[i] and ob1[i] <= b1[i] + .02 for i in range(3))
                (parts[pid] if inside else keep).append(o)
            if other in parts:
                parts[other] = keep

    # ── 4. TYRES MUST READ AS BLACK RUBBER ─────────────────────────────
    rep['tyre_faces_to_rubber'] = _rubber_tyres(parts)

    # ── 5. PAINT: the material covering most of the bonnet (or doors) ──
    paint = _paint(parts, rep)

    # ── 6. BONNET / BOOT from the paint mesh if no part carries them ───
    _lift_panels(parts, paint, lo, hi, rep)
    rep['missing'] = [p for p in _wanted(parts) if not parts.get(p)]

    # ── 7. HINGES, and which doors SLIDE ───────────────────────────────
    hinge = _hinges(parts)
    rep['hinge'] = hinge
    rep['motion'] = _motion(parts, hi.y - lo.y, rep, override)

    # ── 8. GLASS: say what the file claims, the render decides ─────────
    gm = {}
    for o in parts.get('glazing', []) + [o for k in parts if k.startswith('door_') for o in parts[k]]:
        for s in o.material_slots:
            m = s.material
            if m and re.search(r'glass|window|vitre|screen', m.name, re.I):
                gm[m.name] = getattr(m, 'blend_method', '?')
    rep['glass_materials'] = gm

    # ── 9. NAME ────────────────────────────────────────────────────────
    for pid, os_ in parts.items():
        for k, o in enumerate(os_):
            o.name = f'SB_{pid}__{k}'
            o.data.name = o.name
            o['sb_part'] = pid
    rep['parts'] = {k: len(v) for k, v in sorted(parts.items())}
    return parts, hinge


# ═════════════════════════════════════════════════════════════════════════
def _rubber_tyres(parts):
    """Owner ruling 2026-08-09: tyres read as black rubber. On sim-mod cars the
    tyre is often the RIM's material (Captur: `wheel_rim`, grey metal 0.56).
    Split by radius PER TRIANGLE: a face is tyre if it reaches the tread band
    and none of its corners come in to the rim. Only LIGHT, UNTEXTURED faces
    are touched, so a correct black or textured tyre is left alone."""
    rubber = bpy.data.materials.get('SB_tyre_rubber') or bpy.data.materials.new('SB_tyre_rubber')
    rubber.use_nodes = True
    b = rubber.node_tree.nodes.get('Principled BSDF')
    b.inputs['Base Color'].default_value = (0.022, 0.022, 0.024, 1)
    b.inputs['Roughness'].default_value = 0.88
    b.inputs['Metallic'].default_value = 0.0

    def light_untextured(m):
        if m is None or not m.use_nodes:
            return False
        n = m.node_tree.nodes.get('Principled BSDF')
        if n is None or n.inputs['Base Color'].is_linked:
            return False
        c = n.inputs['Base Color'].default_value
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2] > 0.18

    done, split = set(), 0
    for k in [k for k in parts if k.startswith('wheel_')]:
        b0, b1 = bbox([v for o in parts[k] for v in wv(o)])
        cy, cz, R = (b0.y + b1.y) / 2, (b0.z + b1.z) / 2, (b1.y - b0.y) / 2
        for o in parts[k]:
            if o.data.name in done or not any(light_untextured(s.material) for s in o.material_slots):
                continue
            mw, hits = o.matrix_world, []
            for p in o.data.polygons:
                if p.material_index >= len(o.material_slots):
                    continue
                if not light_untextured(o.material_slots[p.material_index].material):
                    continue
                rr = [((q.y - cy) ** 2 + (q.z - cz) ** 2) ** .5
                      for q in (G(mw @ o.data.vertices[vi].co) for vi in p.vertices)]
                if max(rr) > 0.85 * R and min(rr) > 0.60 * R:
                    hits.append(p.index)
            if not hits:
                continue
            o.data.materials.append(rubber)
            ri = len(o.data.materials) - 1
            for i in hits:
                o.data.polygons[i].material_index = ri
            done.add(o.data.name)
            split += len(hits)
    return split


def _paint(parts, rep):
    """The paint is the material on the OUTSIDE of the panel. Counting all area
    picked the Sharan's black door CARD (the door is two skins, and the inner
    one carries more trim); counting only faces that face outward — up for a
    bonnet, away from the centreline for a door — picks the skin."""
    def mat_area(os_, outward):
        A = {}
        for o in os_:
            sc = o.matrix_world.to_scale()
            s = abs(sc.x * sc.y * sc.z) ** (2 / 3)
            n3 = o.matrix_world.to_3x3()
            for p in o.data.polygons:
                if p.material_index < len(o.material_slots) and o.material_slots[p.material_index].material:
                    n = G(n3 @ p.normal)
                    if n.length == 0 or outward(n.normalized()) < 0.5:
                        continue
                    m = o.material_slots[p.material_index].material
                    A[m] = A.get(m, 0) + p.area * s
        return A
    if parts.get('panel_bonnet'):
        A = mat_area(parts['panel_bonnet'], lambda n: n.y)
    else:
        A = {}
        for k in [k for k in parts if k.startswith('door_') and k[5] in 'fr']:
            sx = 1 if k[-1] == 'l' else -1
            for m, a in mat_area(parts[k], lambda n, sx=sx: n.x * sx).items():
                A[m] = A.get(m, 0) + a
    if not A:
        return None
    paint = max(A, key=A.get)
    rep['paint'] = {'material': paint.name, 'from': 'bonnet' if parts.get('panel_bonnet') else 'doors',
                    'share': round(A[paint] / sum(A.values()), 3)}
    # SIBLINGS ARE THE SAME PAINT: the Micra's bonnet is `primary.001` and its
    # body `primary`. Blender's `.NNN` suffix is an import artefact.
    base = re.sub(r'\.\d+$', '', paint.name)
    sib = [m for m in bpy.data.materials if re.sub(r'\.\d+$', '', m.name) == base]
    for m in sib:
        if 'paint' not in m.name.lower():
            m.name = m.name + '_paint'              # the app finds paint by this word
    rep['paint']['renamed'] = [m.name for m in sib]
    return paint


def _islands(o):
    bm = bmesh.new()
    bm.from_mesh(o.data)
    bm.faces.ensure_lookup_table()
    tag = bm.faces.layers.int.new('orig')
    for f in bm.faces:
        f[tag] = f.index
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)   # weld for ISLANDS only
    bm.faces.ensure_lookup_table()
    seen, comps = set(), []
    mw = o.matrix_world
    n3 = mw.to_3x3()
    for f in bm.faces:
        if f.index in seen:
            continue
        stk, comp = [f], []
        seen.add(f.index)
        while stk:
            g = stk.pop()
            comp.append(g)
            for e in g.edges:
                for h in e.link_faces:
                    if h.index not in seen:
                        seen.add(h.index)
                        stk.append(h)
        vs = [G(mw @ v.co) for g in comp for v in g.verts]
        area = sum(g.calc_area() for g in comp)
        up = sum(G(n3 @ g.normal).y * g.calc_area() for g in comp) / max(area, 1e-9)
        fwd = sum(G(n3 @ g.normal).z * g.calc_area() for g in comp) / max(area, 1e-9)
        comps.append((bbox(vs), up, [g[tag] for g in comp], fwd))
    bm.free()
    return comps


def _lift(o, fidx):
    """Separate the faces `fidx` (ORIGINAL indices) off `o` into a new object.
    Indices are stamped into an attribute first, because a separation
    renumbers every face after it."""
    att = o.data.attributes.new('sb_lift', 'INT', 'FACE')
    for i in fidx:
        att.data[i].value = 1
    before = set(bpy.data.objects)
    _select_only([o])
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_mode(type='FACE')
    bpy.ops.mesh.select_all(action='DESELECT')
    ebm = bmesh.from_edit_mesh(o.data)
    lay = ebm.faces.layers.int['sb_lift']
    for f in ebm.faces:
        if f[lay] == 1:
            f.select_set(True)
    ebm.select_flush_mode()
    bmesh.update_edit_mesh(o.data)
    bpy.ops.mesh.separate(type='SELECTED')
    bpy.ops.object.mode_set(mode='OBJECT')
    new = [x for x in bpy.data.objects if x not in before][0]
    for ob in (o, new):
        if 'sb_lift' in ob.data.attributes:
            ob.data.attributes.remove(ob.data.attributes['sb_lift'])
    return new


def _wanted(parts):
    """Panels this vehicle should have. A van closed by BARN doors has no
    tailgate: lifting one anyway cut a slab out of the Vito's rear body."""
    barn = 'door_bl' in parts or 'door_br' in parts
    return [p for p in ('panel_bonnet', 'tailgate') if not (p == 'tailgate' and barn)]


def _lift_panels(parts, paint, lo, hi, rep):
    need = [p for p in _wanted(parts) if not parts.get(p)]
    if not (need and paint):
        return
    L, W, H = hi.z - lo.z, hi.x - lo.x, hi.y - lo.y
    for o in list(parts.get('body', [])):
        if not any(s.material is paint for s in o.material_slots):
            continue
        progress = True
        while need and progress:                    # re-read islands after every lift
            progress = False
            comps = _islands(o)
            for pid in list(need):
                # a bonnet or saloon boot lid faces UP; a hatch or van tailgate
                # stands near-vertical and faces BACK
                cand = [c for c in comps if (c[0][1].x - c[0][0].x) > .6 * W and c[0][0].y > lo.y + .25 * H
                        and (abs(c[1]) > .55 if pid == 'panel_bonnet' else (abs(c[1]) > .55 or c[3] < -.55))
                        and (c[0][1].z > hi.z - .15 * L if pid == 'panel_bonnet'
                             else c[0][0].z < lo.z + .15 * L)]
                rep.setdefault('island_candidates', {})[pid] = len(cand)
                if len(cand) == 1:
                    parts.setdefault(pid, []).append(_lift(o, cand[0][2]))
                    need.remove(pid)
                    rep.setdefault('lifted', {})[pid] = len(cand[0][2])
                    progress = True
                    break
        if not need:
            break


def _hinges(parts):
    hinge = {}
    for pid in [k for k in parts if k.startswith('door_b')]:
        # barn door: vertical hinge on its OUTER edge, at the back face
        vs = [v for o in parts[pid] for v in wv(o)]
        b0, b1 = bbox(vs)
        xs = sorted(abs(v.x) for v in vs)
        x = xs[int(.98 * (len(xs) - 1))]
        edge = [v for v in vs if abs(v.x) > x - .06]
        hinge[pid] = {'x': round(x if pid[-1] == 'l' else -x, 4), 'y': round((b0.y + b1.y) / 2, 4),
                      'z': round(sum(v.z for v in edge) / len(edge), 4)}
    for pid in [k for k in parts if k.startswith('door_') and k[5] in 'fr']:
        vs = [v for o in parts[pid] for v in wv(o)]
        b0, b1 = bbox(vs)
        edge = [v for v in vs if v.z > b1.z - .06]
        xs = sorted(abs(v.x) for v in edge)
        x = xs[int(.9 * (len(xs) - 1))]
        hinge[pid] = {'x': round(x if pid[-1] == 'l' else -x, 4), 'y': round((b0.y + b1.y) / 2, 4),
                      'z': round(b1.z, 4)}
    if parts.get('panel_bonnet'):
        vs = [v for o in parts['panel_bonnet'] for v in wv(o)]
        b0, b1 = bbox(vs)
        hinge['panel_bonnet'] = {'x': 0, 'y': round(max(v.y for v in vs if v.z < b0.z + .06), 4),
                                 'z': round(b0.z, 4)}
    if parts.get('tailgate'):
        vs = [v for o in parts['tailgate'] for v in wv(o)]
        b0, b1 = bbox(vs)
        hinge['tailgate'] = {'x': 0, 'y': round(max(v.y for v in vs if v.z > b1.z - .06), 4),
                             'z': round(b1.z, 4)}
    return hinge


def _motion(parts, height, rep, override=None):
    """Which doors SLIDE (and which are barn doors). A van's side door runs back
    along a rail; swinging it on a hinge would drive it through the body.

    Evidence, strongest first:
      1. `override` — a per-car ruling from overrides.json. Geometry cannot
         decide every car, and a person who has looked at it can.
      2. the file NAMES it sliding (`slide`, `sliding`).
      3. the VAN SIGNATURE, measured in WHEEL DIAMETERS so it survives the
         catalogue's scale spread: the rear side door is TALLER than the front
         door (>= 1.04x) and the vehicle is >= 2.6 wheel diameters tall.
         Calibrated on 25 converted cars: it catches the Vito (1.06x, 2.71)
         and fires on none of the 23 cars with hinged rear doors.

    WHAT IT CANNOT DO, measured: an MPV like the VW Sharan (sliding) and a
    Mazda 3 (hinged) are the SAME shape by every bounding-box ratio tried —
    rear door 1.77 vs 1.79 wheel diameters tall, vehicle 2.55 vs 2.52. So the
    Sharan needs an override. An earlier absolute rule (vehicle >= 1.75 m)
    slid the rear doors of a Micra and a Captur, because those files are
    modelled at ~1.25x real size: never judge this catalogue in metres.
    A sliding door moves OUT then BACK by most of its own length."""
    override = override or {}
    motion = {}
    for pid in ('door_bl', 'door_br'):
        if pid in parts:
            motion[pid] = {'type': 'barn', 'why': 'door across the back of the vehicle'}
    wd = []
    for k in ('wheel_fl', 'wheel_fr', 'wheel_rl', 'wheel_rr'):
        if k in parts:
            b0, b1 = bbox([v for o in parts[k] for v in wv(o)])
            wd.append(b1.y - b0.y)
    wd = sum(wd) / len(wd) if wd else 0

    def dh(k):
        b0, b1 = bbox([v for o in parts[k] for v in wv(o)])
        return b1.y - b0.y, b1.z - b0.z
    fh = [dh(k)[0] for k in ('door_fl', 'door_fr') if k in parts]
    fh = sum(fh) / len(fh) if fh else 0
    sig = {}
    for pid in ('door_rl', 'door_rr'):
        if pid not in parts:
            continue
        h, l = dh(pid)
        ratio = h / fh if fh else 0
        sig[pid] = {'rear_over_front': round(ratio, 3), 'height_in_wheels': round(height / wd, 3) if wd else 0}
        forced = override.get(pid)
        if forced:
            if forced == 'slide':
                motion[pid] = {'type': 'slide', 'out': 0.07, 'back': round(0.82 * l, 3), 'why': 'override'}
            continue
        named = any(SLIDE_NAME.search(o['sb_chain']) for o in parts[pid])
        van = wd and fh and ratio >= 1.04 and height / wd >= 2.6
        if named or van:
            motion[pid] = {'type': 'slide', 'out': 0.07, 'back': round(0.82 * l, 3),
                           'why': 'named sliding' if named else
                           f'van signature: rear door {ratio:.2f}x the front door, vehicle {height / wd:.2f} wheels tall'}
    rep['door_signature'] = sig
    return motion


# ═════════════════════════════════════════════════════════════════════════
def import_glb(path):
    """Import one glTF/GLB and return exactly the objects it created."""
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    bpy.context.view_layer.update()
    return [o for o in bpy.data.objects if o not in before]


def export_parts(parts, dst):
    """Export ONLY this car's parts, in glTF's Y-up frame."""
    objs = [o for os_ in parts.values() for o in os_]
    _select_only(objs)
    bpy.ops.export_scene.gltf(filepath=dst, export_format='GLB', use_selection=True,
                              export_normals=True, export_skins=False,
                              export_animations=False, export_apply=True)


def process_file(src, dst, report_path=None, override=None):
    """Import `src`, rig it, export `dst`. Returns (rep, parts). Raises Refused.
    The objects stay in the scene so a caller can add controls or save .blend.
    `override` is this car's entry from overrides.json, e.g.
    {"door_rl": "slide", "door_rr": "slide"}; "swing" forces a hinge."""
    rep = {'src': src.replace('\\', '/').rsplit('/', 1)[-1], 'rigger': VERSION}
    imported = import_glb(src)
    names = [o.name for o in imported]      # by NAME: a deleted object cannot be asked
    try:
        parts, hinge = convert(imported, rep, override)
        if override:
            rep['override'] = override
    except Refused as e:
        rep['refused'] = str(e)
        if report_path:
            json.dump(rep, open(report_path, 'w'), indent=1)
        _remove([bpy.data.objects[n] for n in names if n in bpy.data.objects])
        raise
    if dst:
        export_parts(parts, dst)
    if report_path:
        json.dump(rep, open(report_path, 'w'), indent=1)
    return rep, parts


def load_overrides(*paths):
    """Merge overrides.json files: the one packaged with the add-on first,
    then one sitting in the input folder, which wins. Keys are file stems."""
    out = {}
    for p in paths:
        if p and os.path.exists(p):
            for k, v in json.load(open(p)).items():
                if not k.startswith('_'):
                    out.setdefault(k, {}).update(v)
    return out


def purge_orphans():
    """Free meshes, materials and images no object uses any more, so a batch
    of a thousand cars does not grow Blender's memory without bound."""
    for coll in (bpy.data.meshes, bpy.data.materials, bpy.data.images,
                 bpy.data.armatures, bpy.data.actions, bpy.data.textures):
        for d in list(coll):
            if d.users == 0:
                coll.remove(d)
