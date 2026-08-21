#!/usr/bin/env python3
"""
Consolidated acceptance metrics.  Consumes glb_audit + bl_audit + delta_account
for ONE file and emits one machine-readable verdict block per criterion.

Two traps from CLAUDE.md are wired in explicitly:

  * GLASS.  `glass_probe` alone is insufficient -- it returns clear/proven on
    glazing cut to 2.5% of its area, on a file with every KHR extension
    stripped, and on a car whose windscreen is called `carpaint`.  So the
    glazing verdict here is ALWAYS a pair: a transparency verdict AND a glass
    surface AREA in m^2 with its share of the exterior.  Neither alone decides.
  * MATERIALS.  trimesh drops KHR material extensions on any round-trip while
    alphaMode survives, so a probe can report "transparent" off alphaMode on a
    file whose transmission extension is gone.  The WRITTEN material table is
    reported, extension by extension.

Usage: python3 metrics.py <file.json> <bl.json> <delta.json> <out.json> [baseline.json]
"""
import sys, json, math

FJ, BJ, DJ, OUT = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
BASE = json.load(open(sys.argv[5])) if len(sys.argv) > 5 else None
F = json.load(open(FJ))
B = json.load(open(BJ))
D = json.load(open(DJ))
obj = {o['name']: o for o in B['objects']}
fno = {n['name']: n for n in F['nodes_table']}

# ------------------------------------------------------------------ 1 glazing
glass_nodes = [n for n in F['nodes_table'] if n['class'] == 'glass']
glass_area = sum(n['area_m2'] for n in glass_nodes)
total_area = sum(n['area_m2'] for n in F['nodes_table'])
gmats = [m for m in F['materials_table'] if m['area_m2'] > 0 and (
    any(k in (m['name'] or '').lower() for k in
        ('glass', 'window', 'windscreen', 'glazing', 'pane'))
    and not any(k in (m['name'] or '').lower() for k in
                ('surr', 'frame', 'trim', 'lamp', 'mirror')))]


def transparent(m):
    a = (m.get('baseColorFactor') or [1, 1, 1, 1])[3]
    return (m.get('alphaMode') in ('BLEND', 'MASK') or a < 0.999
            or 'KHR_materials_transmission' in m.get('extensions', []))


trans_mats = [m for m in F['materials_table'] if transparent(m)]
probe = ('clear' if any(transparent(m) for m in gmats) else
         ('ambiguous' if not gmats else 'opaque'))
GLASS = {
    'probe_verdict': probe,
    'PAIRED_glass_surface_area_m2': round(glass_area, 6),
    'glass_share_of_total_surface': round(glass_area / total_area, 6) if total_area else 0,
    'glass_nodes': [n['name'] for n in glass_nodes],
    'glass_named_materials': [m['name'] for m in gmats],
    'glass_materials_detail': [{'name': m['name'], 'alphaMode': m['alphaMode'],
                                'baseColorAlpha': (m.get('baseColorFactor') or [1, 1, 1, 1])[3],
                                'extensions': m['extensions'],
                                'area_m2': m['area_m2']} for m in gmats],
    'any_transparent_material_in_file': len(trans_mats) > 0,
    'NOTE': 'the probe verdict is NOT sufficient on its own; read it together '
            'with the area.  A file can score "clear" on glazing cut to 2.5%.',
}
if BASE:
    ba = sum(n['area_m2'] for n in BASE['nodes_table'] if n['class'] == 'glass')
    GLASS['baseline_glass_area_m2'] = round(ba, 6)
    GLASS['glass_area_ratio_vs_baseline'] = round(glass_area / ba, 6) if ba else None
    GLASS['GLASS_LOST'] = bool(ba and glass_area < ba * 0.9)

# --------------------------------------------------------------- 2 wheel parity
CORNERS = ['FL', 'FR', 'RL', 'RR']
PARTS = ['Tyre', 'Rim', 'Disc']
wheels = {}
for c in CORNERS:
    for p in PARTS:
        nm = 'Wheel_%s_%s' % (c, p)
        if nm in fno:
            wheels[nm] = {'tris': fno[nm]['tris'], 'area_m2': fno[nm]['area_m2'],
                          'wmin': fno[nm]['wmin'], 'wmax': fno[nm]['wmax']}


def span(nm, k):
    w = wheels.get(nm)
    return round(w['wmax'][k] - w['wmin'][k], 6) if w else None


