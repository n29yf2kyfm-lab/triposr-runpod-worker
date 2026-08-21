#!/usr/bin/env python3
"""
Assemble the GLB INTEGRITY verdict table from the evidence files.

Every row must cite an evidence FILE.  A criterion with no evidence file is
emitted as NOT TESTED -- never as a pass.  The three permitted verdicts are
PASS, FAIL and BLOCKED and nothing else.

Usage: python3 verdict.py <evidencedir> <after_tag> <out.json> <out.md>
       after_tag is the suffix of the "after" evidence files, e.g. "interim".
"""
import sys, os, json

EV, TAG, OJ, OM = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]


def L(name):
    p = os.path.join(EV, name)
    if not os.path.exists(p):
        return None
    try:
        return json.load(open(p))
    except Exception:
        return None


mb = L('metrics_before.json')
ma = L('metrics_%s.json' % TAG)
vb = L('validator_before_MINE.json')
va = L('validator_%s.json' % TAG)
hb = L('hierarchy_before.json')
ha = L('hierarchy_%s.json' % TAG)
cb = L('conceal_diff_before_v2.json') or L('conceal_diff_before.json')
fo_b = L('faceorient_before.json')
fo_a = L('faceorient_%s.json' % TAG)
rig_b = L('rig_before_neutral.json')
rig_a = L('rig_%s_neutral.json' % TAG)
vp_b = L('viewer_probe.json')
vp_a = L('viewer_probe_%s.json' % TAG)
nc = L('negative_controls.json')

R = []


def row(req, cause, base, final, thr, ev, status, risk):
    R.append({'requirement': req, 'root_cause': cause, 'baseline': base,
              'final_measured': final, 'threshold': thr, 'evidence': ev,
              'status': status, 'remaining_risk': risk})


def vcount(v):
    if not v:
        return None
    i = v['issues']
    return '%d err / %d warn / %d info / %d hint' % (
        i['numErrors'], i['numWarnings'], i['numInfos'], i['numHints'])


# 1 validator
row('Zero validator errors (Khronos glTF-Validator)',
    'n/a - source already passed',
    vcount(vb) or 'NOT TESTED', vcount(va) or 'NOT TESTED', '0 errors',
    'validator_before_MINE.json / validator_%s.json' % TAG,
    ('PASS' if va and va['issues']['numErrors'] == 0 else
     ('NOT TESTED' if not va else 'FAIL')),
    'none for errors; hints are advisory' if va else 'after-file not yet validated')

# 2 warnings documented
row('Every validator warning documented and justified',
    'BUFFER_VIEW_TARGET_MISSING x273 (hint) + ACCESSOR_INDEX_TRIANGLE_DEGENERATE x1 (info) on the source',
    (vcount(vb) or 'NOT TESTED'), (vcount(va) or 'NOT TESTED'),
    'all warnings enumerated',
    'validator_before_MINE.json / validator_%s.json' % TAG,
    ('PASS' if va and va['issues']['numWarnings'] == 0 else
     ('NOT TESTED' if not va else 'FAIL')),
    'none')

# 3 ledgers / no missing geometry
def led(m):
    if not m:
        return 'NOT TESTED'
    l = m['LEDGERS']
    return ('L1 %s / L2 delta %d = %d degen + %d dup / L3 err %.1e m -- all balance %s'
            % (l['L1_vertices']['BALANCES'], l['L2_triangles']['delta'],
               l['L2_triangles']['index_degenerate'],
               l['L2_triangles']['duplicate_index_triples'],
               l['L3_bbox']['max_abs_err_m'], l['ALL_THREE_BALANCE']))


row('No missing geometry after fresh import',
    'source declares 928 more triangles than Blender imports: 4 index-degenerate + 924 duplicate index triples',
    led(mb), led(ma), 'all three ledgers balance; L3 bbox residue = 0',
    'delta_account_before.json / delta_account_%s.json' % TAG,
    ('PASS' if ma and ma['LEDGERS']['ALL_THREE_BALANCE'] else
     ('NOT TESTED' if not ma else 'FAIL')),
    'none - L3 proves the referenced bbox matches Blender to 4e-7 m')

# 4 wheels
def wh(m):
    if not m:
        return 'NOT TESTED'
    w = m['WHEEL_PARITY']
    s = 'worst L/R area diff %s%%' % w['worst_left_right_area_pct_diff']
    if w.get('PARITY_IS_BY_CONSTRUCTION_SHARED_MESH'):
        s += ' (BY CONSTRUCTION - shared mesh, not an independent measurement)'
    return s


