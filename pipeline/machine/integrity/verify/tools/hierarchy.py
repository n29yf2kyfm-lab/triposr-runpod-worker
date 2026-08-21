#!/usr/bin/env python3
"""
Node hierarchy + transform table, straight from the glTF JSON.

Reports the TRS a node actually declares, the accumulated world matrix, and the
3x3 determinant.  The determinant is the mirroring witness: Stage 0 used
"zero negative determinants" to rule out mirrored nodes as the cause of the
wheel defect, and control C7 proves this column can detect one when it is there.

Also flags nodes whose scale is non-uniform or non-unit, since a viewer that
normalises by the largest axis will be wrong on those.

Usage: python3 hierarchy.py <file.glb> <out.json> <out.txt>
"""
import sys, json
sys.path.insert(0, __file__.rsplit('/', 1)[0])
from glb_audit import load_glb, trs_matrix, mat_mul, det3

SRC, OJ, OT = sys.argv[1], sys.argv[2], sys.argv[3]
g, _, _, _ = load_glb(SRC)
nodes = g.get('nodes', [])
scene = g['scenes'][g.get('scene', 0)]

parent = {}
for i, n in enumerate(nodes):
    for c in n.get('children', []):
        parent[c] = i

world = {}
depth = {}
order = []


def walk(i, pm, d):
    m = mat_mul(pm, trs_matrix(nodes[i]))
    world[i] = m
    depth[i] = d
    order.append(i)
    for c in nodes[i].get('children', []):
        walk(c, m, d + 1)


I = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
for r in scene['nodes']:
    walk(r, I, 0)

rows = []
for i in order:
    n = nodes[i]
    t = n.get('translation', [0, 0, 0])
    r = n.get('rotation', [0, 0, 0, 1])
    s = n.get('scale', [1, 1, 1])
    has_m = 'matrix' in n
    d = det3(world[i])
    rows.append({
        'node': i, 'name': n.get('name', ''), 'depth': depth[i],
        'parent': parent.get(i), 'mesh': n.get('mesh'),
        'camera': n.get('camera'),
        'declares_matrix': has_m,
        'translation': [round(v, 8) for v in t],
        'rotation_quat_xyzw': [round(v, 8) for v in r],
        'scale': [round(v, 8) for v in s],
        'is_identity_TRS': (not has_m and t == [0, 0, 0]
                            and list(r) == [0, 0, 0, 1] and list(s) == [1, 1, 1]),
        'scale_is_unit': all(abs(v - 1.0) < 1e-9 for v in s) and not has_m,
        'scale_is_uniform': (abs(s[0] - s[1]) < 1e-9 and abs(s[1] - s[2]) < 1e-9),
        'world_matrix_row_major': [round(v, 8) for v in world[i]],
        'world_det3': round(d, 9),
        'mirrored': d < 0,
    })

out = {
    'file': SRC.rsplit('/', 1)[-1],
    'nodes': len(nodes),
    'scene_roots': scene['nodes'],
    'max_depth': max(depth.values()) if depth else 0,
    'all_nodes_reachable_from_scene': len(order) == len(nodes),
    'nodes_declaring_matrix': [r['node'] for r in rows if r['declares_matrix']],
    'nodes_with_identity_TRS': sum(1 for r in rows if r['is_identity_TRS']),
    'nodes_with_non_unit_scale': [r['name'] for r in rows if not r['scale_is_unit']],
    'nodes_with_non_uniform_scale': [r['name'] for r in rows if not r['scale_is_uniform']],
    'MIRRORED_NODES': [r['name'] for r in rows if r['mirrored']],
    'n_mirrored': sum(1 for r in rows if r['mirrored']),
    'determinant_min': min(r['world_det3'] for r in rows) if rows else None,
    'determinant_max': max(r['world_det3'] for r in rows) if rows else None,
    'rows': rows,
}
json.dump(out, open(OJ, 'w'), indent=1)

with open(OT, 'w') as f:
    f.write('NODE HIERARCHY AND TRANSFORM TABLE  --  %s\n' % out['file'])
    f.write('nodes=%d  roots=%s  max depth=%d  all reachable=%s\n'
            % (out['nodes'], out['scene_roots'], out['max_depth'],
               out['all_nodes_reachable_from_scene']))
    f.write('mirrored (det<0) nodes: %d %s\n' % (out['n_mirrored'], out['MIRRORED_NODES']))
    f.write('determinant range: %.9f .. %.9f\n\n'
            % (out['determinant_min'], out['determinant_max']))
    f.write('%-4s %-34s %-6s %-26s %-22s %-22s %10s\n'
            % ('idx', 'name', 'mesh', 'translation', 'rotation(xyzw)', 'scale', 'det3'))
    f.write('-' * 150 + '\n')
    for r in rows:
        f.write('%-4d %-34s %-6s %-26s %-22s %-22s %10.6f\n'
                % (r['node'], ('  ' * r['depth']) + r['name'][:32],
                   str(r['mesh']),
                   ','.join('%.4f' % v for v in r['translation']),
                   ','.join('%.3f' % v for v in r['rotation_quat_xyzw']),
                   ','.join('%.4f' % v for v in r['scale']),
                   r['world_det3']))
print('nodes=%d  roots=%s  mirrored=%d  identity TRS=%d/%d  non-unit scale=%d'
      % (out['nodes'], out['scene_roots'], out['n_mirrored'],
         out['nodes_with_identity_TRS'], out['nodes'],
         len(out['nodes_with_non_unit_scale'])))
print('det range %.9f .. %.9f' % (out['determinant_min'], out['determinant_max']))
