"""Self-test for the Strip Bay Rigger. Run after ANY change to rig.py / core.py.

    blender -b --factory-startup --python selftest.py              # no car needed
    blender -b --factory-startup --python selftest.py -- GLB_DIR   # + every car in it

1. DRIVER LIFE. Every combination of the rig's setup steps must leave a
   slider that moves its part in the SAME session. This is the test that
   caught the add-on shipping dead sliders: every driver on a freshly rigged
   car was flagged invalid and nothing moved until the .blend was reopened.
   A saved-and-reloaded .blend hides that bug, so this never reloads.
2. EVERY SLIDER ON REAL CARS (with GLB_DIR): rig each car through the same
   code the panel uses, move every slider to 1 and back, and require the part
   to move the right way — doors outward (or back, for sliding and barn
   doors), bonnet and tailgate up, wheels straight out 0.85 m — and to return
   exactly. Refused cars are listed, not failed.

Exit code 0 only when everything passed.
"""
import bpy, sys, os, itertools
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from strip_bay_rigger import core, rig        # noqa: E402

fails = []


def clear():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)


# ── 1. driver life over every ordering the rig can produce ──────────────
for U, PB, PA, R in itertools.product([0, 1], repeat=4):
    if PB and PA:
        continue
    clear()
    c = rig._empty('SB_Controls.t', (0, 0, 0))
    c['sb_car'] = 't'
    p = rig._empty('SB_pivot_door_fl.t', (1, 0, 0))
    if U:
        bpy.context.view_layer.update()
    if PB:
        p.parent = c
    rig._prop(c, 'k', 'test')
    rig._drive(p, 'rotation_euler', 2, c, 'k', 'p*2')
    if PA:
        p.parent = c
    if R:
        rig._revalidate(c)
    c['k'] = 1.0
    c.update_tag()
    bpy.context.view_layer.update()
    ok = p.animation_data.drivers[0].driver.is_valid and abs(p.rotation_euler.z - 2) < 1e-6
    if not ok:
        fails.append(f'driver dead: update-first={U} parent-before={PB} parent-after={PA} revalidate={R}')
print(f'SELFTEST driver life: {11 - len(fails)}/11 orderings live')


# ── 2. every slider on real cars ────────────────────────────────────────
def G(v):
    return Vector((v.x, v.z, -v.y))


def cen(objs):
    vs = [G(o.matrix_world @ v.co) for o in objs for i, v in enumerate(o.data.vertices) if i % 9 == 0]
    return sum(vs, Vector()) / len(vs)


args = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
if args:
    d = args[0]
    ov = core.load_overrides(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                          'strip_bay_rigger', 'overrides.json'),
                             os.path.join(d, 'overrides.json'))
    clear()
    for f in sorted(x for x in os.listdir(d) if x.lower().endswith(('.glb', '.gltf'))):
        car = os.path.splitext(f)[0]
        try:
            rep, parts = core.process_file(os.path.join(d, f), None, None, ov.get(car))
        except core.Refused as e:
            print(f'SELFTEST {car}: refused ({e}) — not a failure')
            continue
        ctl = rig.add_controls(parts, rep['hinge'], rep.get('motion'), car, rep)
        n = 0
        for k in [k for k in ctl['sb_controls'].split(',') if k]:
            pid = {'bonnet': 'panel_bonnet'}.get(k, k)
            objs = parts[pid]
            a = cen(objs)
            ctl[k] = 1.0; ctl.update_tag(); bpy.context.view_layer.update()
            b = cen(objs)
            ctl[k] = 0.0; ctl.update_tag(); bpy.context.view_layer.update()
            back = (cen(objs) - a).length < 1e-4
            m, side = b - a, (1 if a.x > 0 else -1)
            if pid.startswith('door_b'):
                ok = m.z < -0.2
            elif pid.startswith('door_'):
                ok = m.x * side > 0.15 or m.z < -0.5
            elif pid in ('panel_bonnet', 'tailgate'):
                ok = m.y > 0.1
            else:
                ok = abs(m.x - side * 0.85) < 0.01
            if not (ok and back):
                fails.append(f'{car} {k}: moved ({m.x:+.2f},{m.y:+.2f},{m.z:+.2f}), '
                             f"{'returns' if back else 'does NOT return'}")
            n += 1
        print(f'SELFTEST {car}: {n} sliders checked')

print('SELFTEST', 'PASS' if not fails else 'FAIL')
for f in fails:
    print('   ', f)
sys.exit(1 if fails else 0)
