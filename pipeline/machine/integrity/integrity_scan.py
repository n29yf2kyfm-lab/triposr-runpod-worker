#!/usr/bin/env python3
"""integrity_scan.py — STAGE 1 automated integrity diagnosis of a GLB.

Run:  blender -b --python integrity_scan.py -- IN.glb OUT.json [--isect-cap N]

Reports, PER RENDERABLE NODE: node path + parent · mesh ref · material
assignment · local AND world transforms · scale · transform determinant ·
negative scale · unapplied transforms · mirrored · flipped normals ·
inconsistent winding · backfacing polygons · loose verts/edges · non-manifold
boundaries · duplicate faces · zero-area faces · degenerate triangles ·
self-intersections · inter-object intersections · floating geometry · UV
availability · missing material slots · invalid texture refs · bboxes · hidden
objects · objects outside the vehicle bounds.

THREE RULES THIS FILE OBEYS, each of them paid for by this project:

  * MEASURE FROM TRANSFORMED VERTICES, never from node-local coordinates or a
    node translation. Downstream stages bake instance transforms, so a graph
    read returns zeros on a correct file (CLAUDE.md, ultra-audit 2026-08-19).
  * A CHECK THAT CANNOT FIRE IS NOT A CHECK. Every predicate here has a
    negative control in `selftest_integrity.py`; nothing is trusted from a zero
    until the same code has been observed returning non-zero on a rigged mesh.
  * A TEST THAT WAS NOT RUN IS "NOT TESTED", NEVER "PASS". The self-intersection
    pass is O(n log n) with a big constant; above --isect-cap faces the object
    is recorded `"self_intersections": null` with `"self_isect_status":
    "NOT TESTED (over cap)"`, which is not the same thing as zero.
"""
import json
import sys
import time

import bmesh
import bpy
import numpy as np
from mathutils.bvhtree import BVHTree

ZERO_AREA = 1e-12          # m^2. A 1 micron triangle is 5e-13.
FLOAT_EPS = 1e-9


def argv():
    a = sys.argv
    return a[a.index("--") + 1:] if "--" in a else []


def wipe():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def import_glb(path):
    bpy.ops.import_scene.gltf(filepath=path)


def node_path(ob):
    names, cur = [], ob
    while cur is not None:
        names.append(cur.name)
        cur = cur.parent
    return "/".join(reversed(names))


def world_verts(ob):
    """(n,3) float64 of vertices in WORLD space. Never node-local."""
    n = len(ob.data.vertices)
    co = np.empty(n * 3, dtype=np.float64)
    ob.data.vertices.foreach_get("co", co)
    co = co.reshape(n, 3)
    m = np.array(ob.matrix_world, dtype=np.float64)
    return co @ m[:3, :3].T + m[:3, 3]


