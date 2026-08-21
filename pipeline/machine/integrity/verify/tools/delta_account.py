#!/usr/bin/env python3
"""
EXACT accounting for every file-vs-Blender difference.  Three independent
ledgers, each of which must balance to zero:

  L1 VERTICES.   file POSITION entries  =  index-referenced  +  unreferenced.
                 Blender's vertex count must equal the REFERENCED count.
                 (Refutes "Blender welds by position": if it welded, its count
                 would be BELOW the referenced count.)
  L2 TRIANGLES.  file triangles  =  Blender triangles
                                  + index-degenerate (a corner index repeated)
                                  + duplicate index-triples (BMesh refuses a
                                    second face on an already-used vertex set).
  L3 BBOX.       the file-side world bbox computed over REFERENCED vertices
                 only must equal Blender's world bbox, to float tolerance.
                 Any residue is genuinely missing geometry.

Position-triple duplicates are ALSO counted, and deliberately reported
separately: they over-count (1005 vs 924 on the source) precisely because
Blender does not weld, and quoting them would have mis-stated the ledger.

Usage: python3 delta_account.py <file.glb> <bl_audit.json> <out.json>
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

T = dict(file_verts=0, ref_verts=0, unref_verts=0, file_tris=0, bl_tris=0,
         idx_degen=0, dup_idx_triple=0, dup_pos_triple=0)
rows = []
rmin = [1e30] * 3
rmax = [-1e30] * 3
bad_bbox = []
for ni, nd in enumerate(nodes):
    if 'mesh' not in nd:
        continue
    name = nd.get('name', '')
    m = world[ni]
    fverts = rverts = ftris = degen = dupi = dupp = 0
    seen_i, seen_p = set(), set()
    omin = [1e30] * 3
    omax = [-1e30] * 3
    for pi, p in enumerate(meshes[nd['mesh']]['primitives']):
        if p.get('mode', 4) != 4:
            continue
        pos = read_accessor(g, bins, p['attributes']['POSITION'])
        fverts += len(pos)
        idx = (read_accessor(g, bins, p['indices']) if 'indices' in p
               else [(i,) for i in range(len(pos))])
        ftris += len(idx) // 3
        used = set()
        for t in range(0, len(idx) - 2, 3):
            a, b, c = idx[t][0], idx[t + 1][0], idx[t + 2][0]
            if a == b or b == c or a == c:
                degen += 1
                used.update((a, b, c))
                continue
            ki = (pi,) + tuple(sorted((a, b, c)))
            if ki in seen_i:
                dupi += 1
            else:
                seen_i.add(ki)
            kp = tuple(sorted((pos[a], pos[b], pos[c])))
            if kp in seen_p:
                dupp += 1
            else:
                seen_p.add(kp)
            used.update((a, b, c))
        rverts += len(used)
        for i in used:
            w = xform(m, pos[i])
            for k in range(3):
                if w[k] < omin[k]:
                    omin[k] = w[k]
                if w[k] > omax[k]:
                    omax[k] = w[k]
    for k in range(3):
        rmin[k] = min(rmin[k], omin[k])
        rmax[k] = max(rmax[k], omax[k])
    b = bl.get(name)
    T['file_verts'] += fverts
    T['ref_verts'] += rverts
    T['unref_verts'] += fverts - rverts
    T['file_tris'] += ftris
    T['idx_degen'] += degen
    T['dup_idx_triple'] += dupi
    T['dup_pos_triple'] += dupp
    if b:
        T['bl_tris'] += b['tris']
        # glTF is Y-UP, Blender is Z-UP: gltf (x,y,z) -> blender (x,-z,y)
        pred_min = [omin[0], -omax[2], omin[1]]
        pred_max = [omax[0], -omin[2], omax[1]]
        err = max(abs(pred_min[k] - b['wmin'][k]) for k in range(3))
        err = max(err, max(abs(pred_max[k] - b['wmax'][k]) for k in range(3)))
        if err > 1e-4:
            bad_bbox.append({'name': name, 'max_abs_err_m': round(err, 6),
                             'file_referenced_min': [round(v, 6) for v in pred_min],
                             'blender_min': b['wmin'],
                             'file_referenced_max': [round(v, 6) for v in pred_max],
                             'blender_max': b['wmax']})
        rows.append({'name': name, 'file_tris': ftris, 'bl_tris': b['tris'],
                     'delta': ftris - b['tris'], 'idx_degenerate': degen,
                     'duplicate_index_triples': dupi,
                     'duplicate_position_triples': dupp,
                     'balances': ftris - b['tris'] == degen + dupi,
                     'file_verts': fverts, 'referenced_verts': rverts,
                     'unreferenced_verts': fverts - rverts,
                     'bl_verts': b['verts'],
                     'verts_balance': rverts == b['verts'],
                     'bbox_max_abs_err_m': round(err, 7)})

L1 = {'file_position_entries': T['file_verts'],
      'index_referenced': T['ref_verts'],
      'unreferenced': T['unref_verts'],
      'blender_vertices': B['vertices'],
      'BALANCES': T['ref_verts'] == B['vertices'],
      'per_object_all_balance': all(r['verts_balance'] for r in rows)}
L2 = {'file_triangles': T['file_tris'], 'blender_triangles': T['bl_tris'],
      'delta': T['file_tris'] - T['bl_tris'],
      'index_degenerate': T['idx_degen'],
      'duplicate_index_triples': T['dup_idx_triple'],
      'sum': T['idx_degen'] + T['dup_idx_triple'],
      'BALANCES': (T['file_tris'] - T['bl_tris']) == T['idx_degen'] + T['dup_idx_triple'],
      'per_object_all_balance': all(r['balances'] for r in rows),
      'duplicate_POSITION_triples_for_contrast': T['dup_pos_triple'],
      'contrast_note': 'position-triple duplicates OVER-count; Blender does not '
                       'weld by position, as ledger L1 proves.'}
bl_min_pred = [rmin[0], -rmax[2], rmin[1]]
bl_max_pred = [rmax[0], -rmin[2], rmax[1]]
L3 = {'file_referenced_world_bbox_min_in_blender_axes': [round(v, 6) for v in bl_min_pred],
      'blender_world_bbox_min': B['world_bbox_min'],
      'file_referenced_world_bbox_max_in_blender_axes': [round(v, 6) for v in bl_max_pred],
      'blender_world_bbox_max': B['world_bbox_max'],
      'max_abs_err_m': round(max(
          max(abs(bl_min_pred[k] - B['world_bbox_min'][k]) for k in range(3)),
          max(abs(bl_max_pred[k] - B['world_bbox_max'][k]) for k in range(3))), 7),
      'objects_with_bbox_residue_over_0.1mm': bad_bbox,
      'BALANCES': len(bad_bbox) == 0}

out = {'source': B['source'], 'L1_vertices': L1, 'L2_triangles': L2, 'L3_bbox': L3,
       'ALL_THREE_LEDGERS_BALANCE': L1['BALANCES'] and L2['BALANCES'] and L3['BALANCES'],
       'per_object': rows}
json.dump(out, open(DST, 'w'), indent=1)
print('L1 verts : file=%d ref=%d unref=%d  blender=%d  BALANCES=%s'
      % (L1['file_position_entries'], L1['index_referenced'], L1['unreferenced'],
         L1['blender_vertices'], L1['BALANCES']))
print('L2 tris  : delta=%d = degen %d + dup-index-triple %d  BALANCES=%s  (pos-triple dups=%d, over-counts)'
      % (L2['delta'], L2['index_degenerate'], L2['duplicate_index_triples'],
         L2['BALANCES'], L2['duplicate_POSITION_triples_for_contrast']))
print('L3 bbox  : max abs err = %.7f m over %d objects  BALANCES=%s'
      % (L3['max_abs_err_m'], len(rows), L3['BALANCES']))
print('ALL THREE LEDGERS BALANCE: %s' % out['ALL_THREE_LEDGERS_BALANCE'])
