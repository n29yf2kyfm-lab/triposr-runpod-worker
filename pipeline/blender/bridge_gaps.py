"""bridge_gaps.py — fill panel gaps WITHOUT touching the visible skin.
v20's edge-pulling dented the door panels (visible warp in glancing light).
This does it right: the outer surface is never moved. Instead, every gap
gets a recessed body-coloured floor — bridge faces between the two gap
edges, inset a few mm along the surface normal — so the shut-line reads
as a tight factory groove instead of a black slot. Plus the non-manifold
solidify for any unpaired stretches.

blender -b -noaudio --python /tmp/bridge_gaps.py -- --in <glb> --out <glb>
  [--maxgap 0.032] [--depth 0.005]
"""
import bpy, bmesh, sys
from mathutils.kdtree import KDTree

argv = sys.argv[sys.argv.index("--") + 1:]
IN = argv[argv.index("--in") + 1]; OUT = argv[argv.index("--out") + 1]
MAXG = float(argv[argv.index("--maxgap") + 1]) if "--maxgap" in argv else 0.032
DEPTH = float(argv[argv.index("--depth") + 1]) if "--depth" in argv else 0.005
T = 0.007

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=IN)

for o in bpy.context.scene.objects:
    if o.type != "MESH":
        continue
    if not any((m and m.name in ("Paint_Color", "Car_Paint")) for m in o.data.materials):
        continue
    pi = next(i for i, m in enumerate(o.data.materials)
              if m and m.name in ("Paint_Color", "Car_Paint"))
    seam = bpy.data.materials.new("seam_dark")
    seam.use_nodes = True
    sb = seam.node_tree.nodes["Principled BSDF"]
    sb.inputs["Base Color"].default_value = (0.015, 0.016, 0.018, 1)
    sb.inputs["Metallic"].default_value = 0.0
    sb.inputs["Roughness"].default_value = 0.95
    o.data.materials.append(seam)
    si = len(o.data.materials) - 1
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

    # --- de-ripple: smooth every boundary polyline along itself so bent
    # door-edge lips (source-mesh damage) straighten out. Displacement is
    # capped so clean edges and arch lips barely move.
    badj0 = {v.index: [e.other_vert(v).index for e in v.link_edges
                       if len(e.link_faces) == 1] for v in bverts}
    orig = {v.index: v.co.copy() for v in bverts}
    for _ in range(20):
        newpos = {}
        for v in bverts:
            ns = badj0.get(v.index, [])
            if len(ns) != 2:
                continue
            mid = (bm.verts[ns[0]].co + bm.verts[ns[1]].co) / 2
            newpos[v.index] = v.co + (mid - v.co) * 0.4
        for vi, p in newpos.items():
            bm.verts[vi].co = p
    CAP = 0.008
    moved = 0
    for v in bverts:
        d = v.co - orig[v.index]
        if d.length > CAP:
            v.co = orig[v.index] + d.normalized() * CAP
        if d.length > 0.0015:
            moved += 1
            # carry half the correction into the 1-ring so the lip follows
            for e in v.link_edges:
                n = e.other_vert(v)
                if n.index not in badj0:      # interior neighbour only
                    n.co += (v.co - orig[v.index]) * 0.28
    print(f"DERIPPLED {moved} boundary verts (cap {CAP*1000:.0f}mm)")

    kd = KDTree(len(bverts))
    for i, v in enumerate(bverts):
        kd.insert(v.co, i)
    kd.balance()

    # boundary adjacency + BFS hop distance (capped) so a single loop that
    # wraps both sides of a shut-line can still pair across the gap
    badj = {v.index: [e.other_vert(v).index for e in v.link_edges
                      if len(e.link_faces) == 1] for v in bverts}
    HOPS = 30
    def hop_far(a, b):
        seen = {a}; frontier = [a]
        for _ in range(HOPS):
            nxt = []
            for x in frontier:
                for n in badj.get(x, []):
                    if n == b:
                        return False
                    if n not in seen:
                        seen.add(n); nxt.append(n)
            frontier = nxt
        return True

    # partner for each boundary vert: nearest vert across the gap — another
    # loop, or the same loop if topologically distant along the boundary
    partner = {}
    for v in bverts:
        best = None
        for co, i, d in kd.find_range(v.co, MAXG):
            u = bverts[i]
            if loop_id[u.index] == loop_id[v.index] and not hop_far(v.index, u.index):
                continue
            if v.normal.dot(u.normal) < 0.45:
                continue
            dirv = u.co - v.co
            if dirv.length < 1e-9:
                continue
            if abs(dirv.normalized().dot(v.normal)) > 0.45:
                continue
            if best is None or d < best[1]:
                best = (u, d)
        if best:
            partner[v.index] = best[0]

    # recessed copies of every vert that participates
    sunk = {}
    def sink(v):
        if v.index not in sunk:
            nv = bm.verts.new(v.co - v.normal * DEPTH)
            sunk[v.index] = nv
        return sunk[v.index]

    made = 0
    boundary_edges = [e for e in bm.edges if len(e.link_faces) == 1]
    for e in boundary_edges:
        v1, v2 = e.verts
        u1 = partner.get(v1.index); u2 = partner.get(v2.index)
        if not (u1 and u2):
            continue
        if loop_id[v1.index] > loop_id[u1.index]:
            continue          # build each gap floor once
        if u1 == u2:
            continue
        quad = [sink(v1), sink(v2), sink(u2), sink(u1)]
        if len(set(quad)) < 4:
            continue
        try:
            f = bm.faces.new(quad)
            f.material_index = si
            f.smooth = True
            made += 1
        except ValueError:
            pass              # duplicate face, skip
    bm.normal_update()
    bm.to_mesh(o.data); bm.free()
    print(f"BRIDGED {o.name}: {made} floor quads, skin untouched")

    s = o.modifiers.new("GapFill", "SOLIDIFY")
    s.solidify_mode = "NON_MANIFOLD"
    s.nonmanifold_thickness_mode = "FIXED"
    s.thickness = T
    s.offset = -1.0

bpy.ops.object.select_all(action="SELECT")
bpy.ops.export_scene.gltf(filepath=OUT, export_format="GLB", use_selection=False,
    export_apply=True, export_yup=True, export_normals=True, export_materials="EXPORT")
print(f"BRIDGE_OK {OUT} maxgap={MAXG} depth={DEPTH}")
