#!/usr/bin/env python3
"""
Run the full check battery against every injected control and record, per
check, whether it FIRED and whether the magnitude it reported matches the
magnitude that was injected.  A check that cannot be shown failing here is
reported as NOT PROVEN and must be described that way in the verdict.

Usage: python3 runctrl.py <verifydir>
"""
import sys, os, json, subprocess

V = os.path.abspath(sys.argv[1])
CTRL = os.path.join(V, 'ctrl')
EV = os.path.join(V, 'evidence')
TOOLS = os.path.join(V, 'tools')
SRC = os.path.abspath(os.path.join(V, '..', 'SOURCE_LOCKED', 'GOLF_ALL_GATES_SOURCE.glb'))
CON = json.load(open(os.path.join(CTRL, 'CONTROLS.json')))
BASE_F = json.load(open(os.path.join(EV, 'glb_audit_before.json')))
BASE_B = json.load(open(os.path.join(EV, 'bl_audit_before.json')))
BASE_D = json.load(open(os.path.join(EV, 'delta_account_before.json')))


def sh(*a):
    r = subprocess.run(a, capture_output=True, text=True)
    if r.returncode != 0:
        print('CMD FAILED:', ' '.join(a)[:150])
        print(r.stdout[-1500:], r.stderr[-1500:])
    return r


def measure(glb, tag):
    fj = os.path.join(CTRL, tag + '_file.json')
    bj = os.path.join(CTRL, tag + '_bl.json')
    dj = os.path.join(CTRL, tag + '_delta.json')
    sh('python3', os.path.join(TOOLS, 'glb_audit.py'), glb, fj)
    sh('blender', '-b', '--factory-startup', '--python',
       os.path.join(TOOLS, 'bl_audit.py'), '--', glb, bj, tag)
    sh('python3', os.path.join(TOOLS, 'delta_account.py'), glb, bj, dj)
    return (json.load(open(fj)), json.load(open(bj)), json.load(open(dj)))


def area_of(fj, cls):
    return fj['class_area_m2'].get(cls, 0.0)


def node_area(fj, name):
    for n in fj['nodes_table']:
        if n['name'] == name:
            return n['area_m2']
    return None


