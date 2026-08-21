#!/usr/bin/env python3
"""
Explain the file-vs-Blender triangle delta, per object, from first principles.

HYPOTHESIS UNDER TEST: Blender's glTF importer welds vertices that share a
position (its vertex-dedup dictionary), then `mesh.validate()` deletes any
face left with fewer than three distinct corners.  If so, the count of
triangles in the FILE whose three corner POSITIONS are not all distinct must
equal the per-object triangle delta EXACTLY.  An exact match across 18
independent objects is a strong result; anything else means real geometry is
being lost and the delta is a defect, not a sliver.

Also reports zero-AREA triangles that have three distinct positions (true
slivers Blender keeps) so the two classes are never conflated.

Usage: python3 sliver_probe.py <file.glb> <bl_audit.json> <out.json>
"""
import sys, json, math
sys.path.insert(0, __file__.rsplit('/', 1)[0])
from glb_audit import load_glb, read_accessor, trs_matrix, mat_mul, xform, tri_area

SRC, BLJ, DST = sys.argv[1], sys.argv[2], sys.argv[3]
g, bins, _, _ = load_glb(SRC)
B = json.load(open(BLJ))
bl = {o['name']: o for o in B['objects']}

nodes, meshes = g['nodes'], g['meshes']
scene = g['scenes'][g.get('scene', 0)]
world, stack = {}, [(r, [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]) for r in scene['nodes']]
while stack:
    ni, pm = stack.pop()
    m = mat_mul(pm, trs_matrix(nodes[ni]))
    world[ni] = m
    for c in nodes[ni].get('children', []):
        stack.append((c, m))

rows, tot_coincident, tot_delta, exact = [], 0, 0, 0
extreme_dropped = []
for ni, nd in enumerate(nodes):
    if 'mesh' not in nd:
        continue
    name = nd.get('name', '')
    if name not in bl:
        continue
    m = world[ni]
    coincident = 0          # < 3 distinct POSITIONS  -> Blender deletes
    sliver = 0              # 3 distinct positions but area < 1e-12 m^2
    kept_min_x = 1e30
    drop_min_x = 1e30
    for p in meshes[nd['mesh']]['primitives']:
        if p.get('mode', 4) != 4:
            continue
        pos = read_accessor(g, bins, p['attributes']['POSITION'])
        idx = (read_accessor(g, bins, p['indices']) if 'indices' in p
               else [(i,) for i in range(len(pos))])
        wp = [xform(m, v) for v in pos]
        for t in range(0, len(idx) - 2, 3):
            a, b, c = idx[t][0], idx[t + 1][0], idx[t + 2][0]
            pa, pb, pc = pos[a], pos[b], pos[c]
            distinct = len({pa, pb, pc})
            xs = min(wp[a][0], wp[b][0], wp[c][0])
            if distinct < 3:
                coincident += 1
                drop_min_x = min(drop_min_x, xs)
            else:
                kept_min_x = min(kept_min_x, xs)
                if tri_area(wp[a], wp[b], wp[c]) < 1e-12:
                    sliver += 1
    delta = bl[name]['tris']
    d = None
    # file tris for this node
    ftris = 0
    for p in meshes[nd['mesh']]['primitives']:
        if p.get('mode', 4) != 4:
            continue
        ftris += (g['accessors'][p['indices']]['count'] // 3 if 'indices' in p
                  else g['accessors'][p['attributes']['POSITION']]['count'] // 3)
    d = ftris - bl[name]['tris']
    tot_delta += d
    tot_coincident += coincident
    if d or coincident or sliver:
        ok = (d == coincident)
        exact += 1 if ok else 0
        rows.append({'name': name, 'file_tris': ftris, 'blender_tris': bl[name]['tris'],
                     'delta': d, 'coincident_position_tris': coincident,
                     'true_zero_area_slivers_kept': sliver,
                     'delta_equals_coincident': ok,
                     'min_x_of_dropped': (round(drop_min_x, 6) if drop_min_x < 1e29 else None),
                     'min_x_of_kept': (round(kept_min_x, 6) if kept_min_x < 1e29 else None)})

mismatch = [r for r in rows if not r['delta_equals_coincident']]
out = {
    'hypothesis': 'per-object triangle delta == count of triangles whose three '
                  'corner POSITIONS are not all distinct (Blender welds then validates)',
    'objects_with_any_delta_or_coincident': len(rows),
    'objects_where_hypothesis_holds_exactly': exact,
    'objects_where_hypothesis_fails': len(mismatch),
    'total_file_minus_blender': tot_delta,
    'total_coincident_position_tris': tot_coincident,
    'VERDICT': ('EXPLAINED — every dropped triangle is zero-area by construction '
                '(two or three corners at the same point); no surface is lost'
                if not mismatch and tot_delta == tot_coincident
                else 'NOT EXPLAINED — real geometry may be missing'),
    'rows': rows,
    'mismatches': mismatch,
}
json.dump(out, open(DST, 'w'), indent=1)
print('delta=%d coincident=%d  holds=%d/%d  -> %s'
      % (tot_delta, tot_coincident, exact, len(rows), out['VERDICT'][:60]))
for r in rows:
    print('  %-28s d=%-5d coinc=%-5d slivers=%-4d dropX=%s keptX=%s'
          % (r['name'], r['delta'], r['coincident_position_tris'],
             r['true_zero_area_slivers_kept'], r['min_x_of_dropped'], r['min_x_of_kept']))
