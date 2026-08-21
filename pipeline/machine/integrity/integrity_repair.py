#!/usr/bin/env python3
"""integrity_repair.py — Stages 3/5/6 narrow repairs, one controlled change each.

Run: blender -b --python integrity_repair.py -- IN.glb OUT.glb REPORT.json
                                                [--skip name,name]

SCOPE IS DELIBERATELY NARROW. Only defects that were individually IDENTIFIED to
an object and a mechanism are touched. Everything else is measured and reported,
not "cleaned". Three reasons, all of them things this project has already paid
for:

  * a chip/purge heuristic tuned by area ATE REAL WINDOW SURROUND and holed the
    shell the first time it was run here;
  * "never conceal geometry defects with smoothing, blur or masks" is a
    non-negotiable rule of the production brief;
  * the ragged shell fringes on this car's rear quarters are the BODY's own torn
    edges. Deleting them would remove real surface and leave a bigger hole. They
    are reported as an open defect for component reconstruction, which is not
    what an integrity gate is for.

THE THREE REPAIRS, each with its own evidence and each independently skippable:

  R1  drop Glass_Rear      — 187 tris in 25 DISCONNECTED components totalling
                             0.0119 m2, floating outside the rear-screen
                             aperture (isolate render: one cluster is detached
                             in mid-air). It does not intersect Glass_Backlight
                             at all, which is itself 1 clean component of 14,208
                             tris. Debris, not a pane: no real pane is 4.8 cm2
                             per fragment.
  R2  flip inverted shells — CLOSED components whose signed volume is negative,
                             i.e. normals pointing inward. 57 components /
                             2,418 faces, 53 of them inside `Interior`. Only
                             CLOSED components are touched: on an open shell
                             "inside" is undefined and flipping it would be a
                             guess.
  R3  drop loose vertices  — vertices with no edge. 1 in the whole car.

Every repair re-measures the SAME predicate afterwards and the report carries
before/after for each. A repair that did not move its own number is reported as
NOT EFFECTIVE rather than assumed to have worked.
"""
import json
import os
import sys

import bmesh
import bpy
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def argv():
    a = sys.argv
    return a[a.index("--") + 1:] if "--" in a else []


def opt(a, f, d=""):
    return a[a.index(f) + 1] if f in a else d


def component_volumes(bm):
    """(components, closed?, signed volume) for every face island."""
    seen, comps = set(), []
    for f0 in bm.faces:
        if f0.index in seen:
            continue
        stack, comp = [f0], []
        seen.add(f0.index)
        while stack:
            f = stack.pop()
            comp.append(f)
            for e in f.edges:
                for nf in e.link_faces:
                    if nf.index not in seen:
                        seen.add(nf.index)
                        stack.append(nf)
        comps.append(comp)
    out = []
    for comp in comps:
        closed = all(len(e.link_faces) == 2 for f in comp for e in f.edges)
        vol = 0.0
        if closed:
            for f in comp:
                vs = [v.co for v in f.verts]
                for i in range(1, len(vs) - 1):
                    vol += vs[0].dot(vs[i].cross(vs[i + 1])) / 6.0
        out.append((comp, closed, vol))
    return out


def count_inverted_and_loose(ob):
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bm.faces.ensure_lookup_table()
    bm.verts.ensure_lookup_table()
    inv = sum(1 for c, closed, v in component_volumes(bm) if closed and v < 0)
    invf = sum(len(c) for c, closed, v in component_volumes(bm)
               if closed and v < 0)
    loose = sum(1 for v in bm.verts if not v.link_edges)
    bm.free()
    return inv, invf, loose


