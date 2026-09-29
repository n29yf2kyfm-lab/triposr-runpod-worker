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
import bpy, sys, os, json, math, time, traceback
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


def aim(az, el):
    d = Vector((math.sin(az) * math.cos(el), -math.cos(az) * math.cos(el), math.sin(el)))
    cam.location = centre + d * dist
    cam.rotation_euler = (centre - cam.location).to_track_quat('-Z', 'Y').to_euler()


stills = []
t1 = time.time()
for name, ks in STATES:
    pose(ks)
    for v, (az, el) in VIEWS.items():
        aim(az, el)
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
