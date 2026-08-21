#!/usr/bin/env python3
# ============================== SUPERSEDED ==================================
# This file is kept ONLY as a record of two refuted hypotheses.  Its printed
# verdict ("PARTIAL / NOT EXPLAINED - real geometry may be missing") is
# WITHDRAWN and must not be quoted.
#
#   sliver_probe.py  tested "three corner POSITIONS not all distinct".
#                    REFUTED: holds for 0 of 18 objects; 4 of 928.
#   sliver_probe2.py tested duplicate POSITION triples, counted PER MESH.
#                    WRONG TWICE OVER: glTF indices are LOCAL to a primitive's
#                    own POSITION accessor, so a per-mesh count is invalid; and
#                    Blender does not weld by position at all (ledger L1 proves
#                    it: Blender's vertex count equals the index-REFERENCED
#                    position count exactly).  It returned 1005 against a true
#                    924 and was superseded before being reported.
#
# THE CORRECT PREDICATE, and the live one, is in delta_account.py: extras
# beyond the first, counted PER PRIMITIVE, on sorted INDEX triples.
#   924 duplicate index triples + 4 index-degenerate = 928 = the exact delta.
# ============================================================================
"""
Second attempt at the 928-triangle delta.  Hypothesis 1 (coincident corner
positions) was REFUTED: only 4 of 928.  Two further mechanisms are tested here,
together, because Blender's glTF importer welds vertices by POSITION and then
runs `mesh.validate()`:

  H2  DUPLICATE FACES.  After welding, two triangles occupying the same three
      positions become the same face; validate() keeps one and deletes the rest.
  H3  UNREFERENCED VERTICES.  POSITION entries no triangle indexes.  These
      inflate the FILE bbox but are dropped on import, which is the candidate
      explanation for Bumper_Front_Paint's 29 mm of phantom nose.

A mechanism is accepted only if it reproduces the per-object delta EXACTLY on
all 18 affected objects.  Partial agreement is reported as partial.

Usage: python3 sliver_probe2.py <file.glb> <bl_audit.json> <out.json>
"""
import sys, json
sys.path.insert(0, __file__.rsplit('/', 1)[0])
from glb_audit import load_glb, read_accessor, trs_matrix, mat_mul, xform

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

rows = []
tot = {'delta': 0, 'dupface': 0, 'coincident': 0, 'unref_verts': 0}
h2_exact = h2_fail = 0
for ni, nd in enumerate(nodes):
    if 'mesh' not in nd:
        continue
    name = nd.get('name', '')
    if name not in bl:
        continue
    m = world[ni]
    seen = set()
    dupface = coincident = ftris = 0
    used = set()
    allpos = []
    for p in meshes[nd['mesh']]['primitives']:
        if p.get('mode', 4) != 4:
            continue
        pos = read_accessor(g, bins, p['attributes']['POSITION'])
        base = len(allpos)
        allpos.extend(pos)
        idx = (read_accessor(g, bins, p['indices']) if 'indices' in p
               else [(i,) for i in range(len(pos))])
        ftris += len(idx) // 3
        for t in range(0, len(idx) - 2, 3):
            a, b, c = idx[t][0], idx[t + 1][0], idx[t + 2][0]
            used.add(base + a); used.add(base + b); used.add(base + c)
            key = tuple(sorted((pos[a], pos[b], pos[c])))
            if len(set(key)) < 3:
                coincident += 1
                continue
            if key in seen:
                dupface += 1
            else:
                seen.add(key)
    unref = len(allpos) - len(used)
    # world x-min over UNREFERENCED positions only
    ux = None
    if unref:
        um = [xform(m, allpos[i]) for i in range(len(allpos)) if i not in used]
        ux = round(min(v[0] for v in um), 6)
    d = ftris - bl[name]['tris']
    tot['delta'] += d
    tot['dupface'] += dupface
    tot['coincident'] += coincident
    tot['unref_verts'] += unref
    if d or dupface or coincident or unref:
        ok = (d == dupface + coincident)
        h2_exact += 1 if ok else 0
        h2_fail += 0 if ok else 1
        rows.append({'name': name, 'file_tris': ftris, 'blender_tris': bl[name]['tris'],
                     'delta': d, 'duplicate_faces': dupface,
                     'coincident_corner_tris': coincident,
                     'delta_equals_dup_plus_coincident': ok,
                     'unreferenced_vertices': unref,
                     'unref_world_xmin': ux,
                     'file_xmin': None, 'blender_xmin': bl[name]['wmin'][0]})

out = {
 'H2_duplicate_faces_plus_H1_coincident': {
   'objects_tested': len(rows), 'exact': h2_exact, 'failed': h2_fail,
   'total_delta': tot['delta'],
   'total_duplicate_faces': tot['dupface'],
   'total_coincident': tot['coincident'],
   'sum_dup_plus_coincident': tot['dupface'] + tot['coincident'],
   'VERDICT': ('EXPLAINED IN FULL' if (h2_fail == 0 and
               tot['delta'] == tot['dupface'] + tot['coincident'])
               else 'PARTIAL / NOT EXPLAINED')},
 'H3_unreferenced_vertices': {
   'total_unreferenced_positions': tot['unref_verts'],
   'note': 'these inflate the FILE-side bbox and are dropped on import'},
 'rows': rows,
}
json.dump(out, open(DST, 'w'), indent=1)
v = out['H2_duplicate_faces_plus_H1_coincident']
print('delta=%d  dupfaces=%d + coincident=%d = %d   exact=%d/%d  -> %s'
      % (v['total_delta'], v['total_duplicate_faces'], v['total_coincident'],
         v['sum_dup_plus_coincident'], v['exact'], v['objects_tested'], v['VERDICT']))
print('unreferenced vertices in file: %d' % tot['unref_verts'])
for r in rows:
    print('  %-28s d=%-5d dup=%-5d coinc=%-3d %s unref=%-6d unrefXmin=%s blXmin=%.6f'
          % (r['name'], r['delta'], r['duplicate_faces'], r['coincident_corner_tris'],
             'OK ' if r['delta_equals_dup_plus_coincident'] else 'MISS',
             r['unreferenced_vertices'], r['unref_world_xmin'], r['blender_xmin']))
