"""narrow_gaps.py — reduce panel shut-line WIDTH without welding.
For every boundary vertex of the paint skin, find the nearest boundary vertex
on a DIFFERENT boundary loop within --maxgap; slide both toward each other by
--pull (fraction of the distance). No merging, topology untouched — this is
what the failed 6mm weld should have been. Then a non-manifold Solidify walls
whatever gap remains.

blender -b -noaudio --python /tmp/narrow_gaps.py -- \
  --in <glb> --out <glb> [--pull 0.35] [--maxgap 0.012] [--t 0.007]
"""
import bpy, bmesh, sys
from mathutils.kdtree import KDTree

argv = sys.argv[sys.argv.index("--") + 1:]
IN = argv[argv.index("--in") + 1]; OUT = argv[argv.index("--out") + 1]
PULL = float(argv[argv.index("--pull") + 1]) if "--pull" in argv else 0.35
MAXG = float(argv[argv.index("--maxgap") + 1]) if "--maxgap" in argv else 0.012
T = float(argv[argv.index("--t") + 1]) if "--t" in argv else 0.007

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=IN)

for o in bpy.context.scene.objects:
    if o.type != "MESH":
        continue
    if not any((m and m.name in ("Paint_Color", "Car_Paint")) for m in o.data.materials):
        continue
    bm = bmesh.new(); bm.from_mesh(o.data)
    bm.verts.ensure_lookup_table(); bm.edges.ensure_lookup_table()

    # boundary verts + loop labelling by flood fill over boundary edges
    bverts = [v for v in bm.verts if any(len(e.link_faces) == 1 for e in v.link_edges)]
    loop_id = {}
    cur = 0
    for v in bverts:
        if v.index in loop_id:
            continue
        stack = [v]
        while stack:
            w = stack.pop()
            if w.index in loop_id:
                continue
            loop_id[w.index] = cur
            for e in w.link_edges:
                if len(e.link_faces) == 1:
                    n = e.other_vert(w)
                    if n.index not in loop_id:
                        stack.append(n)
        cur += 1

    kd = KDTree(len(bverts))
    for i, v in enumerate(bverts):
        kd.insert(v.co, i)
    kd.balance()

    moves = {}
    for v in bverts:
        best = None
        for co, i, d in kd.find_range(v.co, MAXG):
            u = bverts[i]
            if loop_id[u.index] == loop_id[v.index]:
                continue
            # only pull edges that face the same way (gap sides), not
            # unrelated rims (arch lip vs sill)
            if v.normal.dot(u.normal) < 0.5:
                continue
            if best is None or d < best[1]:
                best = (u, d)
        if best:
            moves[v.index] = (best[0].co - v.co) * PULL
    softened = {}
    for vi, d in moves.items():
        v = bm.verts[vi]
        for e in v.link_edges:
            n = e.other_vert(v)
            if n.index not in moves and n.index not in softened:
                softened[n.index] = d * 0.4
    for vi, d in {**softened, **moves}.items():
        bm.verts[vi].co += d
    bm.to_mesh(o.data); bm.free()
    print(f"NARROWED {o.name}: {len(moves)} edge verts pulled, {len(softened)} softened")

    s = o.modifiers.new("GapFill", "SOLIDIFY")
    s.solidify_mode = "NON_MANIFOLD"
    s.nonmanifold_thickness_mode = "FIXED"
    s.thickness = T
    s.offset = -1.0

bpy.ops.object.select_all(action="SELECT")
bpy.ops.export_scene.gltf(filepath=OUT, export_format="GLB", use_selection=False,
    export_apply=True, export_yup=True, export_normals=True, export_materials="EXPORT")
print(f"NARROW_OK {OUT} pull={PULL} maxgap={MAXG}")
