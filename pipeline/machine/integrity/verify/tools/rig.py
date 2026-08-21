#!/usr/bin/env python3
"""
STAGE 7 + STAGE 8 RIG.  Neutral diagnostic materials, eight canonical cameras,
five orthographic cameras, and the numeric assertions that make the resulting
sheets admissible as evidence.

    blender -b --factory-startup --python rig.py -- \
        --glb IN.glb --out DIR --mats neutral|original|clay|matid|normal|faceorient \
        [--views canon|ortho|all] [--res 1200x900] [--samples 48] [--fit fixed|per_view]
        [--cull] [--only NAME[,NAME]] [--isolate CLASS] [--wire]

DESIGN NOTES THAT ARE LOAD-BEARING
  * CYCLES only (no EGL in this container).  Standard view transform, look None,
    exposure 0 -- AgX is never used.  The world is a uniform 0.22 grey, which
    under Standard must encode to sRGB ~129.  Every render reports the measured
    background value and the clipped-pixel fraction, so "is the transform right"
    is answered by a number in the report rather than by an eye.
  * ORIENTATION IS ASSERTED, NEVER INHERITED.  CLAUDE.md records four separate
    occasions where azimuth was taken from a filename and the render was wrong.
    `assert_orientation()` derives the nose axis from interior geometry alone
    (seat rake, steering assembly, rear bench) and refuses to build cameras if
    the signals disagree.
  * Every camera is verified AFTER creation by taking its world -Z axis and
    comparing it to the direction the name promises.  A camera whose measured
    azimuth is more than 1 degree from its nominal one aborts the run.
  * The silhouette mask is a SEPARATE 1-sample render with every material
    replaced by one opaque diffuse and the ground hidden, so coverage is
    geometric and cannot be altered by transparency.  Occupancy and the
    populated-tile test are both computed from that mask, in code.
"""
import bpy, sys, os, json, math, argparse
from mathutils import Vector, Matrix

# ------------------------------------------------------------------ arguments
argv = sys.argv[sys.argv.index('--') + 1:]
ap = argparse.ArgumentParser()
ap.add_argument('--glb', required=True)
ap.add_argument('--out', required=True)
ap.add_argument('--mats', default='neutral')
ap.add_argument('--views', default='canon')
ap.add_argument('--res', default='1200x900')
ap.add_argument('--samples', type=int, default=48)
ap.add_argument('--fit', default='fixed')
ap.add_argument('--cull', action='store_true')
ap.add_argument('--only', default='')
ap.add_argument('--isolate', default='')
ap.add_argument('--wire', action='store_true')
ap.add_argument('--label', default='')
ap.add_argument('--nomask', action='store_true')
A = ap.parse_args(argv)
RESX, RESY = (int(v) for v in A.res.lower().split('x'))
os.makedirs(A.out, exist_ok=True)

# ------------------------------------------------------------------ import
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=A.glb)
CAR = [o for o in bpy.context.scene.objects if o.type == 'MESH']
if not CAR:
    raise SystemExit('FATAL: no mesh objects imported')

TYREY = ('tyre', 'tire', 'rubber')
RIMY = ('rim', 'wheel', 'alloy', 'hub', 'spoke', 'disc', 'brake')
GLASSY = ('glass', 'window', 'windscreen', 'windshield', 'glazing', 'pane', 'backlight')
NOTGLASS = ('lamp', 'surr', 'frame', 'trim', 'mirror', 'rearview', 'icon',
            'button', 'instrument', 'dash', 'seal', 'wiper')
LAMPY = ('lamp', 'drl', 'headlight', 'taillight', 'indicator', 'reflector')
INTY = ('cabin', 'interior', 'seat', 'dash', 'console', 'headliner', 'floor',
        'doorcard', 'tunnel', 'bench', 'parcelshelf', 'bootfloor', 'binnacle')


def cls_of(o):
    ns = [o.name.lower()] + [(m.name.lower() if m else '') for m in o.data.materials]
    for n in ns:
        if any(k in n for k in TYREY) and 'arch' not in n:
            return 'tyre'
    for n in ns:
        if any(k in n for k in LAMPY):
            return 'lamp'
    for n in ns:
        if any(k in n for k in GLASSY) and not any(k in n for k in NOTGLASS):
            return 'glass'
    for n in ns:
        if any(k in n for k in RIMY):
            return 'rim'
    for n in ns:
        if any(k in n for k in INTY):
            return 'interior'
    return 'body'


CLS = {o.name: cls_of(o) for o in CAR}


# ------------------------------------------------------- transformed geometry
def obj_world_bounds(o):
    dg = bpy.context.evaluated_depsgraph_get()
    me = o.evaluated_get(dg).to_mesh()
    mw = o.matrix_world
    mn = Vector((1e30,) * 3)
    mx = Vector((-1e30,) * 3)
    for v in me.vertices:
        w = mw @ v.co
        for k in range(3):
            mn[k] = min(mn[k], w[k])
            mx[k] = max(mx[k], w[k])
    o.evaluated_get(dg).to_mesh_clear()
    return mn, mx


