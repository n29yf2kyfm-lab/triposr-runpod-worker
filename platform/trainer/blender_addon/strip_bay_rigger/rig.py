"""Open/close controls INSIDE Blender for a rigged car.

One empty, `SB_Controls[.<car>]`, carries a 0..1 slider per moving part:
door_fl door_fr door_rl door_rr bonnet tailgate wheel_fl wheel_fr wheel_rl
wheel_rr. Every part hangs off a pivot empty placed on its measured hinge,
and a DRIVER turns the slider into motion — so scrubbing one number in the
N-panel opens a door exactly as the web trainer does.

The drivers are plain arithmetic (`p*-1.117`), which Blender evaluates without
"Auto Run Python Scripts", so the controls work in a fresh install.

Motion, in the same frame and with the same numbers as the web app:
  swinging door   about its forward vertical edge, 64 degrees, outward
  sliding door    out 7 cm, then back along the body by 82% of its length
  barn door       (van back doors) about its outer vertical edge, 100 degrees
  bonnet          about its rear (scuttle) edge, 52 degrees up
  tailgate / boot about its hinge edge, 62 degrees up
  wheel           straight out from the hub, 0.85 m
"""
import bpy, math, json
from mathutils import Vector
from .core import B, G, bbox

DOOR_OPEN = math.radians(64)
BONNET_OPEN = math.radians(52)
TAIL_OPEN = math.radians(62)
BARN_OPEN = math.radians(100)
WHEEL_OFF = 0.85


def _empty(name, loc, size=0.08, kind='PLAIN_AXES', coll=None):
    e = bpy.data.objects.new(name, None)
    e.empty_display_type = kind
    e.empty_display_size = size
    e.location = loc
    (coll or bpy.context.scene.collection).objects.link(e)
    return e


def _prop(ctl, key, desc):
    ctl[key] = 0.0
    ui = ctl.id_properties_ui(key)
    ui.update(min=0.0, max=1.0, soft_min=0.0, soft_max=1.0, subtype='FACTOR', description=desc)
    # ADDING a custom property does not tag the object as changed, so the
    # evaluated copy the drivers read keeps the OLD property set. The next
    # evaluation then fails to find the slider and marks the driver invalid
    # for good (see _revalidate).
    ctl.update_tag()


def _drive(obj, path, index, ctl, key, expr):
    fc = obj.driver_add(path, index)
    d = fc.driver
    d.type = 'SCRIPTED'
    v = d.variables.new()
    v.name = 'p'
    v.type = 'SINGLE_PROP'
    v.targets[0].id = ctl
    v.targets[0].data_path = f'["{key}"]'
    d.expression = expr
    return fc


def _revalidate(ctl):
    """Make every slider on this car live NOW.

    MEASURED FAILURE, 2026-09-23: on a freshly rigged car every driver was
    flagged invalid and no slider moved anything until the .blend was saved
    and reopened. Bisected over every combination of the rig's steps: a
    driver dies when the scene is evaluated once BEFORE its slider property
    exists and again after — the evaluated copy of the controls object still
    lacks the property, the lookup fails, and Blender never retries an
    invalid driver. So: tag the controls object, evaluate, THEN clear the
    flags and evaluate again. Clearing first and evaluating once (the first
    version of this function) re-killed them."""
    ctl.update_tag()
    bpy.context.view_layer.update()
    car = ctl.get('sb_car')
    for piv in bpy.data.objects:
        if piv.name.startswith('SB_pivot_') and piv.name.endswith('.' + car) and piv.animation_data:
            for fc in piv.animation_data.drivers:
                fc.driver.is_valid = True
                fc.is_valid = True
            piv.update_tag()
    bpy.context.view_layer.update()


def _hang(objs, pivot):
    """Parent `objs` to `pivot` without moving them."""
    for o in objs:
        mw = o.matrix_world.copy()
        o.parent = pivot
        o.matrix_parent_inverse = pivot.matrix_world.inverted()
        o.matrix_world = mw


def _door_drivers(ctl, piv, pid, m):
    """(Re)build one door's slider and drivers from its motion `m`."""
    for path in ('location', 'rotation_euler'):
        for i in range(3):
            piv.driver_remove(path, i)
    piv.location = piv['sb_home']
    piv.rotation_euler = (0, 0, 0)
    sx = 1 if pid[-1] == 'l' else -1
    hx, hy = piv['sb_home'][0], piv['sb_home'][1]
    if m.get('type') == 'barn':
        _prop(ctl, pid, f'{pid}: 0 shut, 1 swung open')
        # vertical hinge on the outer edge, free edge swings rearward;
        # left door (x>0) takes a negative angle, as a front door does
        _drive(piv, 'rotation_euler', 2, ctl, pid, f'p*{-sx * BARN_OPEN:.4f}')
    elif m.get('type') == 'slide':
        _prop(ctl, pid, f'{pid}: 0 shut, 1 slid fully back')
        # glTF +x is Blender +x; glTF -z (rearward) is Blender +y
        _drive(piv, 'location', 0, ctl, pid, f'{hx:.5f}+{sx * m["out"]:.4f}*min(1,p*4)')
        _drive(piv, 'location', 1, ctl, pid, f'{hy:.5f}+{m["back"]:.4f}*max(0,(p-0.25)/0.75)')
    else:
        _prop(ctl, pid, f'{pid}: 0 shut, 1 open')
        # rotation about glTF Y is rotation about Blender Z, same sign;
        # a LEFT door opens with a NEGATIVE angle (as in the web app)
        _drive(piv, 'rotation_euler', 2, ctl, pid, f'p*{-sx * DOOR_OPEN:.4f}')