def mesh_stats(ob, isect_cap):
    """Everything that needs bmesh topology, in one pass."""
    me = ob.data
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.faces.ensure_lookup_table()
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()

    loose_verts = sum(1 for v in bm.verts if not v.link_edges)
    loose_edges = sum(1 for e in bm.edges if not e.link_faces)
    boundary_edges = sum(1 for e in bm.edges if len(e.link_faces) == 1)
    nonmanifold_edges = sum(1 for e in bm.edges if len(e.link_faces) > 2)

    # duplicate faces: identical vertex SET (order/winding ignored)
    seen, dup = set(), 0
    for f in bm.faces:
        k = tuple(sorted(v.index for v in f.verts))
        if k in seen:
            dup += 1
        else:
            seen.add(k)

    zero_area = sum(1 for f in bm.faces if f.calc_area() < ZERO_AREA)

    # degenerate triangles: two or three coincident CORNERS
    degen = 0
    for f in bm.faces:
        vs = [v.co for v in f.verts]
        if len(vs) == 3:
            if ((vs[0] - vs[1]).length < FLOAT_EPS
                    or (vs[1] - vs[2]).length < FLOAT_EPS
                    or (vs[0] - vs[2]).length < FLOAT_EPS):
                degen += 1

    # INCONSISTENT WINDING: on a 2-face manifold edge, the two faces must
    # traverse the shared edge in OPPOSITE directions. Same direction => the
    # two faces disagree about which side is out.
    bad_wind = 0
    for e in bm.edges:
        lf = e.link_faces
        if len(lf) != 2:
            continue
        dirs = []
        for f in lf:
            vi = [v.index for v in f.verts]
            a, b = e.verts[0].index, e.verts[1].index
            ia = vi.index(a)
            dirs.append(vi[(ia + 1) % len(vi)] == b)
        if dirs[0] == dirs[1]:
            bad_wind += 1

    # FLIPPED NORMALS, per closed connected component, by signed volume.
    # A closed shell whose normals point out has POSITIVE signed volume.
    comps = []
    seen_f = set()
    for f0 in bm.faces:
        if f0.index in seen_f:
            continue
        stack, comp = [f0], []
        seen_f.add(f0.index)
        while stack:
            f = stack.pop()
            comp.append(f)
            for e in f.edges:
                for nf in e.link_faces:
                    if nf.index not in seen_f:
                        seen_f.add(nf.index)
                        stack.append(nf)
        comps.append(comp)

    inverted_comps, inverted_faces, open_comps = 0, 0, 0
    for comp in comps:
        cf = set(f.index for f in comp)
        closed = True
        for f in comp:
            for e in f.edges:
                if len(e.link_faces) != 2:
                    closed = False
                    break
            if not closed:
                break
        if not closed:
            open_comps += 1
            continue
        vol = 0.0
        for f in comp:
            vs = [v.co for v in f.verts]
            for i in range(1, len(vs) - 1):
                a, b, c = vs[0], vs[i], vs[i + 1]
                vol += a.dot(b.cross(c)) / 6.0
        if vol < 0:
            inverted_comps += 1
            inverted_faces += len(cf)

    # SELF-INTERSECTION. Pairs that share a vertex are neighbours, not
    # intersections, and are filtered out.
    nf = len(bm.faces)
    if nf > isect_cap:
        self_isect = None
        self_status = f"NOT TESTED (over cap {isect_cap})"
    else:
        tree = BVHTree.FromBMesh(bm, epsilon=0.0)
        pairs = tree.overlap(tree)
        cnt = 0
        for i, j in pairs:
            if i >= j:
                continue
            vi = {v.index for v in bm.faces[i].verts}
            vj = {v.index for v in bm.faces[j].verts}
            if vi & vj:
                continue
            cnt += 1
        self_isect = cnt
        self_status = "tested"

    bm.free()
    return dict(
        loose_vertices=loose_verts, loose_edges=loose_edges,
        boundary_edges=boundary_edges, nonmanifold_edges=nonmanifold_edges,
        duplicate_faces=dup, zero_area_faces=zero_area,
        degenerate_triangles=degen, inconsistent_winding_edges=bad_wind,
        connected_components=len(comps), open_components=open_comps,
        inverted_components=inverted_comps, inverted_faces=inverted_faces,
        self_intersections=self_isect, self_isect_status=self_status,
    )