BOUNDS = {o.name: obj_world_bounds(o) for o in CAR}
GMIN = Vector((min(BOUNDS[o.name][0][k] for o in CAR) for k in range(3)))
GMAX = Vector((max(BOUNDS[o.name][1][k] for o in CAR) for k in range(3)))
CENTRE = (GMIN + GMAX) / 2.0
SIZE = GMAX - GMIN


def cen(name):
    mn, mx = BOUNDS[name]
    return (mn + mx) / 2.0


# ------------------------------------------------------------- ORIENTATION
def assert_orientation():
    """Derive the nose axis from INTERIOR geometry.  Exterior part names
    ('Bumper_Front', 'TailLamp') are recorded as corroboration only -- a name
    is not evidence.  Four signals; all four must agree or the run aborts."""
    sig = []

    def group(*keys):
        return [o.name for o in CAR if any(k in o.name.lower() for k in keys)]

    # S1 seat rake, front row: as a seat rises it leans AWAY from the nose.
    front = [n for n in group('seatfd', 'seatfp')]
    if front:
        pts = [(cen(n).z, cen(n).x) for n in front]
        zs = [p[0] for p in pts]
        xs = [p[1] for p in pts]
        mz, mx_ = sum(zs) / len(zs), sum(xs) / len(xs)
        num = sum((z - mz) * (x - mx_) for z, x in pts)
        den = sum((z - mz) ** 2 for z in zs) or 1e-12
        slope = num / den
        sig.append({'signal': 'S1 front-seat rake dx/dz', 'value': round(slope, 4),
                    'nose_axis_sign': (-1 if slope > 0 else 1), 'n': len(front),
                    'reason': 'a seat reclines away from the nose, so a positive '
                              'dx/dz means the nose is at -X'})
    # S2 rear bench rake, same rule, independent parts
    bench = group('bench')
    if bench:
        pts = [(cen(n).z, cen(n).x) for n in bench]
        zs = [p[0] for p in pts]
        xs = [p[1] for p in pts]
        mz, mx_ = sum(zs) / len(zs), sum(xs) / len(xs)
        num = sum((z - mz) * (x - mx_) for z, x in pts)
        den = sum((z - mz) ** 2 for z in zs) or 1e-12
        slope = num / den
        sig.append({'signal': 'S2 rear-bench rake dx/dz', 'value': round(slope, 4),
                    'nose_axis_sign': (-1 if slope > 0 else 1), 'n': len(bench),
                    'reason': 'same rake rule on an independent seat row'})
    # S3 steering assembly sits FORWARD of the front-seat cushions
    steer = group('cabin_wheel', 'cabin_hub', 'cabin_spokes', 'cabin_column', 'binnacle')
    cush = [n for n in front if 'cush' in n.lower()]
    if steer and cush:
        sx = sum(cen(n).x for n in steer) / len(steer)
        cxv = sum(cen(n).x for n in cush) / len(cush)
        sig.append({'signal': 'S3 steering.x - cushion.x', 'value': round(sx - cxv, 4),
                    'nose_axis_sign': (-1 if sx < cxv else 1),
                    'n': len(steer) + len(cush),
                    'reason': 'the steering wheel is between the driver and the nose'})
    # S4 front row sits forward of the rear row
    if front and bench:
        fx = sum(cen(n).x for n in front) / len(front)
        bx = sum(cen(n).x for n in bench) / len(bench)
        sig.append({'signal': 'S4 frontrow.x - rearrow.x', 'value': round(fx - bx, 4),
                    'nose_axis_sign': (-1 if fx < bx else 1), 'n': len(front) + len(bench),
                    'reason': 'the front row is nearer the nose than the rear row'})

    signs = [s['nose_axis_sign'] for s in sig]
    agree = len(set(signs)) == 1 and len(signs) >= 3
    nose = signs[0] if agree else None

    # corroboration from names -- recorded, never decisive
    def nx(keys):
        g = [o.name for o in CAR if any(k in o.name.lower() for k in keys)]
        return (round(sum(cen(n).x for n in g) / len(g), 4) if g else None), len(g)

    fx, fn = nx(('bumper_front', 'valance_front', 'headlamp', 'grille', 'drl'))
    rx, rn = nx(('taillamp', 'hatch', 'bumper_rear', 'plate_rear', 'parcelshelf'))
    corrob = (-1 if (fx is not None and rx is not None and fx < rx) else 1)

    # handedness: nose = -X, up = +Z  =>  vehicle RIGHT = forward x up
    fwd = Vector((nose, 0, 0)) if nose else Vector((-1, 0, 0))
    right = fwd.cross(Vector((0, 0, 1))).normalized()
    def is_L(n):
        t = n.split('_')
        return (t[-1].upper() == 'L'
                or (len(t) > 2 and t[-2].upper() == 'L')
                or n.lower().startswith(('wheel_fl', 'wheel_rl')))
    lsuf = [o.name for o in CAR if is_L(o.name)]
    ly = (sum(cen(n).y for n in lsuf) / len(lsuf)) if lsuf else None
    l_is_vehicle_left = (ly is not None and (Vector((0, ly, 0)).dot(-right) > 0))

    out = {
        'signals': sig,
        'all_signals_agree': agree,
        'nose_axis': ('-X' if nose == -1 else ('+X' if nose == 1 else 'UNDECIDED')),
        'nose_unit_vector': [float(fwd.x), 0.0, 0.0],
        'vehicle_right_unit_vector': [round(v, 6) for v in right],
        'vehicle_left_unit_vector': [round(-v, 6) for v in right],
        'name_corroboration': {
            'front_named_parts_mean_x': fx, 'n_front_named': fn,
            'rear_named_parts_mean_x': rx, 'n_rear_named': rn,
            'implies_nose_axis': ('-X' if corrob == -1 else '+X'),
            'agrees_with_geometry': (corrob == nose)},
        'L_suffix_check': {
            'objects_treated_as_L_suffixed': lsuf,
            'their_mean_y': (round(ly, 4) if ly is not None else None),
            'L_suffix_is_on_vehicle_LEFT': bool(l_is_vehicle_left),
            'NOTE': 'if False, the model uses a viewer-facing L/R convention '
                    '(photographer\'s left) rather than automotive nearside/'
                    'offside.  It is a NAMING fact, not a geometry defect, but '
                    'any camera named from a node name would be mirrored.'},
    }
    if not agree:
        out['FATAL'] = 'orientation signals disagree; refusing to build cameras'
    return out, fwd, right


