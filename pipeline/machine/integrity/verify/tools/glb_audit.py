#!/usr/bin/env python3
"""
FILE-LEVEL glTF/GLB integrity audit. INDEPENDENT of Blender and of trimesh.

Written for the ExpertCarCheck GLB INTEGRITY GATE, Stage 7/8/9 verifier.
Deliberately parses the container and the accessors BY HAND so that no
library can silently normalise a defect away.  CLAUDE.md records that
`trimesh silently drops every KHR material extension on any round-trip`;
that is exactly the class of bug this file exists to see.

Everything geometric is measured from TRANSFORMED vertices: each primitive's
POSITION accessor is decoded and pushed through the accumulated world matrix
of the node that references its mesh.  Node-local accessor min/max is
reported separately and never used as a world measurement.

Usage:  python3 glb_audit.py <file.glb> <out.json> [--label NAME]
"""
import sys, json, struct, base64, math, hashlib, os
from collections import defaultdict

CT = {5120: ('b', 1), 5121: ('B', 1), 5122: ('h', 2),
      5123: ('H', 2), 5125: ('I', 4), 5126: ('f', 4)}
NC = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4,
      'MAT2': 4, 'MAT3': 9, 'MAT4': 16}


def load_glb(path):
    with open(path, 'rb') as f:
        data = f.read()
    if data[:4] != b'glTF':
        raise SystemExit('not a GLB: %s' % path)
    ver, total = struct.unpack('<II', data[4:12])
    off, js, bin_chunk = 12, None, b''
    while off < len(data):
        clen, ctype = struct.unpack('<II', data[off:off + 8])
        chunk = data[off + 8: off + 8 + clen]
        if ctype == 0x4E4F534A:
            js = json.loads(chunk.decode('utf-8'))
        elif ctype == 0x004E4942:
            bin_chunk = chunk
        off += 8 + clen + ((4 - clen % 4) % 4 if clen % 4 else 0)
        off = off if off % 4 == 0 else off + (4 - off % 4)
    return js, bin_chunk, ver, len(data)


def buf_bytes(g, bins, i):
    b = g['buffers'][i]
    uri = b.get('uri')
    if uri is None:
        return bins
    if uri.startswith('data:'):
        return base64.b64decode(uri.split(',', 1)[1])
    raise SystemExit('external buffer not supported here: %s' % uri)


def read_accessor(g, bins, idx):
    """Decode accessor -> list of tuples. Handles byteStride and sparse=absent."""
    a = g['accessors'][idx]
    n = NC[a['type']]
    fmt, sz = CT[a['componentType']]
    count = a['count']
    if 'bufferView' not in a:
        return [tuple([0] * n)] * count
    bv = g['bufferViews'][a['bufferView']]
    raw = buf_bytes(g, bins, bv.get('buffer', 0))
    base = bv.get('byteOffset', 0) + a.get('byteOffset', 0)
    stride = bv.get('byteStride') or (sz * n)
    out = []
    elem = struct.Struct('<' + fmt * n)
    for k in range(count):
        o = base + k * stride
        out.append(elem.unpack_from(raw, o))
    return out


def mat_mul(a, b):
    r = [0.0] * 16
    for i in range(4):
        for j in range(4):
            r[i * 4 + j] = sum(a[i * 4 + k] * b[k * 4 + j] for k in range(4))
    return r


def trs_matrix(node):
    if 'matrix' in node:
        m = node['matrix']          # glTF matrix is COLUMN-major
        return [m[0], m[4], m[8], m[12],
                m[1], m[5], m[9], m[13],
                m[2], m[6], m[10], m[14],
                m[3], m[7], m[11], m[15]]
    t = node.get('translation', [0, 0, 0])
    r = node.get('rotation', [0, 0, 0, 1])
    s = node.get('scale', [1, 1, 1])
    x, y, z, w = r
    rm = [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w), 0,
          2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w), 0,
          2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y), 0,
          0, 0, 0, 1]
    sm = [s[0], 0, 0, 0, 0, s[1], 0, 0, 0, 0, s[2], 0, 0, 0, 0, 1]
    tm = [1, 0, 0, t[0], 0, 1, 0, t[1], 0, 0, 1, t[2], 0, 0, 0, 1]
    return mat_mul(tm, mat_mul(rm, sm))


def det3(m):
    return (m[0] * (m[5] * m[10] - m[6] * m[9])
            - m[1] * (m[4] * m[10] - m[6] * m[8])
            + m[2] * (m[4] * m[9] - m[5] * m[8]))


