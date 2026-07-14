"""narrow_gaps2.py — v2: iterative gap narrowing + edge-smoothed pulls.
Pass schedule widens the pairing radius so wide shut-lines (up to ~30mm)
get pulled too; a perpendicularity guard stops unrelated edges (door top vs
roof rail) from pairing; per-loop smoothing of the displacement kills the
wavy-highlight artifact of v1. Then non-manifold Solidify walls the rest.

blender -b -noaudio --python /tmp/narrow_gaps2.py -- --in <glb> --out <glb>
"""
import bpy, bmesh, sys
from mathutils.kdtree import KDTree

argv = sys.argv[sys.argv.index("--") + 1:]
IN = argv[argv.index("--in") + 1]; OUT = argv[argv.index("--out") + 1]
PASSES = [0.012, 0.022, 0.030]
PULL = 0.35
T = 0.007

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=IN)

for o in bpy.context.scene.objects:
    if o.type != "MESH":
        continue
    if not any((m and m.name in ("Paint_Color", "Car_Paint")) for m in o.data.materials):
        continue
    bm = bmesh.new(); bm.from_mesh(o.data)
    bm.verts.ensure_lookup_table()

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
    # boundary adjacency for smoothing
    bneigh = {v.index: [e.other_vert(v).index for e in v.link_edges
                        if len(e.link_faces) == 1] for v in bverts}
    total = 0
    for maxg in PASSES:
        kd = KDTree(len(bverts))
        for i, v in enumerate(bverts):
            kd.insert(v.co, i)
        kd.balance()
        moves = {}
        for v in bverts:
            best = None
            for co, i, d in kd.find_range(v.co, maxg):
                u = bverts[i]
                if loop_id[u.index] == loop_id[v.index]:
                    continue
                if v.normal.dot(u.normal) < 0.5:
                    continue
                dirv = (u.co - v.co)
                if dirv.length < 1e-9:
                    continue
                dirn = dirv.normalized()
                # gap opening must lie in the surface plane, not along it
                if abs(dirn.dot(v.normal)) > 0.45:
                    continue
                if best is None or d < best[1]:
                    best = (u, d)
            if best:
                moves[v.index] = (best[0].co - v.co) * PULL
        # smooth displacement along each boundary loop (2 iterations)
        for _ in range(2):
            sm = {}
            for vi, d in moves.items():
                ns = [moves[n] for n in bneigh.get(vi, []) if n in moves]
                sm[vi] = (d + sum(ns, d * 0)) / (1 + len(ns)) if ns else d
            moves = sm
        soft = {}
        for vi, d in moves.items():
            for n in bneigh.get(vi, []):
                pass
        for vi, d in moves.items():
            v = bm.verts[vi]
            for e in v.link_edges:
                n = e.other_vert(v)
                if n.index not in moves and n.index not in soft:
                    soft[n.index] = d * 0.4
        for vi, d in {**soft, **moves}.items():
            bm.verts[vi].co += d
        total += len(moves)
    bm.to_mesh(o.data); bm.free()
    print(f"NARROW2 {o.name}: {total} pulls over {len(PASSES)} passes")

    s = o.modifiers.new("GapFill", "SOLIDIFY")
    s.solidify_mode = "NON_MANIFOLD"
    s.nonmanifold_thickness_mode = "FIXED"
    s.thickness = T
    s.offset = -1.0

bpy.ops.object.select_all(action="SELECT")
bpy.ops.export_scene.gltf(filepath=OUT, export_format="GLB", use_selection=False,
    export_apply=True, export_yup=True, export_normals=True, export_materials="EXPORT")
print(f"NARROW2_OK {OUT}")