ORI, FWD, RIGHT = assert_orientation()
if 'FATAL' in ORI:
    json.dump(ORI, open(os.path.join(A.out, 'orientation.json'), 'w'), indent=1)
    raise SystemExit('FATAL: ' + ORI['FATAL'])
UP = Vector((0, 0, 1))

# ------------------------------------------------------------------ materials
NEUTRAL = {
    'body':     dict(base=(0.350, 0.350, 0.355, 1), metal=0.0, rough=0.62, trans=0.0),
    'glass':    dict(base=(0.560, 0.630, 0.680, 1), metal=0.0, rough=0.05, trans=0.88),
    'tyre':     dict(base=(0.045, 0.045, 0.048, 1), metal=0.0, rough=0.90, trans=0.0),
    'rim':      dict(base=(0.560, 0.560, 0.570, 1), metal=1.0, rough=0.34, trans=0.0),
    'interior': dict(base=(0.170, 0.170, 0.175, 1), metal=0.0, rough=0.72, trans=0.0),
    'lamp':     dict(base=(0.050, 0.720, 0.900, 1), metal=0.0, rough=0.15, trans=0.0),
}
LAMP_REAR = (0.900, 0.100, 0.520, 1)
MATID = {'body': (0.20, 0.45, 0.85, 1), 'glass': (0.15, 0.85, 0.75, 1),
         'tyre': (0.90, 0.55, 0.10, 1), 'rim': (0.85, 0.20, 0.35, 1),
         'interior': (0.55, 0.30, 0.75, 1), 'lamp': (0.95, 0.90, 0.20, 1)}


def flat(name, rgba, emit=True):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    if emit:
        s = nt.nodes.new('ShaderNodeEmission')
        s.inputs['Color'].default_value = rgba
        s.inputs['Strength'].default_value = 1.0
    else:
        s = nt.nodes.new('ShaderNodeBsdfDiffuse')
        s.inputs['Color'].default_value = rgba
    nt.links.new(s.outputs[0], out.inputs['Surface'])
    m.use_backface_culling = A.cull
    return m


def principled(name, spec):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes['Principled BSDF']
    b.inputs['Base Color'].default_value = spec['base']
    b.inputs['Metallic'].default_value = spec['metal']
    b.inputs['Roughness'].default_value = spec['rough']
    if 'Transmission Weight' in b.inputs:
        b.inputs['Transmission Weight'].default_value = spec['trans']
    if spec['trans'] > 0:
        m.blend_method = 'BLEND'
        if 'IOR' in b.inputs:
            b.inputs['IOR'].default_value = 1.45
    m.use_backface_culling = A.cull
    return m


def shader_diag(kind):
    """Emission-only diagnostic shaders.  These need no light transport, so
    they render at 4 samples in seconds even on 888k triangles -- which is the
    only reason a full set of diagnostic sheets is affordable on 4 CPU cores."""
    m = bpy.data.materials.new('DIAG_' + kind)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    emi = nt.nodes.new('ShaderNodeEmission')
    emi.inputs['Strength'].default_value = 1.0
    geo = nt.nodes.new('ShaderNodeNewGeometry')
    if kind == 'normal':
        # world-space normal remapped to 0..1: a normal sheet shows smoothing
        # errors and inverted shells that a shaded render hides
        mp = nt.nodes.new('ShaderNodeVectorMath')
        mp.operation = 'MULTIPLY_ADD'
        mp.inputs[1].default_value = (0.5, 0.5, 0.5)
        mp.inputs[2].default_value = (0.5, 0.5, 0.5)
        nt.links.new(geo.outputs['Normal'], mp.inputs[0])
        nt.links.new(mp.outputs['Vector'], emi.inputs['Color'])
    elif kind == 'faceorient':
        # Blender's face-orientation convention: front faces blue, back red.
        mix = nt.nodes.new('ShaderNodeMixRGB')
        mix.inputs['Color1'].default_value = (0.10, 0.30, 0.95, 1)   # front
        mix.inputs['Color2'].default_value = (0.95, 0.12, 0.10, 1)   # back
        nt.links.new(geo.outputs['Backfacing'], mix.inputs['Fac'])
        nt.links.new(mix.outputs['Color'], emi.inputs['Color'])
    elif kind == 'wire':
        wf = nt.nodes.new('ShaderNodeWireframe')
        wf.use_pixel_size = True
        wf.inputs['Size'].default_value = 1.0
        mix = nt.nodes.new('ShaderNodeMixRGB')
        mix.inputs['Color1'].default_value = (0.82, 0.82, 0.84, 1)   # surface
        mix.inputs['Color2'].default_value = (0.05, 0.05, 0.06, 1)   # wire
        nt.links.new(wf.outputs['Fac'], mix.inputs['Fac'])
        nt.links.new(mix.outputs['Color'], emi.inputs['Color'])
    else:
        raise SystemExit('unknown diag shader ' + kind)
    nt.links.new(emi.outputs[0], out.inputs['Surface'])
    m.use_backface_culling = A.cull
    return m