pairs = []
for ax in ('F', 'R'):
    for p in PARTS:
        a, b = 'Wheel_%sL_%s' % (ax, p), 'Wheel_%sR_%s' % (ax, p)
        if a in wheels and b in wheels:
            ar, br = wheels[a]['area_m2'], wheels[b]['area_m2']
            ta, tb = wheels[a]['tris'], wheels[b]['tris']
            # rolling radius from the vertical span (glTF Y / index 1)
            da, db = span(a, 1), span(b, 1)
            pairs.append({
                'pair': '%s%s' % (ax, p), 'left_node': a, 'right_node': b,
                'tris_L': ta, 'tris_R': tb, 'tri_delta': ta - tb,
                'tri_ratio': round(ta / tb, 5) if tb else None,
                'area_L_m2': ar, 'area_R_m2': br,
                'area_ratio': round(ar / br, 5) if br else None,
                'area_pct_diff': round(100 * (ar - br) / br, 3) if br else None,
                'vertical_span_L_m': da, 'vertical_span_R_m': db,
                'span_pct_diff': round(100 * (da - db) / db, 3) if db else None,
            })
worst = max((abs(p['area_pct_diff']) for p in pairs if p['area_pct_diff'] is not None),
            default=None)
# Is L/R parity MEASURED, or guaranteed by construction?  If the two sides
# reference the SAME mesh index, every count and area below is trivially equal
# and proves nothing on its own -- the brief warns explicitly that a name-only
# hierarchy check reports 20/20 on two nodes sharing one mesh.  When that is the
# case the parity number is a structural guarantee and the load-bearing evidence
# becomes the placement transforms plus the rendered left/right comparison.
shared = F.get('meshes_shared_by_multiple_nodes', {})
node_mesh = {n['name']: n['mesh'] for n in F['nodes_table']}
wheel_shared = {}
for ax in ('F', 'R'):
    for p_ in PARTS:
        a, b = 'Wheel_%sL_%s' % (ax, p_), 'Wheel_%sR_%s' % (ax, p_)
        if a in node_mesh and b in node_mesh:
            wheel_shared['%s%s' % (ax, p_)] = (node_mesh[a] == node_mesh[b])
by_construction = bool(wheel_shared) and all(wheel_shared.values())

WHEELS = {
    'pairs': pairs,
    'worst_left_right_area_pct_diff': worst,
    'PARITY_IS_BY_CONSTRUCTION_SHARED_MESH': by_construction,
    'left_right_share_same_mesh_index': wheel_shared,
    'EVIDENCE_STATUS': ('structural guarantee -- L and R are the SAME mesh, so '
                        'equal counts/areas are tautological.  The verdict rests '
                        'on the placement transforms (must be a rotation, det>0, '
                        'not a mirror) and on the rendered L/R comparison.'
                        if by_construction else
                        'independently measured -- L and R are distinct meshes'),
    'IDENTICAL_ACROSS_SIDES': bool(worst is not None and worst < 1.0),
    'NOTE': 'determinant sign is reported separately; equal determinants only '
            'rule out MIRRORING, they do not make the two sides identical.',
    'negative_determinant_nodes': F['negative_determinant_nodes'],
}

# ------------------------------------------------------------- 3 ground contact
TG = B['tyre_ground']
GROUND = {
    'per_tyre_world_zmin_m': TG['per_tyre_world_zmin_m'],
    'worst_tyre_zmin_m': TG['max_tyre_zmin_m'],
    'best_tyre_zmin_m': TG['min_tyre_zmin_m'],
    'whole_model_zmin_m': B['world_bbox_min'][2],
    'lowest_object': min(B['objects'], key=lambda o: o['wmin'][2])['name'],
    'ALL_FOUR_TYRES_ON_GROUND_1mm': bool(
        TG['max_tyre_zmin_m'] is not None and abs(TG['max_tyre_zmin_m']) <= 0.001
        and abs(TG['min_tyre_zmin_m']) <= 0.001),
    'NOTE': 'measured from the TYRE nodes, not the whole-model bbox: '
            'viewer_check.py passed a car whose front tyres were 183 mm up '
            'because it read the whole-model minimum.',
}

# ------------------------------------------------------- 4 payload / dead weight
PAYLOAD = {
    'declared_positions': F.get('declared_positions'),
    'referenced_positions': F.get('referenced_positions'),
    'unreferenced_positions': F.get('unreferenced_positions'),
    'unreferenced_fraction': F.get('unreferenced_fraction'),
    'file_bytes': F['bytes'],
    'bbox_declared_vs_referenced_max_abs_diff_m':
        F.get('bbox_declared_vs_referenced_max_abs_diff_m'),
    'bbox_declared': [F['world_bbox_min'], F['world_bbox_max']],
    'bbox_referenced_only': [F.get('world_bbox_min_referenced_only'),
                             F.get('world_bbox_max_referenced_only')],
    'WHICH_ONE_THE_VIEWER_SEES': 'referenced_only',
}
if BASE:
    PAYLOAD['baseline_unreferenced_positions'] = BASE.get('unreferenced_positions')
    PAYLOAD['baseline_file_bytes'] = BASE['bytes']