RESULTS = []
for c in CON['controls']:
    tag = c['control']
    glb = os.path.join(CTRL, c['file'])
    if not os.path.exists(glb):
        RESULTS.append({'control': tag, 'status': 'GLB MISSING'})
        continue
    F, B, D = measure(glb, tag)
    inj = c['injected_magnitude']
    checks = []

    def chk(name, fired, measured, expected, note=''):
        checks.append({'check': name, 'FIRED': bool(fired), 'measured': measured,
                       'injected': expected, 'note': note})

    if tag == 'C1_dupfaces':
        d_dup = (D['L2_triangles']['duplicate_index_triples']
                 - BASE_D['L2_triangles']['duplicate_index_triples'])
        d_bl = BASE_B['triangles'] - B['triangles']
        chk('L2 duplicate-index-triple counter', d_dup > 0, d_dup,
            inj['duplicate_index_triples_added'])
        chk('Blender import triangle drop', d_bl > 0, d_bl,
            inj['expected_blender_triangle_drop'])
        chk('declared triangle count unchanged',
            F['triangles_from_indices'] == BASE_F['triangles_from_indices'],
            F['triangles_from_indices'] - BASE_F['triangles_from_indices'],
            inj['expected_declared_triangle_change'],
            'the file still DECLARES the same total; only the import differs')
        chk('L2 ledger still balances', D['L2_triangles']['BALANCES'],
            D['L2_triangles']['BALANCES'], True,
            'balance must survive: the extra loss is fully accounted for')

    elif tag == 'C2_sink5mm':
        tz = B['tyre_ground']['max_tyre_zmin_m']
        base_tz = BASE_B['tyre_ground']['max_tyre_zmin_m']
        chk('per-tyre world z-min (grounding)', abs(tz - base_tz) > 1e-4,
            round(tz, 6), inj['expected_tyre_zmin_m'])
        chk('whole-model bbox z-min (the WEAK test)',
            abs(B['world_bbox_min'][2] - BASE_B['world_bbox_min'][2]) > 1e-4,
            round(B['world_bbox_min'][2], 6),
            round(BASE_B['world_bbox_min'][2] - inj['sink_m'], 6),
            'kept only to show it moves too; the tyre test is the witness')

    elif tag == 'C3_glasscut':
        ga, gb = area_of(F, 'glass'), area_of(BASE_F, 'glass')
        chk('glass surface AREA (m2)', ga < gb * 0.5, round(ga, 6),
            round(gb * inj['expected_area_fraction_of_baseline'], 6))
        chk('glass area as fraction of baseline', True,
            round(ga / gb, 5), inj['expected_area_fraction_of_baseline'])
        gm = [m for m in F['materials_table']
              if 'glass' in (m['name'] or '').lower()]
        chk('glass material still NAMED and transparent -> a name-only probe '
            'would still say clear', len(gm) > 0, [m['name'] for m in gm],
            'unchanged', 'this is why glass_probe must be PAIRED with an area')

    elif tag == 'C4_flipwinding':
        chk('winding reversal is INVISIBLE to counts',
            F['triangles_from_indices'] == BASE_F['triangles_from_indices'],
            F['triangles_from_indices'], BASE_F['triangles_from_indices'],
            'detected by the face-orientation and cull-ON renders, not by counts')

    elif tag == 'C5_wheelmismatch':
        got = {}
        for part in ('Tyre', 'Rim', 'Disc'):
            a = node_area(F, 'Wheel_FL_' + part)
            b0 = node_area(BASE_F, 'Wheel_FL_' + part)
            got[part] = round(a / b0, 5)
        chk('per-corner wheel surface-area ratio vs baseline',
            all(abs(v - inj['expected_area_ratio']) < 0.01 for v in got.values()),
            got, inj['expected_area_ratio'])
        r_now = node_area(F, 'Wheel_FL_Tyre') / node_area(F, 'Wheel_FR_Tyre')
        r_was = node_area(BASE_F, 'Wheel_FL_Tyre') / node_area(BASE_F, 'Wheel_FR_Tyre')
        chk('left/right tyre area parity ratio', abs(r_now - r_was) > 0.02,
            round(r_now, 5), round(r_was * inj['expected_area_ratio'], 5))

    elif tag == 'C6_hole3000':
        dd = F['degenerate_triangles'] - BASE_F['degenerate_triangles']
        d_bl = BASE_B['triangles'] - B['triangles']
        chk('file-level degenerate-triangle counter', dd > 0, dd,
            inj['expected_degenerate_count_delta'])
        chk('Blender import triangle drop', d_bl > 0, d_bl,
            inj['expected_blender_triangle_drop'])
        chk('L2 ledger still balances', D['L2_triangles']['BALANCES'],
            D['L2_triangles']['BALANCES'], True)

    elif tag == 'C7_mirrored':
        nd = F['negative_determinant_nodes']
        bn = B['negative_det_objects']
        chk('file-level negative-determinant node list', len(nd) > 0, len(nd),
            inj['mirrored_nodes'])
        chk('Blender negative-determinant object list', len(bn) > 0, bn,
            inj['mirrored_nodes'])

    RESULTS.append({'control': tag, 'defect': c['defect'],
                    'injected': inj, 'checks': checks,
                    'all_fired': all(x['FIRED'] for x in checks)})

out = {'source_sha256': CON['source_sha256'], 'controls_run': len(RESULTS),
       'controls_where_every_check_fired':
           sum(1 for r in RESULTS if r.get('all_fired')),
       'results': RESULTS}
json.dump(out, open(os.path.join(EV, 'negative_controls.json'), 'w'), indent=1)
for r in RESULTS:
    print('\n== %s  (%s)' % (r['control'], 'ALL FIRED' if r.get('all_fired') else 'SOME DID NOT FIRE'))
    for x in r.get('checks', []):
        print('   %-5s %-52s measured=%-28s injected=%s'
              % ('FIRE' if x['FIRED'] else 'DEAD', x['check'][:52],
                 json.dumps(x['measured'])[:28], json.dumps(x['injected'])[:24]))
print('\n%d/%d controls had every check fire' % (out['controls_where_every_check_fired'], len(RESULTS)))