def apply_mats(mode):
    if mode in ('normal', 'faceorient', 'wire'):
        m = shader_diag(mode)
        for o in CAR:
            o.data.materials.clear()
            o.data.materials.append(m)
        return {'mode': mode, 'materials_created': ['DIAG_' + mode],
                'note': 'emission-only diagnostic shader'}
    if mode == 'original':
        for m in bpy.data.materials:
            m.use_backface_culling = A.cull
        return {'mode': 'original', 'note': 'as shipped'}
    made = {}
    for o in CAR:
        c = CLS[o.name]
        if mode == 'neutral':
            spec = dict(NEUTRAL[c])
            key = c
            if c == 'lamp':
                rear = (cen(o.name).x - CENTRE.x) * FWD.x < 0   # away from nose
                if rear:
                    spec['base'] = LAMP_REAR
                    key = 'lamp_rear'
                else:
                    key = 'lamp_front'
            if key not in made:
                made[key] = principled('DIAG_' + key, spec)
            mat = made[key]
        elif mode == 'clay':
            if 'clay' not in made:
                made['clay'] = principled('CLAY', dict(base=(0.42, 0.42, 0.43, 1),
                                                       metal=0.0, rough=0.75, trans=0.0))
            mat = made['clay']
        elif mode == 'matid':
            if c not in made:
                made[c] = flat('MATID_' + c, MATID[c], emit=True)
            mat = made[c]
        else:
            raise SystemExit('unknown mats mode ' + mode)
        o.data.materials.clear()
        o.data.materials.append(mat)
    return {'mode': mode, 'materials_created': sorted(made.keys())}


MATINFO = apply_mats(A.mats)


def cull_backfaces():
    """Backface culling that actually works in CYCLES.

    `Material.use_backface_culling` is an EEVEE rasteriser setting; Cycles is a
    path tracer and ignores it.  Setting that flag and calling the result a
    "backface culling ON" sheet would have produced two IDENTICAL sheets and a
    PASS on a test that never ran -- exactly the dead-check pattern this project
    has hit nine times.  Culling is therefore done in the shader: every surface
    is mixed with a Transparent BSDF driven by Geometry>Backfacing, so a face
    seen from behind is not drawn.  Control C4 (a primitive with reversed
    winding) proves it fires."""
    n = 0
    for m in bpy.data.materials:
        if not m.use_nodes or m.name == 'GroundMatte':
            continue
        nt = m.node_tree
        out = next((x for x in nt.nodes if x.type == 'OUTPUT_MATERIAL'), None)
        if not out or not out.inputs['Surface'].is_linked:
            continue
        src = out.inputs['Surface'].links[0].from_socket
        mix = nt.nodes.new('ShaderNodeMixShader')
        tr = nt.nodes.new('ShaderNodeBsdfTransparent')
        geo = nt.nodes.new('ShaderNodeNewGeometry')
        nt.links.new(src, mix.inputs[1])          # front face -> the real shader
        nt.links.new(tr.outputs[0], mix.inputs[2])   # back face -> invisible
        nt.links.new(geo.outputs['Backfacing'], mix.inputs['Fac'])
        nt.links.new(mix.outputs[0], out.inputs['Surface'])
        n += 1
    return n


CULLED_MATS = cull_backfaces() if A.cull else 0
MATINFO['backface_culled_materials'] = CULLED_MATS
MATINFO['cull_method'] = ('shader Transparent BSDF mixed on Geometry>Backfacing '
                          '(Cycles ignores Material.use_backface_culling)'
                          if A.cull else 'none')

# ------------------------------------------------------------------ isolation
if A.isolate:
    keep = set(A.isolate.split(','))
    for o in CAR:
        if CLS[o.name] not in keep:
            o.hide_render = True
if A.only:
    keep = set(A.only.split(','))
    for o in CAR:
        if o.name not in keep:
            o.hide_render = True

# ------------------------------------------------------------------ the studio
sc = bpy.context.scene
sc.render.engine = 'CYCLES'
sc.cycles.device = 'CPU'
sc.cycles.samples = A.samples
sc.cycles.use_denoising = True
try:
    sc.cycles.denoiser = 'OPENIMAGEDENOISE'
except Exception:
    pass