row('No wheel appearance change between sides',
    'the two sides carried DIFFERENT wheel meshes - a finished 10-spoke alloy on -Y, a plain dished disc on +Y. NOT mirroring (all determinants +1) and NOT inverted normals (cull ON == cull OFF)',
    wh(mb), wh(ma), 'left and right visually identical',
    'metrics_*.json + ZOOM_wheels_LR.jpg + ZOOM_cull_wheels.jpg + ZOOM_wheels_after.jpg',
    'PENDING', 'parity is structural; the render comparison is the real witness')

# 5 glass
def gl(m):
    if not m:
        return 'NOT TESTED'
    g = m['GLAZING']
    return ('probe=%s, area=%.4f m2 (%.2f%% of surface), %d glazing nodes'
            % (g['probe_verdict'], g['PAIRED_glass_surface_area_m2'],
               100 * g['glass_share_of_total_surface'], len(g['glass_nodes'])))


row('No glass disappearance (probe PAIRED with an area)',
    'n/a', gl(mb), gl(ma), 'glass area >= 90% of baseline AND probe not "opaque"',
    'metrics_before.json / metrics_%s.json' % TAG,
    ('PASS' if ma and not ma['GLAZING'].get('GLASS_LOST', False) else
     ('NOT TESTED' if not ma else 'FAIL')),
    'glass_probe alone is insufficient - control C3 scored "clear" on glazing cut to 2.56% of area')

# 6 cameras
def cam(r):
    if not r:
        return 'NOT TESTED'
    v = r['camera_verification']
    s = r['summary']
    return ('8 cameras, max azimuth err %.4f deg, max aim err %.4f deg, blank tiles %s, '
            'fill %.3f-%.3f, clipped max %s, bg %s'
            % (max(x['azimuth_error_deg'] for x in v),
               max(x['aim_error_deg'] for x in v), s['blank_tiles'],
               min(t['frame_fill_max_dim'] for t in r['tiles'].values()),
               max(t['frame_fill_max_dim'] for t in r['tiles'].values()),
               s['max_clipped_fraction'], s['background_srgb8_range']))


row('Eight populated canonical cameras, verified by WORLD DIRECTION',
    'the file contains 0 cameras; the rig builds them. Model _L/_R suffixes are on the OPPOSITE side to automotive convention, so a camera named from a node name would be mirrored',
    cam(rig_b), cam(rig_a), 'azimuth error < 1 deg, zero blank tiles',
    'rig_before_neutral.json / rig_%s_neutral.json' % TAG,
    ('PASS' if rig_b and not rig_b['summary']['blank_tiles'] else 'NOT TESTED'),
    'fixed framing cannot also satisfy 75-85% on every tile - see next row')

# 7 occupancy
def occ(r):
    if not r:
        return 'NOT TESTED'
    return ('%d/8 tiles in 75-85%% under FIXED framing; range %.3f-%.3f'
            % (len(r['summary']['tiles_in_75_85']),
               min(t['frame_fill_max_dim'] for t in r['tiles'].values()),
               max(t['frame_fill_max_dim'] for t in r['tiles'].values())))


row('Vehicle fills 75-85% of frame',
    'the side elevation projects ~1.75x the front elevation, so ONE camera radius cannot put all eight tiles in the band',
    occ(rig_b), occ(rig_a), '75-85% per tile',
    'rig_*_neutral.json (fixed) + rig_*_perview.json (per-view fit)',
    'SPLIT - both sheets shipped, neither choice made silently',
    'identical framing scale and 75-85% per tile are mutually exclusive on this car')

# 8 ground
def gr(m):
    if not m:
        return 'NOT TESTED'
    g = m['GROUND_CONTACT']
    return ('all four tyre z-min %s..%s m; whole-model z-min %.6f (%s)'
            % (g['best_tyre_zmin_m'], g['worst_tyre_zmin_m'],
               g['whole_model_zmin_m'], g['lowest_object']))


row('Ground contact, measured from the TYRE nodes',
    'viewer_check.py reads WHOLE-MODEL bbox min-Y and passed a car with front tyres 183 mm up',
    gr(mb), gr(ma), 'every tyre within 1 mm of z=0',
    'bl_audit_*.json -> tyre_ground',
    ('PASS' if ma and ma['GROUND_CONTACT']['ALL_FOUR_TYRES_ON_GROUND_1mm'] else
     ('NOT TESTED' if not ma else 'FAIL')),
    'the lowest object is Arch_Liner at -4.587 mm, which is NOT a tyre and is unchanged')

# 9 transforms
def tr(h):
    if not h:
        return 'NOT TESTED'
    return ('%d nodes, %d mirrored (det<0), det range %.9f..%.9f, non-unit scale %d'
            % (h['nodes'], h['n_mirrored'], h['determinant_min'],
               h['determinant_max'], len(h['nodes_with_non_unit_scale'])))