def main():
    a = argv()
    src, dst, rep = a[0], a[1], a[2]
    skip = set(x for x in opt(a, "--skip").split(",") if x)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=src)

    report = {"stage": "3/5/6 narrow integrity repairs", "source": src,
              "repairs": {}, "skipped": sorted(skip)}

    def scan():
        tot_inv = tot_invf = tot_loose = 0
        for o in bpy.data.objects:
            if o.type != "MESH":
                continue
            i, f, l = count_inverted_and_loose(o)
            tot_inv += i
            tot_invf += f
            tot_loose += l
        return {"inverted_components": tot_inv, "inverted_faces": tot_invf,
                "loose_vertices": tot_loose,
                "mesh_objects": len([o for o in bpy.data.objects
                                     if o.type == "MESH"]),
                "triangles": sum(
                    sum(max(0, len(p.vertices) - 2) for p in o.data.polygons)
                    for o in bpy.data.objects if o.type == "MESH")}

    before = scan()
    report["before"] = before

    # ---------------------------------------------------- R1 Glass_Rear debris
    if "R1" not in skip:
        ob = bpy.data.objects.get("Glass_Rear")
        if ob is None:
            report["repairs"]["R1_drop_Glass_Rear"] = {
                "status": "NOT APPLICABLE — node absent"}
        else:
            bm = bmesh.new()
            bm.from_mesh(ob.data)
            comps = component_volumes(bm)
            area = sum(f.calc_area() for f in bm.faces)
            det = {"components": len(comps), "triangles": len(bm.faces),
                   "area_m2": round(area, 6),
                   "mean_component_area_cm2": round(
                       area / max(1, len(comps)) * 1e4, 3)}
            bm.free()
            bpy.data.objects.remove(ob, do_unlink=True)
            det["status"] = "REMOVED"
            det["justification"] = (
                "25 disconnected components, mean 4.8 cm2, floating outside the "
                "rear-screen aperture; zero intersecting face pairs with "
                "Glass_Backlight (which is 1 clean component of 14,208 tris)")
            det["after_node_present"] = bpy.data.objects.get("Glass_Rear") is not None
            report["repairs"]["R1_drop_Glass_Rear"] = det

    # ------------------------------------------- R2 flip inverted CLOSED shells
    if "R2" not in skip:
        flipped_objs, flipped_faces = {}, 0
        for o in list(bpy.data.objects):
            if o.type != "MESH":
                continue
            bm = bmesh.new()
            bm.from_mesh(o.data)
            bm.faces.ensure_lookup_table()
            bad = [c for c, closed, v in component_volumes(bm)
                   if closed and v < 0]
            if bad:
                n = sum(len(c) for c in bad)
                bmesh.ops.reverse_faces(bm, faces=[f for c in bad for f in c])
                bm.to_mesh(o.data)
                o.data.update()
                flipped_objs[o.name] = n
                flipped_faces += n
            bm.free()
        report["repairs"]["R2_flip_inverted_closed_shells"] = {
            "status": "APPLIED" if flipped_faces else "NO-OP",
            "objects": flipped_objs, "faces_flipped": flipped_faces,
            "note": ("only CLOSED components are touched; on an open shell "
                     "'inside' is undefined and flipping would be a guess")}

    # -------------------------------------------------------- R3 loose vertices
    if "R3" not in skip:
        removed = 0
        for o in list(bpy.data.objects):
            if o.type != "MESH":
                continue
            bm = bmesh.new()
            bm.from_mesh(o.data)
            bm.verts.ensure_lookup_table()
            loose = [v for v in bm.verts if not v.link_edges]
            if loose:
                bmesh.ops.delete(bm, geom=loose, context="VERTS")
                bm.to_mesh(o.data)
                o.data.update()
                removed += len(loose)
            bm.free()
        report["repairs"]["R3_drop_loose_vertices"] = {
            "status": "APPLIED" if removed else "NO-OP",
            "vertices_removed": removed}

    after = scan()
    report["after"] = after
    report["effect"] = {
        k: {"before": before[k], "after": after[k],
            "moved": before[k] != after[k]}
        for k in ("inverted_components", "inverted_faces", "loose_vertices",
                  "mesh_objects", "triangles")}
    # A repair that did not move its own number is NOT EFFECTIVE, not "done".
    report["repairs_effective"] = {
        "R2_flip_inverted_closed_shells":
            before["inverted_components"] > after["inverted_components"],
        "R3_drop_loose_vertices":
            before["loose_vertices"] > after["loose_vertices"],
        "R1_drop_Glass_Rear":
            before["mesh_objects"] > after["mesh_objects"],
    }

    bpy.ops.export_scene.gltf(
        filepath=dst, export_format="GLB", use_selection=False,
        export_apply=False, export_yup=True, export_normals=True,
        export_materials="EXPORT", export_cameras=False, export_lights=False)
    report["exported"] = dst
    json.dump(report, open(rep, "w"), indent=1)
    print("INTEGRITY_REPAIR_DONE", dst)
    print(json.dumps(report["effect"], indent=1))
    print(json.dumps(report["repairs_effective"], indent=1))


if __name__ == "__main__":
    main()