def add_controls(parts, hinge, motion=None, car='car', rep=None):
    """Build pivots, sliders and drivers. Returns the controls empty. The
    car's report is stored on it, so Export can write it beside the GLB."""
    motion = motion or {}
    coll = bpy.context.scene.collection
    bpy.context.view_layer.update()
    ctl = _empty(f'SB_Controls.{car}', (0, 0, 0), 0.4, 'CUBE', coll)
    ctl['sb_car'] = car
    ctl['sb_report'] = json.dumps(rep or {'hinge': hinge, 'motion': motion})
    for os_ in parts.values():                  # so Export finds THIS car's parts only
        for o in os_:
            o['sb_car'] = car
    made = []

    for pid, h in hinge.items():
        if pid not in parts:
            continue
        piv = _empty(f'SB_pivot_{pid}.{car}', B((h['x'], h['y'], h['z'])), 0.12, 'ARROWS', coll)
        piv['sb_home'] = tuple(piv.location)
        piv['sb_pid'] = pid
        bpy.context.view_layer.update()
        _hang(parts[pid], piv)
        piv.parent = ctl
        key = {'panel_bonnet': 'bonnet'}.get(pid, pid)
        if pid.startswith('door_'):
            _door_drivers(ctl, piv, pid, motion.get(pid, {}))
        elif pid == 'panel_bonnet':
            _prop(ctl, key, 'bonnet: 0 shut, 1 up')
            _drive(piv, 'rotation_euler', 0, ctl, key, f'p*{-BONNET_OPEN:.4f}')
        elif pid == 'tailgate':
            _prop(ctl, key, 'tailgate or boot lid: 0 shut, 1 up')
            _drive(piv, 'rotation_euler', 0, ctl, key, f'p*{TAIL_OPEN:.4f}')
        made.append(key)

    for pid in ('wheel_fl', 'wheel_fr', 'wheel_rl', 'wheel_rr'):
        if pid not in parts:
            continue
        objs = parts[pid]
        vs = [o.matrix_world @ v.co for o in objs for v in o.data.vertices]
        c = sum(vs, Vector()) / len(vs)
        piv = _empty(f'SB_pivot_{pid}.{car}', c, 0.1, 'SPHERE', coll)
        bpy.context.view_layer.update()
        _hang(objs, piv)
        piv.parent = ctl
        _prop(ctl, pid, f'{pid}: 0 on, 1 off the hub')
        sx = 1 if pid[-1] == 'l' else -1
        _drive(piv, 'location', 0, ctl, pid, f'{piv.location.x:.5f}+{sx * WHEEL_OFF:.3f}*p')
        made.append(pid)

    ctl['sb_controls'] = ','.join(made)
    _revalidate(ctl)
    return ctl


def rear_doors_slide(ctl, slide):
    """Switch a car's rear SIDE doors between sliding and swinging, and record
    the ruling in its report so Export and the web app agree."""
    rep = json.loads(ctl.get('sb_report', '{}'))
    motion = rep.setdefault('motion', {})
    car = ctl['sb_car']
    for pid in ('door_rl', 'door_rr'):                  # measure the doors SHUT
        if pid in ctl:
            ctl[pid] = 0.0
    ctl.update_tag()
    bpy.context.view_layer.update()
    for pid in ('door_rl', 'door_rr'):
        piv = bpy.data.objects.get(f'SB_pivot_{pid}.{car}')
        if piv is None:
            continue
        if slide:
            objs = [o for o in piv.children]
            vs = [G(o.matrix_world @ v.co) for o in objs for v in o.data.vertices]
            b0, b1 = bbox(vs)
            motion[pid] = {'type': 'slide', 'out': 0.07, 'back': round(0.82 * (b1.z - b0.z), 3),
                           'why': 'set by hand in Blender'}
        else:
            motion.pop(pid, None)
        _door_drivers(ctl, piv, pid, motion.get(pid, {}))
    rep['override'] = {**rep.get('override', {}), 'door_rl': 'slide' if slide else 'swing',
                       'door_rr': 'slide' if slide else 'swing'}
    ctl['sb_report'] = json.dumps(rep)
    ctl.update_tag()
    _revalidate(ctl)


def reset(ctl):
    for k in (ctl.get('sb_controls') or '').split(','):
        if k:
            ctl[k] = 0.0
    ctl.update_tag()
    bpy.context.view_layer.update()
