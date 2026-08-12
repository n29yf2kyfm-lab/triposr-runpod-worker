#!/usr/bin/env python3
"""assign_materials.py — STAGE 4b: make a generated car SHIPPABLE.

Why this stage exists
---------------------
A raw TRELLIS.2 GLB is one fused mesh with ONE untitled material carrying a baked
texture. Measured on real output (car-meshes/trellis/*.glb): 1 mesh, 1 primitive,
1 material, alphaMode OPAQUE. That car cannot pass the live catalogue gates, and
the reason is not quality — it is structure:

  * glass_probe -> "opaque"          : no transparent glazing material exists, and
                                       the owner ruling of 2026-08-11 makes opaque
                                       glazing an outright scrap (119 live cars
                                       were culled for exactly this).
  * colour_variants -> "no paintMaterialNames — nothing to respray"
                                     : no named body material, so the car cannot
                                       ship the eight DVLA colours.
  * tyres            : no distinct rubber material, so the body paint covers the
                       wheels and the car reads as a clay studio model.

So however good the geometry gets, generation alone can never clear the bar. The
missing step is separating the mesh into parts and giving each the material the
pipeline downstream actually looks for.

The target is not invented. `car-meshes/alam3d/golf_mv_polished.glb` is a
generated car that ALREADY passes every gate, and it has exactly four materials:

    Material_0      textured body        (resprayable -> 8 colours)
    Glass_Tint      BLEND alpha 0.72     (-> glass_probe "clear (proven)")
    Wheel_Dark      near-black, rough    (-> reads as rubber)
    Interior_Dark   near-black, matte

This stage reproduces that structure automatically.

MEASURED LIMIT — READ BEFORE EXTENDING THIS
-------------------------------------------
Geometric loose-part separation CANNOT isolate glazing on TRELLIS.2 output, and
this was measured, not guessed. On a real generated Golf:

  * raw export is UNWELDED -- a straight loose-part split gave 12,558 parts of
    three vertices each (individual triangles). Welding first is mandatory.
  * after welding, ONE part held 231,305 of 233,672 vertices -- 99.3% of the car.
    Body, windows, wheels and interior are a single continuous surface.
  * the parts this classifier then called "glass" were 0.5% of the mesh: mirror
    housings, badges, trim fragments sitting high and inset.
  * the output PASSED glass_probe ("clear (proven)") while a red respray of the
    body turned the windscreen and side windows RED along with the doors.

That last point is why the guard below exists. A stage that satisfies the gate
while putting glazing on the wrong polygons is more dangerous than one that
fails, because everything downstream then trusts it. The fix is NOT to lower the
threshold.

Two candidate fixes were considered and one was MEASURED DEAD:

  * "select window faces from the baked albedo" -- does NOT work in general, and
    the earlier version of this note claiming it would was wrong. The test car is
    a dark-blue Golf R: in its 2048x2048 albedo, glass, dark paint and dark trim
    are all the same near-black blue (mean luminance 53, 58% of texels below 40).
    Glazing is only texture-separable when the body colour happens to contrast
    with the (always dark) glass, so it fails on exactly the dark/black cars that
    are most common. Do not build this expecting it to generalise.

  * the reliable fix is a generator that outputs glazing as SEPARATE geometry, so
    "separate by loose parts" actually isolates it. TRELLIS.2 does not; part-based
    models (PartCrafter and successors) do. That is a MODEL change, tracked in
    CLAUDE.md "Generator research", not something this stage can paper over.

Until then, glazing must be split by hand, and this stage's job is only to name
and assign the parts once they ARE separable.

Classification is GEOMETRIC, not semantic — there is no part labelling in the
output to trust. Each loose part is judged on where it sits in the car's own
bounding box and on its shape. The heuristics are deliberately conservative: a
part that does not clearly look like glazing, a wheel or interior trim stays BODY,
because mislabelling body as glass would punch a hole in the car, which is far
worse than leaving a window opaque for a human to fix.

Usage:
    blender -b -noaudio --python pipeline/trellis/assign_materials.py -- \
        --in  candidate.glb --out candidate_mat.glb [--report r.json]

Verify afterwards (this is the whole point of the stage):
    python3 -c "import sys;sys.path.insert(0,'pipeline/ingest');import glass_probe as G;\
print(G.probe('x', url='file://...')['verdict'])"
"""
import json
import math
import os
import sys