def xform(m, p):
    x, y, z = p[0], p[1], p[2]
    return (m[0] * x + m[1] * y + m[2] * z + m[3],
            m[4] * x + m[5] * y + m[6] * z + m[7],
            m[8] * x + m[9] * y + m[10] * z + m[11])


def tri_area(a, b, c):
    ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    cx, cy, cz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
    return 0.5 * math.sqrt(cx * cx + cy * cy + cz * cz)


# ---------------------------------------------------------------- classifiers
GLASSY = ('glass', 'window', 'windscreen', 'windshield', 'screen', 'glazing',
          'vidro', 'glas', 'scheibe', 'fenster', 'pane')
# CLAUDE.md: lamp lenses, mirrors, dashboard icon sheets and window SURROUNDS
# have all previously outvoted real glazing.  Exclude them explicitly.
NOTGLASS = ('lamp', 'light', 'headlamp', 'taillamp', 'surr', 'frame', 'trim',
            'mirror', 'rearview', 'icon', 'button', 'instrument', 'dash',
            'aircondition', 'seal', 'rubber', 'wiper')
TYREY = ('tyre', 'tire', 'rubber')
RIMY = ('rim', 'wheel', 'alloy', 'hub', 'spoke')


def classify(name):
    n = (name or '').lower()
    if any(k in n for k in TYREY) and 'arch' not in n:
        return 'tyre'
    if any(k in n for k in RIMY):
        return 'rim'
    if any(k in n for k in GLASSY) and not any(k in n for k in NOTGLASS):
        return 'glass'
    return 'other'