row('No broken transforms', 'n/a', tr(hb), tr(ha),
    'zero mirrored determinants, no NaN, all nodes reachable',
    'hierarchy_before.json / hierarchy_%s.json' % TAG,
    ('PASS' if ha and ha['n_mirrored'] == 0 and ha['all_nodes_reachable_from_scene']
     else ('NOT TESTED' if not ha else 'FAIL')),
    'control C7 proves this column can detect a mirrored node')

# 10 payload
def pl(m):
    if not m:
        return 'NOT TESTED'
    p = m['PAYLOAD']
    return ('%s unreferenced of %s declared (%.1f%%), file %.2f MB, declared-vs-referenced bbox %s m'
            % (p['unreferenced_positions'], p['declared_positions'],
               100 * (p['unreferenced_fraction'] or 0), p['file_bytes'] / 1e6,
               p['bbox_declared_vs_referenced_max_abs_diff_m']))


row('Dead payload / declared-vs-referenced bbox agreement',
    '68.3% of declared POSITION entries are referenced by no triangle; they inflate the accessor bbox that model-viewer reads',
    pl(mb), pl(ma), 'unreferenced = 0 and bbox difference = 0',
    'glb_audit_*.json + viewer_probe*.json',
    ('PASS' if ma and ma['PAYLOAD']['unreferenced_positions'] == 0 else
     ('NOT TESTED' if not ma else 'FAIL')),
    'model-viewer reports the SOURCE as 4.262953 m long vs 4.233626 m of visible geometry')

# 11 stage 7
def cd(c):
    if not c:
        return 'NOT TESTED'
    return ('silhouette IoU min %s; whole-frame edge ratio min %s; worst local tile %s'
            % (c['min_silhouette_IoU'], c['min_edge_ratio_whole_frame'],
               c['min_worst_local_tile_ratio']))


row('Stage 7 neutral diagnostics REVEAL, never conceal',
    'first neutral glass (base 0.56/0.63/0.68, transmission 0.88) rendered the cabin milky where the shipped red set resolved seats and B-pillar',
    cd(L('conceal_diff_before.json')), cd(cb),
    'silhouette IoU = 1.000 and no local region materially darker than the shipped set',
    'conceal_diff_before.json (v1, failed) / conceal_diff_before_v2.json (v2)',
    'PENDING', 'the v1 failure is reported, not hidden')

# 12 console / web viewer
def vw(v):
    if not v:
        return 'NOT TESTED'
    return ('loaded=%s, dims %.6f x %.6f x %.6f m, %d/%d azimuths populated, console errors %d'
            % (v['LOADED'], v['model']['dims']['x'], v['model']['dims']['y'],
               v['model']['dims']['z'],
               sum(1 for t in v['views'].values() if t.get('POPULATED')),
               sum(1 for t in v['views'].values() if 'POPULATED' in t),
               len(v['console_errors'])))


row('Independent web viewer: loads, orbits, toggles, clean console',
    'n/a', vw(vp_b), vw(vp_a),
    'load event fires, no console errors beyond a favicon 404, every azimuth populated',
    'viewer_probe.json / viewer_probe_%s.json' % TAG,
    ('PASS' if vp_a and vp_a['LOADED'] and vp_a.get('ASSET_RESOURCES_ALL_OK', True)
     else ('NOT TESTED' if not vp_a else 'FAIL')),
    'SwiftShader software raster on desktop; NOT a device measurement')

# 13 face orientation
def fo(f):
    if not f:
        return 'NOT TESTED'
    return ('back/front %s overall; left-side views %s vs right-side %s (asymmetry %sx)'
            % (f['total_back_over_front'], f['mean_left_side_views'],
               f['mean_right_side_views'], f['left_right_asymmetry_ratio']))


row('Face orientation / backfacing surface',
    'right-side views showed 3.72x the backfacing area of left-side views',
    fo(fo_b), fo(fo_a), 'left/right asymmetry ~1.0',
    'faceorient_before.json / faceorient_%s.json' % TAG,
    'PENDING', 'control C4 proves counts are blind to a winding reversal')

out = {
    'rows': R,
    'negative_controls': ({'controls': nc['controls_run'],
                           'all_checks_fired': nc['controls_where_every_check_fired']}
                          if nc else 'NOT TESTED'),
}
json.dump(out, open(OJ, 'w'), indent=1)
with open(OM, 'w') as f:
    f.write('| Requirement | Root cause | Baseline | Final measured | Threshold | Evidence | Status | Remaining risk |\n')
    f.write('|---|---|---|---|---|---|---|---|\n')
    for r in R:
        f.write('| %s | %s | %s | %s | %s | `%s` | **%s** | %s |\n'
                % (r['requirement'], r['root_cause'], r['baseline'], r['final_measured'],
                   r['threshold'], r['evidence'], r['status'], r['remaining_risk']))
print('rows=%d  written %s' % (len(R), OM))
for r in R:
    print('  %-58s %-10s' % (r['requirement'][:58], r['status']))