try:
    import bpy
    import bmesh
    from mathutils import Vector
except ImportError:  # allows --selftest outside Blender
    bpy = None

# The proven scheme from golf_mv_polished.glb. Values are glTF-linear.
BODY_NAME = "Material_0"
SPEC = {
    "glass":    dict(name="Glass_Tint",    base=(0.030, 0.035, 0.045, 0.72),
                     metallic=0.0, roughness=0.05, blend=True),
    "wheel":    dict(name="Wheel_Dark",    base=(0.030, 0.030, 0.033, 1.0),
                     metallic=0.30, roughness=0.50, blend=False),
    "interior": dict(name="Interior_Dark", base=(0.045, 0.045, 0.050, 1.0),
                     metallic=0.0, roughness=0.90, blend=False),
}


def classify(part_bb, car_bb, n_verts, total_verts):
    """Return 'glass' | 'wheel' | 'interior' | 'body' for one loose part.

    part_bb / car_bb are (min_xyz, max_xyz) in world space, Z up.

    The tests are ordered cheapest-and-most-certain first, and every one of them
    has a deliberate bias toward returning 'body': a false 'glass' makes a hole
    in the car, a false 'body' just leaves a window for a human to fix.
    """
    (pmin, pmax), (cmin, cmax) = part_bb, car_bb
    ext = [pmax[i] - pmin[i] for i in range(3)]
    cext = [max(cmax[i] - cmin[i], 1e-9) for i in range(3)]

    # Which horizontal axis is the car's LENGTH and which is its WIDTH? Never
    # assume X -- sourced and generated GLBs arrive in both orientations, and the
    # whole width test below inverts if this is guessed wrong.
    LEN, WID = (0, 1) if cext[0] >= cext[1] else (1, 0)

    z0 = (pmin[2] - cmin[2]) / cext[2]
    z1 = (pmax[2] - cmin[2]) / cext[2]
    frac = n_verts / max(total_verts, 1)

    # WHEEL first: bottom third, small, and roughly as tall as it is long (a disc
    # from any side). A sill down there is long and flat, so the aspect test is
    # what separates them.
    if z1 < 0.45 and frac < 0.22:
        length = max(ext[0], ext[1])
        if length > 1e-9 and 0.6 < ext[2] / length < 1.7:
            return "wheel"

    # GLASS before interior: a windscreen is inset in both horizontal axes and
    # would otherwise be swallowed by the interior test.
    #
    # Thinness is measured LOOSELY (0.35, not 0.18) because a RAKED windscreen is
    # not thin along any axis-aligned direction -- a 60-degree screen 1.5m wide
    # still has ~0.45m of Z extent, and the tight threshold rejected it outright.
    # The check that actually does the work is the WIDTH inset: glazing always
    # has bodywork or pillars beside it, so it never spans the car's full width,
    # whereas a roof panel and a bonnet both do. That single test is what keeps
    # the roof and the bonnet as BODY.
    if z0 > 0.42 and frac < 0.30:
        srt = sorted(ext)
        thin = srt[2] > 1e-9 and srt[0] / srt[2] < 0.35
        inset_w = ext[WID] < 0.92 * cext[WID]
        if thin and inset_w:
            return "glass"

    # INTERIOR: enclosed in BOTH horizontal axes, mid band, small.
    inset_l = pmin[LEN] > cmin[LEN] + 0.06 * cext[LEN] and pmax[LEN] < cmax[LEN] - 0.06 * cext[LEN]
    inset_w2 = pmin[WID] > cmin[WID] + 0.06 * cext[WID] and pmax[WID] < cmax[WID] - 0.06 * cext[WID]
    if inset_l and inset_w2 and 0.15 < z0 < 0.75 and frac < 0.25:
        return "interior"

    return "body"