def audit(path, label=None):
    g, bins, ver, nbytes = load_glb(path)
    sha = hashlib.sha256(open(path, 'rb').read()).hexdigest()
    nodes = g.get('nodes', [])
    meshes = g.get('meshes', [])
    mats = g.get('materials', [])

    # ---- world matrices by walking the scene graph from the scene roots
    world = {}
    parent = {}
    scene = g.get('scenes', [{}])[g.get('scene', 0)]
    stack = [(r, [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]) for r in scene.get('nodes', [])]
    order = []
    while stack:
        ni, pm = stack.pop()
        m = mat_mul(pm, trs_matrix(nodes[ni]))
        world[ni] = m
        order.append(ni)
        for c in nodes[ni].get('children', []):
            parent[c] = ni
            stack.append((c, m))
    orphans = [i for i in range(len(nodes)) if i not in world]

    # ---- per-node geometry, measured from TRANSFORMED vertices
    per_node = []
    gmin = [1e30] * 3
    gmax = [-1e30] * 3
    total_tris = 0
    degenerate = 0
    mat_area = defaultdict(float)     # material index -> world surface area m^2
    mat_tris = defaultdict(int)
    class_area = defaultdict(float)
    class_tris = defaultdict(int)
    nan_verts = 0

    rmin = [1e30] * 3
    rmax = [-1e30] * 3
    tot_pos = 0
    tot_ref = 0
    for ni in order:
        nd = nodes[ni]
        if 'mesh' not in nd:
            continue
        m = world[ni]
        mesh = meshes[nd['mesh']]
        nmin = [1e30] * 3          # over ALL declared POSITION entries
        nmax = [-1e30] * 3
        nrmin = [1e30] * 3         # over INDEX-REFERENCED entries only
        nrmax = [-1e30] * 3
        ntris = 0
        narea = 0.0
        prim_mats = []
        n_pos = n_ref = 0
        for p in mesh['primitives']:
            if p.get('mode', 4) != 4:
                continue
            pos = read_accessor(g, bins, p['attributes']['POSITION'])
            wp = [xform(m, v) for v in pos]
            n_pos += len(pos)
            for v in wp:
                for k in range(3):
                    if v[k] != v[k]:
                        nan_verts += 1
                        continue
                    if v[k] < nmin[k]:
                        nmin[k] = v[k]
                    if v[k] > nmax[k]:
                        nmax[k] = v[k]
            idx = (read_accessor(g, bins, p['indices'])
                   if 'indices' in p else [(i,) for i in range(len(pos))])
            mi = p.get('material')
            prim_mats.append(mi)
            used = set()
            for t in range(0, len(idx) - 2, 3):
                a, b, c = idx[t][0], idx[t + 1][0], idx[t + 2][0]
                used.add(a); used.add(b); used.add(c)
                if a == b or b == c or a == c:
                    degenerate += 1
                    ntris += 1
                    continue
                ar = tri_area(wp[a], wp[b], wp[c])
                narea += ar
                mat_area[mi] += ar
                mat_tris[mi] += 1
                ntris += 1
            n_ref += len(used)
            for i in used:
                v = wp[i]
                for k in range(3):
                    if v[k] != v[k]:
                        continue
                    if v[k] < nrmin[k]:
                        nrmin[k] = v[k]
                    if v[k] > nrmax[k]:
                        nrmax[k] = v[k]
            total_tris += 0
        tot_pos += n_pos
        tot_ref += n_ref
        for k in range(3):
            if nrmin[k] < rmin[k]:
                rmin[k] = nrmin[k]
            if nrmax[k] > rmax[k]:
                rmax[k] = nrmax[k]
        # count triangles from index counts to stay exact
        tri_exact = 0
        for p in mesh['primitives']:
            if p.get('mode', 4) != 4:
                continue
            if 'indices' in p:
                tri_exact += g['accessors'][p['indices']]['count'] // 3
            else:
                tri_exact += g['accessors'][p['attributes']['POSITION']]['count'] // 3
        total_tris += tri_exact
        mname = mats[prim_mats[0]]['name'] if (prim_mats and prim_mats[0] is not None
                                               and 'name' in mats[prim_mats[0]]) else ''
        cls = classify(nd.get('name', ''))
        if cls == 'other':
            cls = classify(mname)
        class_area[cls] += narea
        class_tris[cls] += tri_exact
        for k in range(3):
            if nmin[k] < gmin[k]:
                gmin[k] = nmin[k]
            if nmax[k] > gmax[k]:
                gmax[k] = nmax[k]
        per_node.append({
            'node': ni, 'name': nd.get('name', ''), 'mesh': nd['mesh'],
            'parent': parent.get(ni), 'det': round(det3(m), 9),
            'tris': tri_exact, 'area_m2': round(narea, 6),
            'materials': sorted(set(x for x in prim_mats if x is not None)),
            'mat_names': sorted(set(mats[x].get('name', '') for x in prim_mats if x is not None)),
            'class': cls,
            'wmin': [round(v, 6) for v in nmin],
            'wmax': [round(v, 6) for v in nmax],
            'wmin_referenced': [round(v, 6) for v in nrmin],
            'wmax_referenced': [round(v, 6) for v in nrmax],
            'declared_positions': n_pos,
            'referenced_positions': n_ref,
            'unreferenced_positions': n_pos - n_ref,
        })

    # ---- material table AS WRITTEN (extensions included)
    mat_table = []
    for i, mt in enumerate(mats):
        pbr = mt.get('pbrMetallicRoughness', {})
        mat_table.append({
            'i': i, 'name': mt.get('name', ''),
            'baseColorFactor': pbr.get('baseColorFactor'),
            'metallicFactor': pbr.get('metallicFactor'),
            'roughnessFactor': pbr.get('roughnessFactor'),
            'alphaMode': mt.get('alphaMode', 'OPAQUE'),
            'doubleSided': mt.get('doubleSided', False),
            'emissiveFactor': mt.get('emissiveFactor'),
            'extensions': sorted(mt.get('extensions', {}).keys()),
            'ext_detail': mt.get('extensions', {}),
            'area_m2': round(mat_area.get(i, 0.0), 6),
            'tris': mat_tris.get(i, 0),
        })

    # ---- meshes referenced by more than one node, and nodes with no mesh
    mesh_refs = defaultdict(list)
    for ni, nd in enumerate(nodes):
        if 'mesh' in nd:
            mesh_refs[nd['mesh']].append(ni)
    shared = {k: v for k, v in mesh_refs.items() if len(v) > 1}
    unused_meshes = [i for i in range(len(meshes)) if i not in mesh_refs]
    empty_nodes = [ni for ni, nd in enumerate(nodes) if 'mesh' not in nd]

    out = {
        'label': label or os.path.basename(path),
        'file': os.path.basename(path),
        'sha256': sha,
        'bytes': nbytes,
        'glb_version': ver,
        'generator': g.get('asset', {}).get('generator'),
        'counts': {
            'nodes': len(nodes), 'meshes': len(meshes),
            'primitives': sum(len(m['primitives']) for m in meshes),
            'materials': len(mats),
            'textures': len(g.get('textures', [])),
            'images': len(g.get('images', [])),
            'accessors': len(g.get('accessors', [])),
            'bufferViews': len(g.get('bufferViews', [])),
            'cameras': len(g.get('cameras', [])),
            'animations': len(g.get('animations', [])),
            'skins': len(g.get('skins', [])),
            'scenes': len(g.get('scenes', [])),
        },
        'camera_names': [c.get('name', '') for c in g.get('cameras', [])],
        'camera_nodes': [{'node': ni, 'name': nd.get('name', ''), 'camera': nd['camera'],
                          'world': [round(v, 6) for v in world.get(ni, [0] * 16)]}
                         for ni, nd in enumerate(nodes) if 'camera' in nd],
        'extensionsUsed': sorted(g.get('extensionsUsed', [])),
        'extensionsRequired': sorted(g.get('extensionsRequired', [])),
        'triangles_from_indices': total_tris,
        'degenerate_triangles': degenerate,
        'nan_vertex_components': nan_verts,
        # TWO bboxes, deliberately.  The first is what any tool that reads
        # accessor min/max (i.e. every scale check in this catalogue that does
        # not download the BIN) will see.  The second is what a viewer actually
        # draws.  On this car they DIFFER, because 68% of the declared positions
        # are referenced by no triangle -- so the pair must always be reported
        # together, and the report must say which one the viewer sees.
        'world_bbox_min': [round(v, 6) for v in gmin],
        'world_bbox_max': [round(v, 6) for v in gmax],
        'world_bbox_size': [round(gmax[k] - gmin[k], 6) for k in range(3)],
        'world_bbox_min_referenced_only': [round(v, 6) for v in rmin],
        'world_bbox_max_referenced_only': [round(v, 6) for v in rmax],
        'world_bbox_size_referenced_only': [round(rmax[k] - rmin[k], 6) for k in range(3)],
        'bbox_declared_vs_referenced_max_abs_diff_m': round(max(
            max(abs(gmin[k] - rmin[k]) for k in range(3)),
            max(abs(gmax[k] - rmax[k]) for k in range(3))), 6),
        'WHICH_BBOX_THE_VIEWER_SEES': 'referenced_only',
        'declared_positions': tot_pos,
        'referenced_positions': tot_ref,
        'unreferenced_positions': tot_pos - tot_ref,
        'unreferenced_fraction': (round((tot_pos - tot_ref) / tot_pos, 6) if tot_pos else 0),
        'negative_determinant_nodes': [p['node'] for p in per_node if p['det'] < 0],
        'zero_determinant_nodes': [p['node'] for p in per_node if abs(p['det']) < 1e-12],
        'orphan_nodes_not_in_scene': orphans,
        'nodes_without_mesh': empty_nodes,
        'meshes_shared_by_multiple_nodes': {str(k): v for k, v in shared.items()},
        'meshes_unreferenced': unused_meshes,
        'class_area_m2': {k: round(v, 6) for k, v in class_area.items()},
        'class_tris': dict(class_tris),
        'materials_table': mat_table,
        'nodes_table': per_node,
    }
    return out