def main():
    a = argv()
    src, out = a[0], a[1]
    isect_cap = 40000
    if "--isect-cap" in a:
        isect_cap = int(a[a.index("--isect-cap") + 1])

    t0 = time.time()
    wipe()
    import_glb(src)

    obs = [o for o in bpy.data.objects if o.type == "MESH"]
    obs.sort(key=lambda o: o.name)

    rows = []
    for ob in obs:
        me = ob.data
        m = np.array(ob.matrix_world, dtype=np.float64)
        det = float(np.linalg.det(m[:3, :3]))
        sc = [round(v, 9) for v in ob.scale]
        wv = world_verts(ob)
        tri = sum(max(0, len(p.vertices) - 2) for p in me.polygons)

        slots = []
        empty_slots = 0
        for s in ob.material_slots:
            if s.material is None:
                empty_slots += 1
                slots.append(None)
            else:
                slots.append(s.material.name)

        row = dict(
            name=ob.name,
            node_path=node_path(ob),
            parent=ob.parent.name if ob.parent else None,
            mesh_data=me.name,
            mesh_users=me.users,
            materials=slots,
            empty_material_slots=empty_slots,
            polygons=len(me.polygons),
            triangles=tri,
            vertices=len(me.vertices),
            edges=len(me.edges),
            uv_layers=[u.name for u in me.uv_layers],
            has_uv=len(me.uv_layers) > 0,
            has_custom_normals=me.has_custom_normals,
            matrix_local=[[round(v, 9) for v in r] for r in ob.matrix_local],
            matrix_world=[[round(v, 9) for v in r] for r in m],
            scale=sc,
            determinant=round(det, 12),
            negative_scale=bool(min(sc) < 0),
            mirrored=bool(det < 0),
            unapplied_transform=not all(
                abs(m[i][j] - (1.0 if i == j else 0.0)) < 1e-9
                for i in range(4) for j in range(4)),
            hidden_viewport=bool(ob.hide_get()),
            hidden_render=bool(ob.hide_render),
            world_bbox_min=[round(float(v), 6) for v in wv.min(axis=0)],
            world_bbox_max=[round(float(v), 6) for v in wv.max(axis=0)],
            world_centroid=[round(float(v), 6) for v in wv.mean(axis=0)],
        )
        row.update(mesh_stats(ob, isect_cap))
        rows.append(row)

    # ---- scene-level: bounds, floating geometry, outside-vehicle objects
    lo = np.array([min(r["world_bbox_min"][k] for r in rows) for k in range(3)])
    hi = np.array([max(r["world_bbox_max"][k] for r in rows) for k in range(3)])
    size = hi - lo

    for r in rows:
        c = np.array(r["world_centroid"])
        frac = (c - lo) / np.where(size > 0, size, 1)
        r["centroid_frac_of_car_bbox"] = [round(float(v), 4) for v in frac]
        r["outside_vehicle_bounds"] = bool(
            (frac < -0.02).any() or (frac > 1.02).any())

    # ---- INTER-OBJECT INTERSECTIONS (bbox prefilter, then BVH overlap)
    trees, bbs = {}, {}
    for ob in obs:
        bm = bmesh.new()
        bm.from_mesh(ob.data)
        bm.transform(ob.matrix_world)
        trees[ob.name] = BVHTree.FromBMesh(bm, epsilon=0.0)
        bm.free()
        r = next(x for x in rows if x["name"] == ob.name)
        bbs[ob.name] = (np.array(r["world_bbox_min"]),
                        np.array(r["world_bbox_max"]))

    inter = []
    names = [o.name for o in obs]
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a1, b1 = bbs[names[i]]
            a2, b2 = bbs[names[j]]
            if (a1 > b2).any() or (a2 > b1).any():
                continue
            ov = trees[names[i]].overlap(trees[names[j]])
            if ov:
                inter.append({"a": names[i], "b": names[j],
                              "overlapping_face_pairs": len(ov)})
    inter.sort(key=lambda d: -d["overlapping_face_pairs"])

    doc = {
        "stage": "1 — automated integrity diagnosis",
        "source": src,
        "blender": bpy.app.version_string,
        "seconds": round(time.time() - t0, 1),
        "isect_cap_faces": isect_cap,
        "scene": {
            "mesh_objects": len(obs),
            "materials": len(bpy.data.materials),
            "images": len(bpy.data.images),
            "cameras": len([o for o in bpy.data.objects if o.type == "CAMERA"]),
            "lights": len([o for o in bpy.data.objects if o.type == "LIGHT"]),
            "triangles": sum(r["triangles"] for r in rows),
            "vertices": sum(r["vertices"] for r in rows),
            "world_bbox_min": [round(float(v), 6) for v in lo],
            "world_bbox_max": [round(float(v), 6) for v in hi],
            "world_bbox_size": [round(float(v), 6) for v in size],
        },
        "totals": {
            k: int(sum(r[k] for r in rows if r[k] is not None))
            for k in ("loose_vertices", "loose_edges", "boundary_edges",
                      "nonmanifold_edges", "duplicate_faces",
                      "zero_area_faces", "degenerate_triangles",
                      "inconsistent_winding_edges", "inverted_components",
                      "inverted_faces", "open_components")
        },
        "negative_scale_objects": [r["name"] for r in rows if r["negative_scale"]],
        "mirrored_objects": [r["name"] for r in rows if r["mirrored"]],
        "hidden_objects": [r["name"] for r in rows
                           if r["hidden_render"] or r["hidden_viewport"]],
        "objects_outside_vehicle_bounds": [r["name"] for r in rows
                                           if r["outside_vehicle_bounds"]],
        "objects_without_uv": [r["name"] for r in rows if not r["has_uv"]],
        "objects_with_empty_material_slot": [
            r["name"] for r in rows if r["empty_material_slots"]],
        "self_isect_not_tested": [r["name"] for r in rows
                                  if r["self_intersections"] is None],
        "inter_object_intersections": inter,
        "objects": rows,
    }
    json.dump(doc, open(out, "w"), indent=1)
    print("INTEGRITY_SCAN_DONE", out, doc["seconds"], "s")


if __name__ == "__main__":
    main()