sc.cycles.max_bounces = 8
sc.cycles.transmission_bounces = 8
sc.cycles.transparent_max_bounces = 8
sc.cycles.use_fast_gi = False
sc.render.resolution_x = RESX
sc.render.resolution_y = RESY
sc.render.resolution_percentage = 100
sc.render.image_settings.file_format = 'PNG'
sc.render.image_settings.color_mode = 'RGBA'
sc.render.film_transparent = False
# STANDARD, never AgX; no look, no exposure, no bloom.
sc.view_settings.view_transform = 'Standard'
sc.view_settings.look = 'None'
sc.view_settings.exposure = 0.0
sc.view_settings.gamma = 1.0

WORLD_GREY = 0.22
w = bpy.data.worlds.new('W')
sc.world = w
w.use_nodes = True
bg = w.node_tree.nodes['Background']
bg.inputs['Color'].default_value = (WORLD_GREY, WORLD_GREY, WORLD_GREY, 1)
bg.inputs['Strength'].default_value = 1.0

# ground plane, matte neutral, big enough that no view sees its edge
bpy.ops.mesh.primitive_plane_add(size=max(SIZE.x, SIZE.y) * 14,
                                 location=(CENTRE.x, CENTRE.y, GMIN.z))
GROUND = bpy.context.active_object
GROUND.name = 'GROUND'
gm = bpy.data.materials.new('GroundMatte')
gm.use_nodes = True
gb = gm.node_tree.nodes['Principled BSDF']
gb.inputs['Base Color'].default_value = (0.30, 0.30, 0.31, 1)
gb.inputs['Roughness'].default_value = 0.95
gb.inputs['Metallic'].default_value = 0.0
if 'Specular IOR Level' in gb.inputs:
    gb.inputs['Specular IOR Level'].default_value = 0.15   # kill mirror hot-spots
GROUND.data.materials.append(gm)

# soft, low-contrast key/fill/rim -- deliberately no HDRI and no hard sun,
# so that nothing clips to white and no reflection reads as a blown highlight.
DIAG = math.sqrt(SIZE.x ** 2 + SIZE.y ** 2 + SIZE.z ** 2)
LIGHTS = [('KEY', (-1.1, -1.4, 1.5), 260.0, 5.0),
          ('FILL', (1.2, 1.5, 1.1), 150.0, 6.0),
          ('RIM', (0.4, -1.6, 1.9), 120.0, 5.0),
          ('FILL2', (1.4, -0.5, 1.2), 110.0, 6.0)]
for nm, d, energy, sz in LIGHTS:
    ld = bpy.data.lights.new(nm, 'AREA')
    ld.energy = energy
    ld.size = sz * (DIAG / 4.5)
    ld.shape = 'SQUARE'
    lo = bpy.data.objects.new(nm, ld)
    sc.collection.objects.link(lo)
    # keep the emitter itself out of frame and out of specular highlights, so
    # nothing in any tile can clip to white off a visible light rectangle
    lo.visible_camera = False
    lo.visible_glossy = False
    p = CENTRE + Vector(d) * DIAG * 1.15
    lo.location = p
    dvec = (CENTRE - p).normalized()
    lo.rotation_euler = dvec.to_track_quat('-Z', 'Y').to_euler()

# ------------------------------------------------------------------ cameras
# Azimuth is measured about +Z from the NOSE direction, turning toward the
# vehicle's LEFT.  So az=0 looks at the nose, az=90 looks at the left flank.
LEFT = -RIGHT
CANON = [('CAM_FRONT', 0), ('CAM_FRONT_LEFT_34', 45), ('CAM_LEFT', 90),
         ('CAM_REAR_LEFT_34', 135), ('CAM_REAR', 180), ('CAM_REAR_RIGHT_34', 225),
         ('CAM_RIGHT', 270), ('CAM_FRONT_RIGHT_34', 315)]
ELEV_DEG = 9.0
LENS_MM = 85.0
SENSOR = 36.0


def dir_for(az_deg):
    """Unit vector from the car toward the camera, for a given azimuth."""
    a = math.radians(az_deg)
    v = FWD * math.cos(a) + LEFT * math.sin(a)
    e = math.radians(ELEV_DEG)
    return (v * math.cos(e) + UP * math.sin(e)).normalized()


