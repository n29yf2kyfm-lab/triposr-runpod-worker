"""Rig one car GLB and render it opening: doors, bonnet, tailgate.

    blender -b --factory-startup --python rig_render.py -- CAR.glb OUT_DIR [--size 1280x800] [--samples 24]

This is the on-demand machine's worker. It reuses the Strip Bay Rigger
(platform/trainer/blender_addon/strip_bay_rigger) unchanged, so a car rigs here
exactly as it rigs in the add-on and the batch CLI.

Writes into OUT_DIR:
  <car>.glb           the rigged car, shut, parts named SB_<part>__<n>
  <car>.report.json   what the rigger found, the hinges, and why if it refused
  <car>_<state>_<view>.png   one still per state per camera
  result.json         status, the parts that open, and the list of stills

States rendered: shut, doors (every side door open), ends (bonnet and
tailgate up), open (everything open at once). A state is skipped when the car
has none of its parts. Cameras: front-left and rear-right three-quarter views.

Refusals are reported, not faked: a car whose doors are welded into the body
has nothing to open, and result.json says so with the rigger's reason.
Exit code 0 when the machine ran (rigged OR refused), 1 on an error.
"""
import bpy, sys, os, re, json, math, time, traceback
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'trainer', 'blender_addon'))
from strip_bay_rigger import core, rig        # noqa: E402

args = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
pos = [a for a in args if not a.startswith('--')]
opt = {a.split('=')[0]: (a.split('=') + [''])[1] for a in args if a.startswith('--')}
if len(pos) != 2:
    print(__doc__)
    sys.exit(1)
SRC, OUT = pos
W, H = (int(x) for x in (opt.get('--size') or '1280x800').split('x'))
SAMPLES = int(opt.get('--samples') or 24)
os.makedirs(OUT, exist_ok=True)
car = os.path.splitext(os.path.basename(SRC))[0]
result = {'car': car, 'src': os.path.basename(SRC), 'rigger': core.VERSION}


def done(status, code=0):
    result['status'] = status
    json.dump(result, open(os.path.join(OUT, 'result.json'), 'w'), indent=1)
    print(f'RIGMACHINE_DONE status={status}')
    sys.exit(code)


for o in list(bpy.data.objects):             # the factory cube sits inside the car
    bpy.data.objects.remove(o, do_unlink=True)

t0 = time.time()
ov = core.load_overrides(os.path.join(HERE, '..', 'trainer', 'blender_addon', 'strip_bay_rigger', 'overrides.json'))
try:
    rep, parts = core.process_file(SRC, os.path.join(OUT, car + '.glb'),
                                   os.path.join(OUT, car + '.report.json'), ov.get(car))
except core.Refused as e:
    result['refused'] = str(e)
    done('refused')
except Exception as e:
    result['error'] = f'{type(e).__name__}: {e}'
    result['trace'] = traceback.format_exc()[-1500:]
    done('error', 1)

ctl = rig.add_controls(parts, rep['hinge'], rep.get('motion'), car, rep)
keys = [k for k in ctl['sb_controls'].split(',') if k]
doors = [k for k in keys if k.startswith('door_')]
ends = [k for k in keys if k in ('bonnet', 'tailgate')]
result.update(opens=doors + ends, wheels=[k for k in keys if k.startswith('wheel_')],
              motion=rep.get('motion', {}), missing=rep.get('missing', []),
              rescaled=rep.get('rescaled'), rig_seconds=round(time.time() - t0, 1))
if not doors + ends:
    result['refused'] = 'rigged, but nothing on this car opens (no separate doors, bonnet or tailgate)'
    done('refused')

STATES = [('shut', []), ('doors', doors), ('ends', ends), ('open', doors + ends)]
STATES = [(n, ks) for n, ks in STATES if n == 'shut' or ks]
if ends == [] or doors == []:                 # 'open' would repeat the other state
    STATES = [s for s in STATES if s[0] != 'open']


def pose(ks):
    for k in keys:
        ctl[k] = 1.0 if k in ks else 0.0
    ctl.update_tag()
    bpy.context.view_layer.update()


car_objs = [o for os_ in parts.values() for o in os_]


def world_bbox(objs):
    vs = [o.matrix_world @ Vector(c) for o in objs if o.type == 'MESH' for c in o.bound_box]
    lo = Vector((min(v.x for v in vs), min(v.y for v in vs), min(v.z for v in vs)))
    hi = Vector((max(v.x for v in vs), max(v.y for v in vs), max(v.z for v in vs)))
    return lo, hi