def _mk_material(kind):
    s = SPEC[kind]
    m = bpy.data.materials.new(s["name"])
    m.use_nodes = True
    b = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    b.inputs["Base Color"].default_value = s["base"]
    b.inputs["Metallic"].default_value = s["metallic"]
    b.inputs["Roughness"].default_value = s["roughness"]
    if s["blend"]:
        # glTF exporter reads alpha from Base Color's 4th channel plus this mode
        m.blend_method = "BLEND"
        try:
            b.inputs["Alpha"].default_value = s["base"][3]
        except KeyError:
            pass
    return m


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    def arg(flag, default=None):
        return argv[argv.index(flag) + 1] if flag in argv else default
    src, dst = arg("--in"), arg("--out")
    report_path = arg("--report")
    if not src or not dst:
        sys.exit("usage: --in <glb> --out <glb> [--report <json>]")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=src)

    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    if not meshes:
        sys.exit("no mesh in input")

    # Keep the ORIGINAL body material: it carries the baked texture, and
    # respray_gltf drops the texture and sets baseColorFactor, so the car can
    # still take the eight colours. Renaming it is what makes it findable.
    body_mat = None
    for o in meshes:
        for sl in o.material_slots:
            if sl.material:
                body_mat = sl.material
                break
        if body_mat:
            break
    if body_mat is None:
        body_mat = bpy.data.materials.new(BODY_NAME)
        body_mat.use_nodes = True
    body_mat.name = BODY_NAME

    # WELD BEFORE SPLITTING -- this is load-bearing and was found the hard way.
    # TRELLIS.2 exports UNWELDED vertices: every triangle is its own island. A
    # straight "separate by loose parts" on real output produced 12,558 parts of
    # THREE vertices each -- individual triangles, not car parts -- and the
    # classifier duly scattered 4,504 "glass" triangles across the whole car.
    # Merging by distance first is what turns triangle soup into real components.
    #
    # The threshold is scaled to the model, not absolute: generated cars arrive at
    # wildly different scales (measured 0.017 to 1900 units end to end elsewhere in
    # this repo), so a fixed 0.0001 welds everything on one and nothing on another.
    bpy.ops.object.select_all(action="DESELECT")
    for o in meshes:
        o.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    if len(meshes) > 1:
        bpy.ops.object.join()
    obj = bpy.context.view_layer.objects.active

    diag = max(obj.dimensions) or 1.0
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.remove_doubles(threshold=diag * 1e-4)
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.separate(type="LOOSE")
    bpy.ops.object.mode_set(mode="OBJECT")

    parts = [o for o in bpy.data.objects if o.type == "MESH"]
    total_v = sum(len(o.data.vertices) for o in parts)

    cmin = [1e18] * 3
    cmax = [-1e18] * 3
    boxes = {}
    for o in parts:
        pmin = [1e18] * 3
        pmax = [-1e18] * 3
        for c in o.bound_box:
            w = o.matrix_world @ Vector(c)
            for i in range(3):
                pmin[i] = min(pmin[i], w[i]); pmax[i] = max(pmax[i], w[i])
                cmin[i] = min(cmin[i], w[i]); cmax[i] = max(cmax[i], w[i])
        boxes[o.name] = (pmin, pmax)

    made = {}
    counts = {"body": 0, "glass": 0, "wheel": 0, "interior": 0}
    rows = []
    for o in parts:
        kind = classify(boxes[o.name], (cmin, cmax), len(o.data.vertices), total_v)
        counts[kind] += 1
        if kind == "body":
            mat = body_mat
        else:
            if kind not in made:
                made[kind] = _mk_material(kind)
            mat = made[kind]
        o.data.materials.clear()
        o.data.materials.append(mat)
        rows.append({"part": o.name, "kind": kind, "verts": len(o.data.vertices),
                     "material": mat.name})

    vfrac = {k: 0 for k in counts}
    for r in rows:
        vfrac[r["kind"]] += r["verts"]
    tot_v = max(sum(vfrac.values()), 1)
    print(f"PARTS={len(parts)} " + " ".join(f"{k}={v}" for k, v in counts.items()))
    print("VERT SHARE: " + " ".join(f"{k}={100*v/tot_v:.1f}%" for k, v in vfrac.items()))

    # THE GUARD. Without it this stage produces a file that PASSES glass_probe
    # while being flatly wrong, which is worse than producing nothing.
    #
    # Measured on real TRELLIS.2 output: after welding, ONE part held 231,305 of
    # 233,672 vertices -- 99.3% of the car. Body, windows, wheels and interior are
    # a single continuous shell, so loose-part separation can never isolate the
    # glazing. The 24 parts this classifier called "glass" were 0.5% of the mesh:
    # mirror housings, badges and trim fragments that happen to sit high and inset.
    # The result named a Glass_Tint material (so the probe reported "clear
    # (proven)") while the actual windows stayed on the body material and
    # resprayed RED along with the doors.
    #
    # Real glazing is roughly 4-12% of a car's vertices. Below GLASS_MIN_FRAC the
    # segmentation has not found windows, and saying so is the only honest output.
    GLASS_MIN_FRAC = 0.02
    got = vfrac["glass"] / tot_v
    dominant = max(r["verts"] for r in rows) / tot_v
    if got < GLASS_MIN_FRAC:
        print(f"REFUSING TO WRITE: glazing is {100*got:.2f}% of vertices "
              f"(need >={100*GLASS_MIN_FRAC:.0f}%), and the largest single part is "
              f"{100*dominant:.1f}% of the mesh.")
        print("  The car is one fused shell -- the windows are not separable "
              "geometry, so this stage cannot find them. Writing anyway would "
              "produce a file that passes glass_probe with the glazing on the "
              "wrong polygons. Use texture-based selection or split the windows "
              "by hand; do NOT relax this threshold.")
        if report_path:
            json.dump({"input": src, "output": None, "refused": True,
                       "reason": "glazing fraction below threshold — fused shell",
                       "glass_vert_frac": got, "largest_part_frac": dominant,
                       "parts": len(parts), "counts": counts, "detail": rows},
                      open(report_path, "w"), indent=1)
        sys.exit(3)

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.export_scene.gltf(filepath=dst, export_format="GLB",
                              export_materials="EXPORT", use_selection=True)
    print(f"WROTE {dst}")
    if report_path:
        json.dump({"input": src, "output": dst, "parts": len(parts),
                   "counts": counts, "detail": rows},
                  open(report_path, "w"), indent=1)