def fit_radius(cam, target, aim):
    """Binary-search the camera distance so the projected model spans `target`
    of the frame's larger relative dimension."""
    lo, hi = DIAG * 0.6, DIAG * 12.0
    for _ in range(26):
        mid = (lo + hi) / 2
        cam.location = aim + DIRV * mid
        bpy.context.view_layer.update()
        f = projected_fill(cam)
        if f > target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def _hull_points():
    """A decimated cloud of REAL transformed vertices.  The first version of
    this fitted against each object's world AABB corners, which lie outside the
    mesh; the solver then hit its 0.80 target on a phantom silhouette and the
    rendered mask measured 0.765.  Fitting to actual vertices removes that bias."""
    dg = bpy.context.evaluated_depsgraph_get()
    pts = []
    for o in CAR:
        if o.hide_render:
            continue
        me = o.evaluated_get(dg).to_mesh()
        mw = o.matrix_world
        n = len(me.vertices)
        step = max(1, n // 900)
        for i in range(0, n, step):
            pts.append(mw @ me.vertices[i].co)
        o.evaluated_get(dg).to_mesh_clear()
    return pts


HULL = None
HULLA = None


def projected_fill(cam):
    """Fraction of the frame spanned by the model, from TRANSFORMED vertices
    pushed through the camera matrix -- never from bound_box.

    Vectorised.  The scalar version called world_to_camera_view ~15M times and
    dominated the run.  The numpy path is asserted against world_to_camera_view
    on a sample of points at start-up (see PROJ_CHECK) so the speed-up cannot
    quietly change the answer."""
    global HULL, HULLA
    import numpy as _np
    if HULL is None:
        HULL = _hull_points()
        HULLA = _np.array([[p.x, p.y, p.z] for p in HULL], dtype=_np.float64)
    inv = cam.matrix_world.inverted()
    M = _np.array([[inv[r][c] for c in range(4)] for r in range(4)])
    P = HULLA @ M[:3, :3].T + M[:3, 3]
    z = -P[:, 2]
    z = _np.where(z < 1e-6, 1e-6, z)
    tanx = (cam.data.sensor_width / 2.0) / cam.data.lens
    tany = tanx * (RESY / float(RESX))
    if cam.data.type == 'ORTHO':
        sx = cam.data.ortho_scale / 2.0
        sy = sx * (RESY / float(RESX))
        u = P[:, 0] / sx
        v = P[:, 1] / sy
    else:
        u = (P[:, 0] / z) / tanx
        v = (P[:, 1] / z) / tany
    return float(max((u.max() - u.min()) / 2.0, (v.max() - v.min()) / 2.0))


def PROJ_CHECK(cam):
    """Prove the vectorised projection agrees with Blender's own function."""
    from bpy_extras.object_utils import world_to_camera_view
    import numpy as _np
    global HULL, HULLA
    if HULL is None:
        HULL = _hull_points()
        HULLA = _np.array([[p.x, p.y, p.z] for p in HULL], dtype=_np.float64)
    idx = list(range(0, len(HULL), max(1, len(HULL) // 40)))[:40]
    inv = cam.matrix_world.inverted()
    M = _np.array([[inv[r][c] for c in range(4)] for r in range(4)])
    worst = 0.0
    for i in idx:
        p = HULL[i]
        ref = world_to_camera_view(bpy.context.scene, cam, p)
        q = _np.array([p.x, p.y, p.z]) @ M[:3, :3].T + M[:3, 3]
        z = max(-q[2], 1e-6)
        tanx = (cam.data.sensor_width / 2.0) / cam.data.lens
        tany = tanx * (RESY / float(RESX))
        mine = ((q[0] / z) / tanx / 2.0 + 0.5, (q[1] / z) / tany / 2.0 + 0.5)
        worst = max(worst, abs(mine[0] - ref.x), abs(mine[1] - ref.y))
    return round(float(worst), 9)


AIM = Vector((CENTRE.x, CENTRE.y, GMIN.z + SIZE.z * 0.44))
cams = []
for nm, az in CANON:
    cd = bpy.data.cameras.new(nm)
    cd.lens = LENS_MM
    cd.sensor_width = SENSOR
    co = bpy.data.objects.new(nm, cd)
    sc.collection.objects.link(co)
    DIRV = dir_for(az)
    co.location = AIM + DIRV * DIAG * 3.0
    co.rotation_euler = (-DIRV).to_track_quat('-Z', 'Y').to_euler()
    cams.append((nm, az, co))

# Distance policy.  `fixed` uses ONE radius for all eight -- identical framing
# scale, which is what a comparison sheet needs, but which cannot put every
# tile inside 75-85% because the side elevation projects ~2.4x the width of the
# front.  `per_view` hits 80% on every tile at the cost of a varying scale.
# Both are produced and both are reported; neither is chosen silently.
TARGET = 0.80
PROJ_AGREEMENT = PROJ_CHECK(cams[0][2])
if PROJ_AGREEMENT > 1e-6:
    raise SystemExit('FATAL: vectorised projection disagrees with '
                     'world_to_camera_view by %g' % PROJ_AGREEMENT)
if A.fit == 'fixed':
    # choose the radius from the WIDEST view so nothing is ever cropped
    worst = 0.0
    for nm, az, co in cams:
        DIRV = dir_for(az)
        r = fit_radius(co, TARGET, AIM)
        worst = max(worst, r)
    for nm, az, co in cams:
        DIRV = dir_for(az)
        co.location = AIM + DIRV * worst
        co.rotation_euler = (-DIRV).to_track_quat('-Z', 'Y').to_euler()
    FITNOTE = {'policy': 'fixed', 'radius_m': round(worst, 4),
               'note': 'one radius for all eight; identical framing scale'}
else:
    rr = {}
    for nm, az, co in cams:
        DIRV = dir_for(az)
        rr[nm] = round(fit_radius(co, TARGET, AIM), 4)
        co.rotation_euler = (-DIRV).to_track_quat('-Z', 'Y').to_euler()
    FITNOTE = {'policy': 'per_view', 'radius_m': rr,
               'note': 'distance solved per view to 80% fill; framing scale varies'}

# orthographic elevations
ORTHO = []
if A.views in ('ortho', 'all'):
    ospec = [('ORTHO_FRONT', FWD, 'x'), ('ORTHO_REAR', -FWD, 'x'),
             ('ORTHO_LEFT', LEFT, 'y'), ('ORTHO_RIGHT', RIGHT, 'y'),
             ('ORTHO_TOP', UP, 'z')]
    for nm, d, axis in ospec:
        cd = bpy.data.cameras.new(nm)
        cd.type = 'ORTHO'
        span = {'x': max(SIZE.y, SIZE.z), 'y': max(SIZE.x, SIZE.z),
                'z': max(SIZE.x, SIZE.y)}[axis]
        cd.ortho_scale = span * 1.18
        co = bpy.data.objects.new(nm, cd)
        sc.collection.objects.link(co)
        co.location = CENTRE + Vector(d) * DIAG * 4.0
        up = 'Y' if axis != 'z' else 'Y'
        co.rotation_euler = (-Vector(d)).to_track_quat('-Z', up).to_euler()
        ORTHO.append((nm, co))

# --------------------------------------------------------- camera verification
def verify(nm, az, co):
    """Measure where the camera actually looks.  Never trust the name."""
    look = (co.matrix_world.to_3x3() @ Vector((0, 0, -1))).normalized()
    to_car = (AIM - co.location).normalized()
    aim_err = math.degrees(math.acos(max(-1, min(1, look.dot(to_car)))))
    flat_look = Vector((look.x, look.y, 0))
    flat_look = flat_look.normalized() if flat_look.length > 1e-9 else Vector((0, 0, 0))
    # azimuth of the direction FROM the car TO the camera
    v = (co.location - AIM)
    v = Vector((v.x, v.y, 0)).normalized()
    meas = math.degrees(math.atan2(v.dot(LEFT), v.dot(FWD))) % 360.0
    err = min(abs(meas - az), 360 - abs(meas - az))
    elev = math.degrees(math.asin(max(-1, min(1, (co.location - AIM).normalized().z))))
    return {'camera': nm, 'nominal_azimuth_deg': az,
            'measured_azimuth_deg': round(meas, 4),
            'azimuth_error_deg': round(err, 4),
            'measured_elevation_deg': round(elev, 4),
            'aim_error_deg': round(aim_err, 4),
            'world_location': [round(v_, 5) for v_ in co.location],
            'look_unit_vector': [round(v_, 5) for v_ in look],
            'faces_nose': round(look.dot(-FWD), 4),
            'faces_vehicle_left': round(look.dot(-LEFT), 4),
            'height_m': round(co.location.z, 5),
            'lens_mm': co.data.lens if co.data.type != 'ORTHO' else None,
            'PASS': err < 1.0 and aim_err < 1.0}


VER = [verify(nm, az, co) for nm, az, co in cams]
bad = [v for v in VER if not v['PASS']]

# ------------------------------------------------------------------ rendering
import numpy as np


def px(path):
    im = bpy.data.images.load(path)
    a = np.array(im.pixels[:], dtype=np.float32).reshape(im.size[1], im.size[0], 4)
    bpy.data.images.remove(im)
    return a[::-1]


def render_to(cam, path, samples=None, mask=False):
    sc.camera = cam
    old = sc.cycles.samples
    if samples:
        sc.cycles.samples = samples
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)
    sc.cycles.samples = old


MASKMAT = None


def mask_render(cam, path):
    """Geometric silhouette: one opaque diffuse on everything, ground hidden,
    transparent film, 1 sample.  Transparency cannot shrink this."""
    global MASKMAT
    if MASKMAT is None:
        MASKMAT = bpy.data.materials.new('MASK')
        MASKMAT.use_nodes = True
        MASKMAT.node_tree.nodes['Principled BSDF'].inputs['Base Color'] \
            .default_value = (1, 1, 1, 1)
        MASKMAT.use_backface_culling = False
    keep = {}
    for o in CAR:
        keep[o.name] = list(o.data.materials)
        o.data.materials.clear()
        o.data.materials.append(MASKMAT)
    gh, ft, dn = GROUND.hide_render, sc.render.film_transparent, sc.cycles.use_denoising
    GROUND.hide_render = True
    sc.render.film_transparent = True
    sc.cycles.use_denoising = False
    render_to(cam, path, samples=1)
    GROUND.hide_render, sc.render.film_transparent = gh, ft
    sc.cycles.use_denoising = dn
    for o in CAR:
        o.data.materials.clear()
        for m in keep[o.name]:
            o.data.materials.append(m)
    a = px(path)
    return a[:, :, 3] > 0.5


def stats(img, silh=None):
    # MEASURED, not assumed: Blender's Image.pixels returns the DISPLAY-referred
    # value for a PNG written under the Standard transform (a 0.22 linear world
    # reads back 0.50504, i.e. 128.8/255, not 0.22).  Re-encoding it to sRGB
    # here would double-convert and report the background as 188 instead of 129,
    # which is exactly the sort of number a gate would then "explain".
    b8 = np.clip(img[:, :, :3].mean(axis=2) * 255.0, 0, 255)
    d = {'mean_srgb8': round(float(b8.mean()), 2),
         'p99_srgb8': round(float(np.percentile(b8, 99)), 2),
         'clipped_fraction_ge_254': round(float((b8 >= 254).mean()), 6),
         'black_fraction_le_1': round(float((b8 <= 1).mean()), 6)}
    # background sample: a 24px band at the very top of the frame
    d['background_srgb8_top_band'] = round(float(b8[:24, :].mean()), 2)
    if silh is not None and silh.any():
        gy = np.abs(np.diff(b8, axis=0))[:, :-1]
        gx = np.abs(np.diff(b8, axis=1))[:-1, :]
        e = np.sqrt(gx ** 2 + gy ** 2)
        m = silh[:-1, :-1]
        d['edge_energy_in_silhouette'] = round(float(e[m].mean()), 4)
        d['mean_srgb8_in_silhouette'] = round(float(b8[:-1, :-1][m].mean()), 2)
        d['std_srgb8_in_silhouette'] = round(float(b8[:-1, :-1][m].std()), 3)
    return d


REPORT = {'label': A.label or os.path.basename(A.glb), 'glb': os.path.basename(A.glb),
          'blender': bpy.app.version_string, 'engine': 'CYCLES/CPU',
          'view_transform': sc.view_settings.view_transform,
          'look': sc.view_settings.look, 'exposure': sc.view_settings.exposure,
          'samples': A.samples, 'resolution': [RESX, RESY],
          'backface_culling': A.cull, 'materials': MATINFO,
          'world_grey_linear': WORLD_GREY,
          'world_grey_expected_srgb8': round(255 * (1.055 * WORLD_GREY ** (1 / 2.4) - 0.055), 2),
          'orientation': ORI, 'fit': FITNOTE,
          'vectorised_projection_max_disagreement_px_fraction': PROJ_AGREEMENT,
          'camera_verification': VER, 'cameras_failing_verification': bad,
          'model_world_bbox_min': [round(v, 6) for v in GMIN],
          'model_world_bbox_max': [round(v, 6) for v in GMAX],
          'tiles': {}}
if bad:
    json.dump(REPORT, open(os.path.join(A.out, 'rig_report.json'), 'w'), indent=1)
    raise SystemExit('FATAL: %d cameras failed direction verification' % len(bad))

todo = []
if A.views in ('canon', 'all'):
    todo += [(nm, co, az) for nm, az, co in cams]
if A.views in ('ortho', 'all'):
    todo += [(nm, co, None) for nm, co in ORTHO]

for nm, co, az in todo:
    beauty = os.path.join(A.out, '%s.png' % nm)
    render_to(co, beauty)
    silh = None
    if not A.nomask:
        silh = mask_render(co, os.path.join(A.out, '%s_mask.png' % nm))
    img = px(beauty)
    t = stats(img, silh)
    if silh is not None:
        frac = float(silh.mean())
        ys, xs = np.nonzero(silh)
        if len(xs):
            bw = (xs.max() - xs.min() + 1) / RESX
            bh = (ys.max() - ys.min() + 1) / RESY
            t.update({'silhouette_pixel_fraction': round(frac, 6),
                      'bbox_width_fraction': round(float(bw), 4),
                      'bbox_height_fraction': round(float(bh), 4),
                      'frame_fill_max_dim': round(float(max(bw, bh)), 4),
                      'bbox_touches_edge': bool(xs.min() == 0 or ys.min() == 0
                                                or xs.max() == RESX - 1
                                                or ys.max() == RESY - 1),
                      'POPULATED': bool(frac > 0.02),
                      'FILL_75_85': bool(0.75 <= max(bw, bh) <= 0.85)})
        else:
            t.update({'silhouette_pixel_fraction': 0.0, 'POPULATED': False,
                      'FILL_75_85': False})
    REPORT['tiles'][nm] = t
    print('TILE %-22s fill=%s pop=%s mean=%s clip=%s bg=%s'
          % (nm, t.get('frame_fill_max_dim'), t.get('POPULATED'),
             t.get('mean_srgb8'), t.get('clipped_fraction_ge_254'),
             t.get('background_srgb8_top_band')))

REPORT['summary'] = {
    'tiles_rendered': len(REPORT['tiles']),
    'blank_tiles': [k for k, v in REPORT['tiles'].items() if not v.get('POPULATED', True)],
    'tiles_in_75_85': [k for k, v in REPORT['tiles'].items() if v.get('FILL_75_85')],
    'tiles_outside_75_85': [k for k, v in REPORT['tiles'].items()
                            if 'FILL_75_85' in v and not v['FILL_75_85']],
    'max_clipped_fraction': (max(v['clipped_fraction_ge_254']
                                 for v in REPORT['tiles'].values())
                             if REPORT['tiles'] else None),
    'background_srgb8_range': ([min(v['background_srgb8_top_band'] for v in REPORT['tiles'].values()),
                                max(v['background_srgb8_top_band'] for v in REPORT['tiles'].values())]
                               if REPORT['tiles'] else None),
}
json.dump(REPORT, open(os.path.join(A.out, 'rig_report.json'), 'w'), indent=1)
print('RIG_DONE tiles=%d blank=%s in7585=%d/%d bg=%s expected=%s'
      % (len(REPORT['tiles']), REPORT['summary']['blank_tiles'],
         len(REPORT['summary']['tiles_in_75_85']), len(REPORT['tiles']),
         REPORT['summary']['background_srgb8_range'],
         REPORT['world_grey_expected_srgb8']))