# ── showcase: glass cleared, an engine in the bay ─────────────────────────
SHOW = '--showcase' in opt
GLASS_RX = re.compile(r'glass|window|vitre|screen|glaz', re.I)
LAMP_RX = re.compile(r'red|amber|orange|lamp|light|indicator|reflect|signal', re.I)   # a coloured lens is not a window


def clear_glass():
    """Make the windows see-through so the cabin reads. Only materials on the
    glazing and on the doors are touched, and only glass-named ones on the
    doors, so a lamp lens (`headlight_glass`) keeps its colour. A glazing
    object's own material is cleared only if nothing else on the car uses it."""
    users = {}
    for pid, os_ in parts.items():
        for o in os_:
            for s in o.material_slots:
                if s.material:
                    users.setdefault(s.material.name, set()).add(pid)
    cleared = set()
    for pid, os_ in parts.items():
        for o in os_:
            for s in o.material_slots:
                m = s.material
                if not m or m.name in cleared:
                    continue
                if LAMP_RX.search(m.name):
                    continue
                named = bool(GLASS_RX.search(m.name))
                own = pid == 'glazing' and users[m.name] <= {'glazing'} | {k for k in users[m.name] if k.startswith('door_')}
                if (pid == 'glazing' or pid.startswith('door_')) and (named or own):
                    m.use_nodes = True
                    bs = next((n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
                    if bs is None:
                        continue
                    for l in list(bs.inputs['Alpha'].links):
                        m.node_tree.links.remove(l)
                    bs.inputs['Alpha'].default_value = 0.0      # Cycles honours alpha with no blend mode
                    cleared.add(m.name)
    return sorted(cleared)


def fit_engine(path, kind, mount):
    """Import a real engine model and stand it in the bay, sized from the car's
    own wheels and bonnet — the Garage's fitPart/addRealEngine, in Blender.
    Frame here: nose -Y, car's left +X, up +Z, ground 0."""
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    new = [o for o in bpy.data.objects if o not in before]
    meshes = [o for o in new if o.type == 'MESH']
    root = bpy.data.objects.new('RM_engine', None)
    sc0 = bpy.context.scene.collection
    sc0.objects.link(root)
    bpy.context.view_layer.update()
    for o in new:
        if o.parent is None:
            mw = o.matrix_world.copy()
            o.parent = root
            o.matrix_world = mw
    for m in {s.material for o in meshes for s in o.material_slots if s.material}:
        bs = next((n for n in (m.node_tree.nodes if m.use_nodes else []) if n.type == 'BSDF_PRINCIPLED'), None)
        if bs and not bs.inputs['Base Color'].links and min(bs.inputs['Base Color'].default_value[:3]) > 0.97:
            bs.inputs['Base Color'].default_value = (0.36, 0.38, 0.4, 1)   # untextured white casting reads as aluminium
            bs.inputs['Metallic'].default_value = 0.75
            bs.inputs['Roughness'].default_value = 0.36
    W = {}
    for k in ('fl', 'fr', 'rl', 'rr'):
        a, b = world_bbox(parts['wheel_' + k])
        W[k] = ((a + b) / 2, (b.z - a.z) / 2, b.x - a.x)
    r = sum(w[1] for w in W.values()) / 4
    yf = (W['fl'][0].y + W['fr'][0].y) / 2
    track = abs(W['fl'][0].x - W['fr'][0].x)
    tw = min((W['fl'][2] + W['fr'][2]) / 2, 0.36)
    inner = track / 2 - tw / 2 - 0.07
    ylow = r * 0.62
    if parts.get('panel_bonnet'):
        a, b = world_bbox(parts['panel_bonnet'])
        ceiling = (a.z + b.z) / 2 - 0.04
    else:
        ceiling = r * 2 + 0.18
    long_ = mount == 'long'
    vee = kind == 'v8'
    length = 0.72 if vee else (0.5 if kind == 'ev' else 0.62)
    max_h = max(0.35, ceiling - ylow)
    max_w = max(0.55, inner * 1.6) if long_ else 0.72
    # turn so the longest horizontal side runs across the car (transverse) or along it
    a, b = world_bbox(meshes)
    sz = b - a
    along_x = not long_
    if (sz.x >= sz.y) != along_x:
        root.rotation_euler.z = math.pi / 2
    bpy.context.view_layer.update()
    a, b = world_bbox(meshes)
    sz = b - a
    L, Wd = (sz.x, sz.y) if along_x else (sz.y, sz.x)
    s = min(length / L, max_h / sz.z, max_w / Wd)
    root.scale = (s, s, s)
    bpy.context.view_layer.update()
    a, b = world_bbox(meshes)
    c = (a + b) / 2
    # transverse: just ahead of the front axle; longitudinal: behind it
    cy = yf - 0.10 if not long_ else yf + length * 0.35 - 0.05
    root.location += Vector((0 - c.x, cy - c.y, ylow - a.z))
    bpy.context.view_layer.update()
    a, b = world_bbox(meshes)
    return meshes, root, {'kind': kind, 'mount': 'longitudinal' if long_ else 'transverse',
                          'scale': round(s, 4), 'size_m': [round(v, 3) for v in (b - a)],
                          'note': 'a representative engine standing in for this car\'s, not its own'}


def bay_contents():
    """How much of the car already sits in the engine bay. Counted in the
    bonnet's footprint (shrunk 15% so the wings and arches stay out), from
    axle height up to the bonnet. A modelled bay (the RS6's V8 under its
    cover) means the car keeps its own engine; an empty shell gets ours."""
    if not parts.get('panel_bonnet'):
        return None
    a, b = world_bbox(parts['panel_bonnet'])
    mx, my = (b.x - a.x) * 0.15, (b.y - a.y) * 0.15
    wa, wb = world_bbox(parts['wheel_fl'])
    z0 = (wa.z + wb.z) / 2
    n = 0
    for pid, os_ in parts.items():
        if pid == 'panel_bonnet' or pid.startswith(('wheel_', 'door_', 'brakes')):
            continue
        for o in os_:
            if o.type != 'MESH':
                continue
            M = o.matrix_world
            for v in o.data.vertices:
                w = M @ v.co
                if a.x + mx < w.x < b.x - mx and a.y + my < w.y < b.y - my and z0 < w.z < a.z:
                    n += 1
    return n


BAY_FULL = 1500          # vertices; see README for how this was set
engine_objs = []
if SHOW:
    result['glass_cleared'] = clear_glass()
    epath, ekind = opt.get('--engine-file'), opt.get('--engine') or 'none'
    bay = bay_contents()
    own = parts.get('engine') or (bay is not None and bay > BAY_FULL)
    if ekind != 'none' and own:
        result['engine'] = {'own': True, 'bay_vertices': bay, 'named_engine_parts': len(parts.get('engine', [])),
                            'note': 'this car has its own engine bay modelled, so ours is not added'}
    elif epath and ekind != 'none' and all(parts.get('wheel_' + k) for k in ('fl', 'fr', 'rl', 'rr')):
        try:
            engine_objs, eroot, result['engine'] = fit_engine(epath, ekind, opt.get('--mount') or 'trans')
            result['engine']['bay_vertices'] = bay
            for o in bpy.data.objects:
                o.select_set(False)
            eroot.select_set(True)
            for o in engine_objs:
                o.select_set(True)
            bpy.ops.export_scene.gltf(filepath=os.path.join(OUT, car + '.engine.glb'), export_format='GLB',
                                      use_selection=True, export_apply=True, export_animations=False)
            result['engine']['file'] = car + '.engine.glb'
        except Exception as e:                # an engine is dressing; the car still ships
            result['engine'] = {'error': f'{type(e).__name__}: {e}'}
    elif ekind != 'none':
        result['engine'] = {'skipped': 'no engine file, or the car has no four wheels to size the bay from'}
    STATES = [('showcase', doors + ends)] + [s for s in STATES if s[0] == 'shut']

# frame every still on the car with EVERYTHING open, so all views share one
# camera and a sheet reads as the same car opening, not a zoom
pose(doors + ends)
lo, hi = world_bbox(car_objs)
pose([])
slo, shi = world_bbox(car_objs)
centre = (lo + hi) / 2
centre.z = (shi.z) * 0.42
radius = (hi - lo).length / 2

# ── studio ────────────────────────────────────────────────────────────────
sc = bpy.context.scene
sc.render.engine = 'CYCLES'
sc.cycles.device = 'CPU'
sc.cycles.samples = SAMPLES
try:                                          # probe, never assume: 4.0.2 had no OIDN
    sc.cycles.use_denoising = True
    sc.cycles.denoiser = 'OPENIMAGEDENOISE'
    result['denoise'] = True
except (TypeError, AttributeError):
    sc.cycles.use_denoising = False
    result['denoise'] = False
sc.render.resolution_x, sc.render.resolution_y = W, H
sc.render.film_transparent = False
sc.view_settings.view_transform = 'Standard'  # AgX clipped tyres white here before
sc.world = bpy.data.worlds.new('rm_world')
sc.world.use_nodes = True
bg = sc.world.node_tree.nodes['Background']
bg.inputs[0].default_value = (0.22, 0.225, 0.235, 1)
bg.inputs[1].default_value = 0.6

L = shi.y - slo.y
floor = bpy.data.meshes.new('rm_floor')
s = 12 * max(L, 4)
floor.from_pydata([(-s, -s, 0), (s, -s, 0), (s, s, 0), (-s, s, 0)], [], [(0, 1, 2, 3)])
fo = bpy.data.objects.new('rm_floor', floor)
sc.collection.objects.link(fo)
fm = bpy.data.materials.new('rm_floor')
fm.use_nodes = True
bs = fm.node_tree.nodes['Principled BSDF']
bs.inputs['Base Color'].default_value = (0.16, 0.162, 0.168, 1)
bs.inputs['Roughness'].default_value = 0.55
floor.materials.append(fm)


def area(name, loc, energy, size):
    d = bpy.data.lights.new(name, 'AREA')
    d.energy, d.size = energy, size
    o = bpy.data.objects.new(name, d)
    o.location = loc
    sc.collection.objects.link(o)
    direction = centre - Vector(loc)
    o.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()


k = max(L, 4) / 4.5
area('rm_key', centre + Vector((0, 0, 5 * k)), 900 * k * k, 5 * k)
area('rm_fill_l', centre + Vector((6 * k, -2 * k, 2.2 * k)), 260 * k * k, 4 * k)
area('rm_fill_r', centre + Vector((-6 * k, 2 * k, 2.2 * k)), 260 * k * k, 4 * k)

cam_d = bpy.data.cameras.new('rm_cam')
cam_d.lens = 40
cam = bpy.data.objects.new('rm_cam', cam_d)
sc.collection.objects.link(cam)
sc.camera = cam
fov = 2 * math.atan(cam_d.sensor_width / 2 / cam_d.lens) * min(1, H / W)
dist = radius / math.sin(fov / 2) * 0.70   # the bbox corners never all face the camera

# Strip Bay frame in Blender: nose -Y, car's left +X, up +Z (core.py step 2)
VIEWS = {'fl': (math.radians(38), math.radians(16)),      # front-left three-quarter
         'rr': (math.radians(218), math.radians(16))}     # rear-right three-quarter


def aim(az, el, target=None, d_=None):
    target = target if target is not None else centre
    d = Vector((math.sin(az) * math.cos(el), -math.cos(az) * math.cos(el), math.sin(el)))
    cam.location = target + d * (d_ or dist)
    cam.rotation_euler = (target - cam.location).to_track_quat('-Z', 'Y').to_euler()


def views_for(state):
    if state != 'showcase':
        return [(v, a, e, None, None) for v, (a, e) in VIEWS.items()]
    out = [('fl', *VIEWS['fl'], None, None), ('rr', *VIEWS['rr'], None, None)]
    # the engine bay, from the front-left and above, framed on the engine
    if engine_objs:
        a, b = world_bbox(engine_objs)
        c = (a + b) / 2
        r_ = max((b - a).length / 2, 0.35)
        out.append(('bay', math.radians(24), math.radians(42), c, r_ / math.sin(fov / 2) * 1.9))
    # the cabin, through the cleared glass on the open driver's-side flank
    out.append(('cabin', math.radians(78), math.radians(24), Vector((0, (slo.y + shi.y) / 2, shi.z * 0.55)),
                max(shi.x - slo.x, 1.6) / math.sin(fov / 2) * 0.62))
    return out


stills = []
t1 = time.time()
for name, ks in STATES:
    pose(ks)
    for v, az, el, tgt, dd in views_for(name):
        aim(az, el, tgt, dd)
        path = os.path.join(OUT, f'{car}_{name}_{v}.png')
        sc.render.filepath = path
        bpy.ops.render.render(write_still=True)
        stills.append({'state': name, 'view': v, 'file': os.path.basename(path), 'opens': ks})
        print(f'RIGMACHINE still {name} {v}')
pose([])
result['stills'] = stills
result['render_seconds'] = round(time.time() - t1, 1)
if opt.get('--blend') is not None and '--blend' in opt:
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, car + '.blend'), copy=True)
done('partial' if rep.get('missing') else 'ok')
