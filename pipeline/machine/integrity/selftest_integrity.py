#!/usr/bin/env python3
"""selftest_integrity.py — NEGATIVE CONTROLS for every predicate in
integrity_scan.mesh_stats.

Run:  blender -b --python selftest_integrity.py -- OUT.json

WHY THIS FILE EXISTS. This project has now found NINE checks that could never
fire — a "no arch intersection" gate that asked for points simultaneously
inside and outside a cylinder, a WRONG_CLASS regex ending in a literal
backslash-b, `run_controls()` that argparse had no flag for, a PSNR gate that
passed eleven blank frames, and a control that gutted glazing by copying
triangle 0 (full area) under the comment "degenerate: zero area". The lesson is
blunt and now costed: **a check that has never been observed to FAIL has not
been tested, however carefully it was written.**

So each control below RIGS a known defect into a clean mesh and asserts the
scanner's count RISES by the rigged amount. A control must also be checked in
the other direction: the CLEAN cube must score zero on the same predicate, or
the control proves only that the number is noisy.

Every control also prints what it did, so a control that fires FOR THE WRONG
REASON (the `tri[~keep] = tri[0]` class) is visible in the log rather than
inferred from a pass.
"""
import json
import os
import sys

import bmesh
import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import integrity_scan as S  # noqa: E402


def argv():
    a = sys.argv
    return a[a.index("--") + 1:] if "--" in a else []


def fresh(name="ctl"):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(ob)
    return ob


def stat(ob, key, cap=10 ** 9):
    return S.mesh_stats(ob, cap)[key]


def edit(ob, fn):
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    fn(bm)
    bm.to_mesh(ob.data)
    bm.free()


RESULTS = []


def control(name, key, rig, expect_min, cap=10 ** 9):
    ob = fresh()
    base = stat(ob, key, cap)
    note = rig(ob)
    after = stat(ob, key, cap)
    delta = (after or 0) - (base or 0)
    ok = (base == 0) and (delta >= expect_min)
    RESULTS.append({"control": name, "predicate": key, "rig": note,
                    "clean": base, "rigged": after, "delta": delta,
                    "expect_delta_at_least": expect_min,
                    "clean_is_zero": base == 0, "fired": delta >= expect_min,
                    "PASS": ok})
    print(f"{'PASS' if ok else 'FAIL':4} {name:28} {key:28} "
          f"clean={base} rigged={after} delta={delta} ({note})")
    return ok


# --------------------------------------------------------------- the controls
def r_loose_vert(ob):
    edit(ob, lambda bm: bm.verts.new((5.0, 5.0, 5.0)))
    return "added 1 vertex with no edges"


def r_loose_edge(ob):
    def f(bm):
        a = bm.verts.new((5.0, 5.0, 5.0))
        b = bm.verts.new((6.0, 5.0, 5.0))
        bm.edges.new((a, b))
    edit(ob, f)
    return "added 1 edge with no faces"


def r_boundary(ob):
    def f(bm):
        bm.faces.ensure_lookup_table()
        bmesh.ops.delete(bm, geom=[bm.faces[0]], context="FACES_ONLY")
    edit(ob, f)
    return "deleted 1 face -> 3 boundary edges"


def r_nonmanifold(ob):
    def f(bm):
        bm.verts.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        v = bm.faces[0].verts[:3]
        bm.faces.new(v)          # third face on an existing edge pair
    edit(ob, f)
    return "duplicated a face -> edges with 3 link_faces"


def r_dupface(ob):
    def f(bm):
        bm.faces.ensure_lookup_table()
        vs = list(bm.faces[0].verts)
        bm.faces.new(list(reversed(vs)))   # same vertex SET, opposite winding
    edit(ob, f)
    return "added a face on the same 3 verts, reversed winding"


def r_zero_area(ob):
    def f(bm):
        a = bm.verts.new((5.0, 5.0, 5.0))
        b = bm.verts.new((5.0 + 1e-9, 5.0, 5.0))
        c = bm.verts.new((5.0 + 2e-9, 5.0, 5.0))
        bm.faces.new((a, b, c))       # collinear AND sub-micron: real zero area
    edit(ob, f)
    return "added a collinear sub-nm triangle (true zero area, NOT a copy of face 0)"


def r_degenerate(ob):
    def f(bm):
        a = bm.verts.new((7.0, 7.0, 7.0))
        b = bm.verts.new((7.0, 7.0, 7.0 + 1e-12))   # coincident corner
        c = bm.verts.new((8.0, 7.0, 7.0))
        bm.faces.new((a, b, c))
    edit(ob, f)
    return "added a triangle with two coincident corners"


def r_winding(ob):
    def f(bm):
        bm.faces.ensure_lookup_table()
        bm.faces[0].normal_flip()
    edit(ob, f)
    return "flipped ONE face -> its 3 edges disagree with their neighbours"


def r_inverted(ob):
    def f(bm):
        bmesh.ops.reverse_faces(bm, faces=bm.faces[:])
    edit(ob, f)
    return "reversed ALL faces -> closed shell with negative signed volume"


def r_selfisect(ob):
    def f(bm):
        # a blade straight through the cube, sharing no vertex with it
        a = bm.verts.new((-2.0, 0.0, 0.0))
        b = bm.verts.new((2.0, 0.0, 0.0))
        c = bm.verts.new((0.0, 0.0, 2.0))
        bm.faces.new((a, b, c))
    edit(ob, f)
    return "added a triangle piercing the cube, sharing no vertex"


def main():
    out = argv()[0]
    ok = True
    ok &= control("loose_vertex", "loose_vertices", r_loose_vert, 1)
    ok &= control("loose_edge", "loose_edges", r_loose_edge, 1)
    ok &= control("open_boundary", "boundary_edges", r_boundary, 3)
    ok &= control("nonmanifold_edge", "nonmanifold_edges", r_nonmanifold, 1)
    ok &= control("duplicate_face", "duplicate_faces", r_dupface, 1)
    ok &= control("zero_area_face", "zero_area_faces", r_zero_area, 1)
    ok &= control("degenerate_tri", "degenerate_triangles", r_degenerate, 1)
    ok &= control("inconsistent_winding", "inconsistent_winding_edges",
                  r_winding, 3)
    ok &= control("inverted_shell", "inverted_components", r_inverted, 1)
    ok &= control("self_intersection", "self_intersections", r_selfisect, 1)

    # And the OTHER direction: a clean cube must be clean on everything.
    ob = fresh()
    clean = S.mesh_stats(ob, 10 ** 9)
    must_be_zero = ["loose_vertices", "loose_edges", "boundary_edges",
                    "nonmanifold_edges", "duplicate_faces", "zero_area_faces",
                    "degenerate_triangles", "inconsistent_winding_edges",
                    "inverted_components", "self_intersections"]
    clean_ok = all(clean[k] == 0 for k in must_be_zero)
    print(f"{'PASS' if clean_ok else 'FAIL':4} clean_cube_scores_zero "
          f"{ {k: clean[k] for k in must_be_zero} }")
    ok &= clean_ok

    doc = {"controls": RESULTS,
           "clean_cube": {k: clean[k] for k in must_be_zero},
           "clean_cube_all_zero": clean_ok,
           "ALL_CONTROLS_PASS": bool(ok)}
    json.dump(doc, open(out, "w"), indent=1)
    print("SELFTEST_DONE", "ALL_PASS" if ok else "FAILURES_PRESENT")


if __name__ == "__main__":
    main()
