#!/usr/bin/env python3
"""
Per-object winding / normal-orientation probe, from the file, name-free.

The face-orientation render showed backfacing (red) geometry concentrated on
one side of the car.  A render localises a defect but does not name the mesh,
so this measures it directly, two independent ways:

  A. SIGNED VOLUME.  sum over triangles of v0 . (v1 x v2) / 6.  For a closed
     surface with outward-facing winding this is POSITIVE and equals the
     enclosed volume; with inverted winding it is NEGATIVE of the same
     magnitude.  Sign is the verdict, magnitude is the sanity check.
  B. OUTWARD AGREEMENT.  fraction of triangles whose geometric normal points
     away from the object's own centroid.  This works on OPEN shells, where
     signed volume is meaningless, and it is what a viewer's backface test
     effectively sees.

Both are reported because neither is sufficient alone: a shell (a wheel arch
liner, a window pane) is open, and a closed part that is genuinely concave in
places will not reach 100% outward agreement.

Usage: python3 normals_probe.py <file.glb> <out.json>
"""
import sys, json, math
sys.path.insert(0, __file__.rsplit('/', 1)[0])
from glb_audit import load_glb, read_accessor, trs_matrix, mat_mul, xform

SRC, DST = sys.argv[1], sys.argv[2]
g, bins, _, _ = load_glb(SRC)
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
for ni, nd in enumerate(nodes):
    if 'mesh' not in nd:
        continue
    m = world[ni]
    vol = 0.0
    out_ok = 0
    out_n = 0
    area_out = 0.0
    area_in = 0.0
    cx = cy = cz = 0.0
    npts = 0
    tris = []
    for p in meshes[nd['mesh']]['primitives']:
        if p.get('mode', 4) != 4:
            continue
        pos = read_accessor(g, bins, p['attributes']['POSITION'])
        wp = [xform(m, v) for v in pos]
        idx = (read_accessor(g, bins, p['indices']) if 'indices' in p
               else [(i,) for i in range(len(pos))])
        for t in range(0, len(idx) - 2, 3):
            a, b, c = idx[t][0], idx[t + 1][0], idx[t + 2][0]
            if a == b or b == c or a == c:
                continue
            A, B, C = wp[a], wp[b], wp[c]
            tris.append((A, B, C))
            cx += A[0] + B[0] + C[0]
            cy += A[1] + B[1] + C[1]
            cz += A[2] + B[2] + C[2]
            npts += 3
    if not tris:
        continue
    cx, cy, cz = cx / npts, cy / npts, cz / npts
    for A, B, C in tris:
        vol += (A[0] * (B[1] * C[2] - B[2] * C[1])
                - A[1] * (B[0] * C[2] - B[2] * C[0])
                + A[2] * (B[0] * C[1] - B[1] * C[0])) / 6.0
        ux, uy, uz = B[0] - A[0], B[1] - A[1], B[2] - A[2]
        vx, vy, vz = C[0] - A[0], C[1] - A[1], C[2] - A[2]
        nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
        ar = 0.5 * math.sqrt(nx * nx + ny * ny + nz * nz)
        mx_ = (A[0] + B[0] + C[0]) / 3 - cx
        my_ = (A[1] + B[1] + C[1]) / 3 - cy
        mz_ = (A[2] + B[2] + C[2]) / 3 - cz
        d = nx * mx_ + ny * my_ + nz * mz_
        out_n += 1
        if d > 0:
            out_ok += 1
            area_out += ar
        else:
            area_in += ar
    rows.append({
        'node': ni, 'name': nd.get('name', ''), 'triangles': len(tris),
        'signed_volume_m3': round(vol, 9),
        'winding_by_volume': ('outward' if vol > 0 else 'INVERTED'),
        'outward_face_fraction': round(out_ok / out_n, 5),
        'outward_area_fraction': round(area_out / (area_out + area_in), 5)
        if (area_out + area_in) else None,
        'inward_area_m2': round(area_in, 6),
    })

inv = [r for r in rows if r['signed_volume_m3'] < 0]
low = [r for r in rows if r['outward_area_fraction'] is not None
       and r['outward_area_fraction'] < 0.5]
out = {
    'file': SRC.rsplit('/', 1)[-1],
    'objects': len(rows),
    'objects_with_negative_signed_volume': [r['name'] for r in inv],
    'n_negative_signed_volume': len(inv),
    'objects_with_majority_inward_area': [r['name'] for r in low],
    'total_inward_facing_area_m2': round(sum(r['inward_area_m2'] for r in rows), 6),
    'total_area_m2': round(sum(r['inward_area_m2'] for r in rows)
                           + sum((r['outward_area_fraction'] or 0) /
                                 max(1e-9, (1 - (r['outward_area_fraction'] or 0)))
                                 * r['inward_area_m2'] for r in rows), 6),
    'rows': sorted(rows, key=lambda r: r['outward_area_fraction'] or 1),
}
json.dump(out, open(DST, 'w'), indent=1)
print('objects=%d  negative signed volume=%d  majority-inward=%d'
      % (len(rows), len(inv), len(low)))
print('%-28s %10s %8s %8s %10s' % ('object', 'signedVol', 'outFrac', 'outArea', 'inwardM2'))
for r in out['rows'][:22]:
    print('%-28s %10.5f %8.4f %8.4f %10.5f'
          % (r['name'][:28], r['signed_volume_m3'], r['outward_face_fraction'],
             r['outward_area_fraction'], r['inward_area_m2']))