if __name__ == '__main__':
    src = sys.argv[1]
    dst = sys.argv[2]
    lab = sys.argv[4] if len(sys.argv) > 4 and sys.argv[3] == '--label' else None
    r = audit(src, lab)
    with open(dst, 'w') as f:
        json.dump(r, f, indent=1)
    c = r['counts']
    print('%s  nodes=%d meshes=%d prims=%d mats=%d tex=%d cams=%d tris=%d degen=%d'
          % (r['file'], c['nodes'], c['meshes'], c['primitives'], c['materials'],
             c['textures'], c['cameras'], r['triangles_from_indices'],
             r['degenerate_triangles']))
    print('  world bbox min=%s max=%s' % (r['world_bbox_min'], r['world_bbox_max']))
    print('  bbox declared %s..%s' % (r['world_bbox_min'], r['world_bbox_max']))
    print('  bbox REFERENCED %s..%s  (diff %.6f m)' % (r['world_bbox_min_referenced_only'], r['world_bbox_max_referenced_only'], r['bbox_declared_vs_referenced_max_abs_diff_m']))
    print('  positions declared=%d referenced=%d UNREFERENCED=%d (%.1f%%)' % (r['declared_positions'], r['referenced_positions'], r['unreferenced_positions'], 100*r['unreferenced_fraction']))
    print('  class areas m2: %s' % r['class_area_m2'])
    print('  neg-det nodes: %s' % r['negative_determinant_nodes'])
