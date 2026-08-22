#!/usr/bin/env python3
"""gap_survey.py — are the shell fragments COINCIDENT-BUT-UNWELDED, or genuinely
separated?

This decides whether the body is repairable at all. The shell carries 203,703
boundary edges across 14,643 open components, and that has one of two very
different causes:

  * the fragments' edges sit on top of each other and were simply never welded
    -- in which case one weld at the right distance turns it into a connected
    surface and the paint, the A-pillar crease and the front end all become
    ordinary surface problems;
  * or there is real empty space between them, in which case welding does
    nothing and the shell has to be re-meshed or re-sourced.

Method: take every boundary vertex, find its nearest boundary vertex belonging to
a DIFFERENT component, and report the distribution of those distances. The answer
is the shape of that histogram, not an average -- a bimodal result (many at
~0 mm, some far) means most of it welds and a minority needs filling.

Run: blender -b --python gap_survey.py -- in.glb [object]
"""
import json
import sys
from collections import defaultdict

import bmesh
import bpy
import numpy as np

argv = sys.argv[sys.argv.index("--") + 1:]
SRC = argv[0]
OBJ = argv[1] if len(argv) > 1 else "carpaint"

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=SRC)
o = next((x for x in bpy.context.scene.objects if x.name == OBJ), None)
if o is None:
    raise SystemExit(f"GAP_FAIL: no object {OBJ}")

bm = bmesh.new()
bm.from_mesh(o.data)
bm.transform(o.matrix_world)
bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
bm.verts.ensure_lookup_table()
bm.faces.ensure_lookup_table()

# component id per face, then per boundary vertex
comp = {}
cid = 0
for f in bm.faces:
    if f.index in comp:
        continue
    st = [f]
    comp[f.index] = cid
    while st:
        c = st.pop()
        for e in c.edges:
            for nf in e.link_faces:
                if nf.index not in comp:
                    comp[nf.index] = cid
                    st.append(nf)
    cid += 1

bverts = defaultdict(set)
for e in bm.edges:
    if len(e.link_faces) == 1:
        c = comp[e.link_faces[0].index]
        for v in e.verts:
            bverts[v.index].add(c)

idx = sorted(bverts)
P = np.array([bm.verts[i].co[:] for i in idx], dtype=float)
C = np.array([min(bverts[i]) for i in idx])
print(f"GAP_INPUT {OBJ}: {cid:,} components, {len(idx):,} boundary vertices")

# nearest boundary vertex in a DIFFERENT component, via a uniform grid
CELL = 0.01
keys = np.floor(P / CELL).astype(int)
grid = defaultdict(list)
for i, k in enumerate(map(tuple, keys)):
    grid[k].append(i)
best = np.full(len(P), np.inf)
for i in range(len(P)):
    ki = keys[i]
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for dz in (-1, 0, 1):
                for j in grid.get((ki[0] + dx, ki[1] + dy, ki[2] + dz), ()):
                    if C[j] == C[i]:
                        continue
                    d = np.linalg.norm(P[i] - P[j])
                    if d < best[i]:
                        best[i] = d
found = best[np.isfinite(best)] * 1000.0
print(f"GAP_FOUND {len(found):,} of {len(P):,} boundary verts have a "
      f"different-component neighbour within {CELL*1000:.0f} mm")
if len(found):
    for t in (0.01, 0.1, 0.5, 1, 2, 5, 10):
        print(f"   within {t:>5.2f} mm : {(found <= t).sum():>8,}  ({100*(found<=t).mean():.2f}%)")
    print(f"   median {np.median(found):.4f} mm   mean {found.mean():.4f} mm")
print("GAP_DONE")