def selftest():
    """Classifier tests that need no Blender. A saloon roughly 4.3 x 1.8 x 1.45."""
    car = ([0, 0, 0], [4.3, 1.8, 1.45])
    cases = [
        # (name, part_bb, verts, expect)
        ("windscreen (thin, upper, inset)",
         ([1.4, 0.15, 0.95], [2.1, 1.65, 1.40]), 800, "glass"),
        ("side window (thin in Y, upper)",
         ([2.0, 0.02, 0.95], [3.0, 0.10, 1.30]), 400, "glass"),
        ("front wheel (low, disc-shaped)",
         ([0.6, 0.0, 0.0], [1.25, 0.25, 0.65]), 900, "wheel"),
        ("rear wheel",
         ([3.1, 0.0, 0.0], [3.75, 0.25, 0.65]), 900, "wheel"),
        ("seat (inset, mid, small)",
         ([1.9, 0.45, 0.35], [2.5, 1.35, 0.95]), 700, "interior"),
        # must NOT be mis-called
        ("body shell (dominant)",
         ([0, 0, 0.1], [4.3, 1.8, 1.45]), 40000, "body"),
        ("roof panel (thin+upper but FULL width -> body, not glass)",
         ([1.5, 0.0, 1.36], [3.0, 1.80, 1.45]), 600, "body"),
        ("sill (low but long and flat -> body, not wheel)",
         ([1.0, 0.0, 0.05], [3.3, 0.12, 0.30]), 500, "body"),
        ("bonnet (low-ish, wide, flat -> body)",
         ([0.1, 0.05, 0.75], [1.4, 1.75, 0.95]), 1500, "body"),
    ]
    bad = 0
    for name, bb, v, want in cases:
        got = classify(bb, car, v, 50000)
        ok = got == want
        bad += not ok
        print(f"{'ok ' if ok else 'BAD'} {got:9} want {want:9}  {name}")
    print(f"\n{len(cases)-bad}/{len(cases)} classifier cases pass")
    return bad == 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(0 if selftest() else 1)
    main()