# ---------------------------------------------------------------- 5 structure
STRUCT = {
    'nodes': F['counts']['nodes'], 'meshes': F['counts']['meshes'],
    'primitives': F['counts']['primitives'], 'materials': F['counts']['materials'],
    'textures': F['counts']['textures'], 'cameras_in_file': F['counts']['cameras'],
    'camera_names': F['camera_names'],
    'extensionsUsed': F['extensionsUsed'],
    'extensionsRequired': F['extensionsRequired'],
    'orphan_nodes_not_in_scene': F['orphan_nodes_not_in_scene'],
    'meshes_unreferenced': F['meshes_unreferenced'],
    'meshes_shared_by_multiple_nodes': F['meshes_shared_by_multiple_nodes'],
    'nodes_without_mesh': F['nodes_without_mesh'],
    'nan_vertex_components': F['nan_vertex_components'],
    'degenerate_triangles': F['degenerate_triangles'],
    'hidden_at_render': B['hidden_at_render'],
    'MATERIAL_TABLE_AS_WRITTEN': [
        {'name': m['name'], 'alphaMode': m['alphaMode'],
         'doubleSided': m['doubleSided'], 'extensions': m['extensions'],
         'baseColorFactor': m['baseColorFactor'], 'area_m2': m['area_m2']}
        for m in F['materials_table']],
}
if BASE:
    bm = {m['name']: m for m in BASE['materials_table']}
    lost = []
    for m in F['materials_table']:
        o = bm.get(m['name'])
        if o and set(o['extensions']) - set(m['extensions']):
            lost.append({'material': m['name'],
                         'extensions_lost': sorted(set(o['extensions']) - set(m['extensions']))})
    STRUCT['KHR_EXTENSIONS_LOST_VS_BASELINE'] = lost
    STRUCT['ANY_KHR_EXTENSION_LOST'] = len(lost) > 0

# ------------------------------------------------------------------- 6 ledgers
LEDGERS = {'L1_vertices': D['L1_vertices'], 'L2_triangles': D['L2_triangles'],
           'L3_bbox': D['L3_bbox'],
           'ALL_THREE_BALANCE': D['ALL_THREE_LEDGERS_BALANCE']}
if BASE:
    LEDGERS['baseline_delta'] = None

out = {'file': F['file'], 'sha256': F['sha256'], 'bytes': F['bytes'],
       'triangles_declared': F['triangles_from_indices'],
       'triangles_imported': B['triangles'],
       'GLAZING': GLASS, 'WHEEL_PARITY': WHEELS, 'GROUND_CONTACT': GROUND,
       'PAYLOAD': PAYLOAD, 'STRUCTURE': STRUCT, 'LEDGERS': LEDGERS}
json.dump(out, open(OUT, 'w'), indent=1)

print('GLAZING  probe=%s  area=%.4f m2 (%.2f%% of surface)  nodes=%d'
      % (GLASS['probe_verdict'], GLASS['PAIRED_glass_surface_area_m2'],
         100 * GLASS['glass_share_of_total_surface'], len(glass_nodes)))
print('WHEELS   worst L/R area diff = %s%%   identical=%s   neg-det nodes=%s'
      % (WHEELS['worst_left_right_area_pct_diff'], WHEELS['IDENTICAL_ACROSS_SIDES'],
         WHEELS['negative_determinant_nodes']))
for p in pairs:
    print('   %-6s tris %7d/%-7d (%+6d)  area %.5f/%.5f  %+7.2f%%  span %+6.2f%%'
          % (p['pair'], p['tris_L'], p['tris_R'], p['tri_delta'],
             p['area_L_m2'], p['area_R_m2'], p['area_pct_diff'], p['span_pct_diff']))
print('GROUND   worst tyre z-min = %s m  all four grounded=%s  lowest object=%s (%.6f)'
      % (GROUND['worst_tyre_zmin_m'], GROUND['ALL_FOUR_TYRES_ON_GROUND_1mm'],
         GROUND['lowest_object'], GROUND['whole_model_zmin_m']))
print('PAYLOAD  unreferenced=%s (%.1f%%)  bbox declared-vs-referenced diff=%s m'
      % (PAYLOAD['unreferenced_positions'], 100 * (PAYLOAD['unreferenced_fraction'] or 0),
         PAYLOAD['bbox_declared_vs_referenced_max_abs_diff_m']))
print('LEDGERS  all three balance = %s' % LEDGERS['ALL_THREE_BALANCE'])
