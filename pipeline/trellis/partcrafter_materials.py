#!/usr/bin/env python3
"""partcrafter_materials.py — make a PartCrafter car SHIPPABLE.

Sibling of assign_materials.py, for PART-NATIVE generator output. Do NOT run
assign_materials.py on PartCrafter files: that stage joins and welds before
splitting, which is correct for a fused TRELLIS shell and DESTROYS PartCrafter's
separation — the parts touch where they meet, so welding fuses them back into
one blob (measured; see CLAUDE.md "PartCrafter TESTED on a real car").

What PartCrafter emits (measured on the 2026-08-12 num_parts=16 run):
  * N separate mesh objects, untextured, no meaningful materials.
  * The GREENHOUSE is its own closed canopy — windscreen, side glass, rear
    screen AND ROOF SKIN fused as one part (13.6% of verts on the test car).
  * The body shell has real window OPENINGS; underbody/chassis is separate;
    wheels are separate; a few percent of verts are floating DEBRIS blobs.
  * Part indices are NOT semantic — which index is the canopy varies per run,
    so every part must be classified from its own geometry.

This stage therefore:
  1. classifies every part geometrically (body / canopy / wheel / interior /
     debris) against a ROBUST car bbox (percentile bounds, so floating debris
     cannot stretch the frame of reference),
  2. deletes debris (it renders as floating junk on the audit sheet),
  3. splits the canopy PER-FACE by normal: up-facing area is roof (body
     paint), sloped/vertical area is glazing (Glass_Tint). Measured on the
     test canopy: 46.4% of face area is strongly up-facing = roof panel.
     Pillars inside the canopy come out glazing-side — acceptable "floating
     roof" look at alpha 0.72; note it, don't fight it in v1,
  4. assigns the proven golf_mv_polished 4-material scheme (same SPEC as
     assign_materials.py) so every downstream gate finds what it expects,
  5. GUARDS: refuses to write unless glazing landed on >=2% of total verts,
     for the same reason assign_materials refuses — a file that names
     Glass_Tint without putting it on the windows passes glass_probe while
     the actual glazing resprays with the body. That failure mode is worse
     than no output.

Usage:
    blender -b -noaudio --python pipeline/trellis/partcrafter_materials.py -- \
        --in results/car16/object.glb --out car16_mat.glb [--report r.json]
    python3 pipeline/trellis/partcrafter_materials.py --selftest
"""
import json
import sys

try:
    import bpy
    from mathutils import Vector
except ImportError:  # allows --selftest outside Blender
    bpy = None

# Same proven scheme as assign_materials.py (golf_mv_polished.glb).
BODY_NAME = "Material_0"
BODY_BASE = (0.60, 0.61, 0.63, 1.0)  # neutral silver; respray overwrites it
SPEC = {
    "glass":    dict(name="Glass_Tint",    base=(0.030, 0.035, 0.045, 0.72),
                     metallic=0.0, roughness=0.05, blend=True),
    "wheel":    dict(name="Wheel_Dark",    base=(0.030, 0.030, 0.033, 1.0),
                     metallic=0.30, roughness=0.50, blend=False),
    "interior": dict(name="Interior_Dark", base=(0.045, 0.045, 0.050, 1.0),
                     metallic=0.0, roughness=0.90, blend=False),
    # Smoked glossy lens: generated lamp blobs have no internal detail, so a
    # CLEAR lens would show nothing behind it. Dark gloss reads as a modern
    # lamp unit and — the point — never resprays with the body.
    "lamp":     dict(name="Lamp_Lens",     base=(0.080, 0.080, 0.090, 1.0),
                     metallic=0.0, roughness=0.08, blend=False),
}

GLASS_MIN_FRAC = 0.02   # same bar as assign_materials.py; do NOT relax
# |n_up| above this = roof panel inside the canopy. 0.85, not lower: a fast
# raked windscreen points its normal well UP (a screen 30 deg from horizontal
# has n_up ~0.87), and at 0.70 the red-control render showed the windscreen
# respraying WITH the body. Roof skin proper sits at n_up ~0.95+.
ROOF_NORMAL_UP = 0.85


def classify(feat, car):
    """Return 'canopy'|'wheel'|'interior'|'debris'|'body' for one part.

    feat: dict(frac, lo, hi, wspan) — vert fraction, normalized [0..1] bbox in
          car frame as (length, width, height) triples, and wspan = the part's
          extents in WORLD units (same axis order). wspan exists because the
          normalized frame scales each axis by a different car extent, so a
          round wheel reads as 2.25:1 there — aspect tests must use world units.
    car:  unused today; kept so future features (e.g. wheelbase) have a slot.

    Ordered most-certain first, biased toward 'body': a false 'canopy' makes
    the roof transparent, a false 'body' just leaves a window opaque for a
    human to catch — the cheaper mistake.
    """
    lo, hi = feat["lo"], feat["hi"]
    frac = feat["frac"]
    span = [hi[i] - lo[i] for i in range(3)]

    # DEBRIS: small and floating clear of the car body — entirely above the
    # roofline, below the ground plane, or outside the footprint. The robust
    # (percentile) car bbox is what makes "above 1.0" meaningful: debris sits
    # beyond the 98th pct. Sub-0.05% specks are deleted wherever they are —
    # they are invisible as geometry and pure noise in the material table.
    if frac < 0.0005:
        return "debris"
    if frac < 0.015 and (lo[2] > 0.98 or hi[2] < 0.02 or hi[0] < 0.02
                         or lo[0] > 0.98 or hi[1] < 0.02 or lo[1] > 0.98):
        return "debris"

    # WHEEL: bottom half, small, disc-like in WORLD units (height ~ length;
    # normalized units distort this), not a sill (sills are long and flat).
    if hi[2] < 0.55 and frac < 0.20:
        w = feat["wspan"]
        length = max(w[0], w[1])
        if length > 1e-9 and 0.5 < w[2] / length < 2.0:
            return "wheel"

    # CANOPY: the greenhouse shell. Starts near/above the beltline, REACHES
    # THE ROOFLINE (that is what separates it from a pillar/rail frame that
    # also spans the cabin but tops out below the roof skin), spans a real
    # stretch of the car in BOTH horizontal axes (debris and mirrors don't),
    # and is a substantial minority of the mesh. The beltline test is loose
    # (0.30) because the canopy's skirt dips to meet the body.
    # Beltline tolerance 0.22, not 0.30: the Golf run's genuine canopy part
    # (261k verts, cabin-spanning, roofline-reaching) had its skirt at 0.25
    # and was called body — zero glazing, refusal downstream. Safe to loosen:
    # hybrid_transfer's beltline prior already returns any canopy face below
    # 0.40 height to body, so a deep skirt cannot leak glass onto the doors.
    if (lo[2] > 0.22 and hi[2] > 0.92 and frac > 0.03 and frac < 0.30
            and span[0] > 0.35 and span[1] > 0.45):
        return "canopy"

    # WINDSCREEN — the HIGH-ROOF (van) case. The rule above encodes a PASSENGER
    # CAR, where the greenhouse IS the top of the vehicle, so it demands
    # hi[2] > 0.92. On a panel van the roof is a separate high panel and the
    # glazing tops out just under it. Measured on the E-Transit Custom hybrid
    # run: the real windscreen part sat at hi[2] = 0.92 EXACTLY and failed by a
    # hair, so hybrid_transfer got zero canopy seeds -- and with no seeds its
    # graph cut cannot create glass at all (d_can falls back to 9.0), so the
    # run refused with glass 0.0%. The refusal was correct; the definition was
    # the defect. Reviewer (Fable 5) found this in the code after I had wrongly
    # reported the root cause as "PartCrafter gave no glazing".
    #
    # WHY THE EXTRA TESTS, and why not simply lower hi[2]: geometry_5 and
    # geometry_13 on that van have NEARLY IDENTICAL bboxes to the windscreen
    # (upper band, full width, hi[2] = 0.92) and carry 4.5% and 0.0% glazing
    # area respectively -- pure roof/upper-flank skin. Lowering the ceiling
    # alone paints them glass. What separates them is REACHING AN END of the
    # car: a windscreen runs to the nose (lo[0] = 0.01) while roof panels start
    # mid-body (0.47, 0.67). Validated against per-part region occupancy
    # measured from the actual mesh: 7 of 8 correct, and the one miss
    # (a 1%-area narrow fragment, span[1] = 0.32) fails in the SAFE direction
    # this function's docstring asks for -- an opaque small window, not a
    # transparent roof.
    #
    # Ordering matters: this sits AFTER the canopy test, so a passenger car
    # whose fused greenhouse already matches above is untouched by construction.
    if (lo[2] > 0.45 and hi[2] > 0.85 and span[1] > 0.45
            and 0.02 < frac < 0.15
            and (lo[0] < 0.10 or hi[0] > 0.90)):
        return "canopy"

    # LAMP: small component at the extreme nose or tail, lamp height band,
    # offset to one side (a grille or bumper is central/full-width, a lamp is
    # not). Light bars that span the full width stay body — conservative.
    at_end = lo[0] > 0.80 or hi[0] < 0.20
    offset = hi[1] < 0.55 or lo[1] > 0.45
    if at_end and offset and frac < 0.04 and 0.25 < lo[2] and hi[2] < 0.85 \
            and span[1] < 0.45:
        return "lamp"

    # INTERIOR: enclosed in both horizontal axes, mid band, small.
    inset_l = lo[0] > 0.06 and hi[0] < 0.94
    inset_w = lo[1] > 0.06 and hi[1] < 0.94
    if inset_l and inset_w and 0.10 < lo[2] < 0.75 and frac < 0.25:
        return "interior"

    return "body"


# ---------------------------------------------------------------- Blender ---

def _mk_material(kind):
    s = SPEC[kind]
    m = bpy.data.materials.new(s["name"])
    m.use_nodes = True
    b = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    b.inputs["Base Color"].default_value = s["base"]
    b.inputs["Metallic"].default_value = s["metallic"]
    b.inputs["Roughness"].default_value = s["roughness"]
    if s["blend"]:
        m.blend_method = "BLEND"
        try:
            b.inputs["Alpha"].default_value = s["base"][3]
        except KeyError:
            pass
    return m


def _world_bounds(o):
    pmin = [1e18] * 3
    pmax = [-1e18] * 3
    for c in o.bound_box:
        w = o.matrix_world @ Vector(c)
        for i in range(3):
            pmin[i] = min(pmin[i], w[i]); pmax[i] = max(pmax[i], w[i])
    return pmin, pmax


def main():
    import numpy as np
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    def arg(flag, default=None):
        return argv[argv.index(flag) + 1] if flag in argv else default
    src, dst = arg("--in"), arg("--out")
    report_path = arg("--report")
    if not src or not dst:
        sys.exit("usage: --in <glb> --out <glb> [--report <json>]")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=src)
    parts = [o for o in bpy.data.objects if o.type == "MESH"]
    if len(parts) < 4:
        sys.exit(f"only {len(parts)} mesh parts — this stage is for part-native "
                 "output; run assign_materials.py on fused meshes instead")

    # SPLIT EACH PART INTO CONNECTED COMPONENTS — without welding (PartCrafter
    # parts are internally welded, unlike TRELLIS exports). Measured on the
    # 16-part test car: the "wheel" part is 2 real discs plus 19 junk
    # fragments, the roof part is one real skin plus 16 floating blobs. A
    # part-level verdict would paint the junk along with the good geometry;
    # component-level verdicts let the junk be culled as debris.
    bpy.ops.object.select_all(action="DESELECT")
    for o in parts:
        o.select_set(True)
        bpy.context.view_layer.objects.active = o
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.mesh.separate(type="LOOSE")
        bpy.ops.object.mode_set(mode="OBJECT")
        o.select_set(False)
    parts = [o for o in bpy.data.objects if o.type == "MESH"]

    # ROBUST car bbox: 2nd/98th percentile of ALL vertices per axis, so a few
    # floating debris blobs cannot stretch the frame every part is judged in.
    allv = []
    for o in parts:
        n = len(o.data.vertices)
        co = np.empty(n * 3)
        o.data.vertices.foreach_get("co", co)
        v = co.reshape(-1, 3)
        M = np.array(o.matrix_world)
        allv.append(v @ M[:3, :3].T + M[:3, 3])
    allv = np.concatenate(allv)
    cmin = np.percentile(allv, 2, axis=0)
    cmax = np.percentile(allv, 98, axis=0)
    cext = np.maximum(cmax - cmin, 1e-9)

    # Axis roles. UP is NOT inferred from extents: on the real 16-part test
    # car the robust width and height measure 0.773 vs 0.809 — a near-tie that
    # the extent sort resolved WRONG (it called the wheels "canopy" and the
    # canopy "body"). This is the same coin-flip failure class as the render
    # worker's inversion bug (CLAUDE.md 2026-08-11). Instead trust the glTF
    # Y-up convention, which Blender's importer maps to +Z: UP is always
    # Blender Z here, and only LEN vs WID comes from the extents.
    UP = 2
    LEN, WID = (0, 1) if cext[0] >= cext[1] else (1, 0)

    total_v = len(allv)
    feats = {}
    for o in parts:
        pmin, pmax = _world_bounds(o)
        lo = [(pmin[a] - cmin[a]) / cext[a] for a in (LEN, WID, UP)]
        hi = [(pmax[a] - cmin[a]) / cext[a] for a in (LEN, WID, UP)]
        feats[o.name] = {"frac": len(o.data.vertices) / total_v,
                         "lo": lo, "hi": hi,
                         "wspan": [pmax[a] - pmin[a] for a in (LEN, WID, UP)]}

    body_mat = bpy.data.materials.new(BODY_NAME)
    body_mat.use_nodes = True
    bsdf = next(n for n in body_mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Base Color"].default_value = BODY_BASE
    bsdf.inputs["Metallic"].default_value = 0.1
    bsdf.inputs["Roughness"].default_value = 0.35

    made = {}
    counts = {"body": 0, "canopy": 0, "wheel": 0, "interior": 0, "lamp": 0, "debris": 0}
    vshare = {k: 0 for k in counts}
    glass_verts = 0
    rows = []
    for o in parts:
        kind = classify(feats[o.name], None)
        counts[kind] += 1
        nv = len(o.data.vertices)
        vshare[kind] += nv
        rows.append({"part": o.name, "kind": kind, "verts": nv,
                     "bbox": [feats[o.name]["lo"], feats[o.name]["hi"]]})
        if kind == "debris":
            continue                          # deleted after the loop
        if kind == "body":
            o.data.materials.clear()
            o.data.materials.append(body_mat)
        elif kind in ("wheel", "interior", "lamp"):
            if kind not in made:
                made[kind] = _mk_material(kind)
            o.data.materials.clear()
            o.data.materials.append(made[kind])
        elif kind == "canopy":
            # PER-FACE split: up-facing area = roof skin (body paint), the
            # rest = glazing. World-space normals, UP axis from the car frame.
            if "glass" not in made:
                made["glass"] = _mk_material("glass")
            o.data.materials.clear()
            o.data.materials.append(made["glass"])   # slot 0 = glazing
            o.data.materials.append(body_mat)        # slot 1 = roof
            R = np.array(o.matrix_world)[:3, :3]
            for poly in o.data.polygons:
                n_world = R @ np.array(poly.normal)
                nl = np.linalg.norm(n_world) or 1.0
                if abs(n_world[UP]) / nl > ROOF_NORMAL_UP:
                    poly.material_index = 1
                else:
                    poly.material_index = 0
                    glass_verts += len(poly.vertices)

    for o in parts:
        k = next(r["kind"] for r in rows if r["part"] == o.name)
        if k == "debris":
            bpy.data.objects.remove(o, do_unlink=True)
            continue
        # STRIP VERTEX COLOURS — load-bearing. PartCrafter bakes per-part
        # COLOR_0 attributes (its own preview colouring), and glTF MULTIPLIES
        # COLOR_0 into baseColorFactor: the first export shipped a BLUE car
        # from a silver Material_0, with a green windscreen. The materials
        # were correct; the vertex colours were repainting them.
        while o.data.color_attributes:
            o.data.color_attributes.remove(o.data.color_attributes[0])

    got = glass_verts / max(total_v, 1)  # face-verts double count; lower bound below
    # glass_verts counts per-face corners (overcounts shared verts) — use the
    # canopy's own vert count scaled by its glazing AREA share instead for the
    # honest number reported and guarded on.
    canopy_rows = [r for r in rows if r["kind"] == "canopy"]
    canopy_v = sum(r["verts"] for r in canopy_rows)
    got = (canopy_v / total_v) if canopy_rows else 0.0

    print(f"PARTS={len(parts)} " + " ".join(f"{k}={v}" for k, v in counts.items()))
    print("VERT SHARE: " + " ".join(f"{k}={100*v/total_v:.1f}%" for k, v in vshare.items()))
    print(f"CANOPY (glazing+roof) = {100*got:.1f}% of verts; "
          f"debris deleted = {vshare['debris']} verts")

    if got < GLASS_MIN_FRAC:
        print(f"REFUSING TO WRITE: no canopy found (glazing candidate is "
              f"{100*got:.2f}% of verts, need >={100*GLASS_MIN_FRAC:.0f}%).")
        print("  Writing anyway would produce a file that passes glass_probe "
              "with Glass_Tint on the wrong polygons. If this is a fused mesh, "
              "use assign_materials.py; if the run really produced no canopy, "
              "regenerate with more parts. Do NOT relax this threshold.")
        if report_path:
            json.dump({"input": src, "output": None, "refused": True,
                       "reason": "no canopy part found",
                       "counts": counts, "detail": rows},
                      open(report_path, "w"), indent=1)
        sys.exit(3)

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.export_scene.gltf(filepath=dst, export_format="GLB",
                              export_materials="EXPORT", use_selection=True)
    print(f"WROTE {dst}")
    if report_path:
        json.dump({"input": src, "output": dst, "parts": len(parts),
                   "counts": counts, "canopy_vert_frac": got,
                   "detail": rows}, open(report_path, "w"), indent=1)


# --------------------------------------------------------------- selftest ---

def selftest():
    """Classifier cases: normalized (length, width, height) frame + world
    spans for a 4.3 x 1.8 x 1.45 saloon."""
    def W(lo, hi):
        return [(hi[i] - lo[i]) * c for i, c in enumerate((4.3, 1.8, 1.45))]
    cases = [
        # (name, frac, lo, hi, expect)
        ("canopy (beltline up to roofline, spans cabin)",
         0.136, [0.20, 0.05, 0.42], [0.80, 0.95, 1.00], "canopy"),
        ("canopy with deep skirt (the Golf near-miss: lo up 0.25)",
         0.159, [0.00, 0.04, 0.25], [0.78, 0.96, 0.95], "canopy"),
        ("full side shell (reaches roof but starts at sill -> body)",
         0.29, [0.00, 0.00, 0.05], [1.00, 1.00, 0.95], "body"),
        ("body shell (dominant)",
         0.298, [0.00, 0.00, 0.00], [1.00, 1.00, 0.95], "body"),
        ("underbody/chassis (low, full length)",
         0.274, [0.00, 0.00, 0.00], [1.00, 1.00, 0.50], "body"),
        ("wheel (low, disc in world units)",
         0.056, [0.10, 0.00, 0.00], [0.25, 0.20, 0.45], "wheel"),
        ("seat block (inset, mid)",
         0.03, [0.35, 0.25, 0.15], [0.60, 0.75, 0.55], "interior"),
        ("floating debris above roof",
         0.005, [0.40, 0.45, 1.05], [0.48, 0.55, 1.15], "debris"),
        ("debris off the nose",
         0.004, [-0.20, 0.40, 0.30], [-0.05, 0.55, 0.40], "debris"),
        # must-NOT-match cases
        ("mirror (small, high, but narrow span -> not canopy)",
         0.006, [0.30, 0.92, 0.55], [0.36, 1.00, 0.70], "body"),
        ("sill (low, long+flat -> not wheel)",
         0.01, [0.15, 0.00, 0.02], [0.85, 0.06, 0.18], "body"),
        ("bonnet fragment (wide, mid-low -> body not canopy)",
         0.05, [0.00, 0.05, 0.35], [0.30, 0.95, 0.60], "body"),
        ("spoiler (high but short span -> not canopy)",
         0.02, [0.88, 0.15, 0.75], [1.00, 0.85, 0.95], "body"),
        ("headlamp (nose, offset left, lamp band)",
         0.004, [0.86, 0.08, 0.40], [0.98, 0.35, 0.60], "lamp"),
        ("tail lamp (tail, offset right)",
         0.003, [0.02, 0.70, 0.45], [0.12, 0.95, 0.70], "lamp"),
        ("grille (nose but CENTRAL -> body, not lamp)",
         0.008, [0.90, 0.30, 0.30], [1.00, 0.70, 0.55], "body"),
        ("front bumper (nose but full width -> body)",
         0.03, [0.88, 0.02, 0.10], [1.00, 0.98, 0.45], "body"),
        # A pillar/rail frame spans the cabin like the canopy but tops out
        # BELOW the roof skin. Body (paint) is the safe call: body-coloured
        # pillars are normal; making them transparent is not.
        ("pillar frame (spans cabin, below roofline -> body, not canopy)",
         0.077, [0.15, 0.05, 0.35], [0.75, 0.90, 0.90], "body"),
    ]
    bad = 0
    for name, frac, lo, hi, want in cases:
        got = classify({"frac": frac, "lo": lo, "hi": hi, "wspan": W(lo, hi)}, None)
        ok = got == want
        bad += not ok
        print(f"{'ok ' if ok else 'BAD'} {got:9} want {want:9}  {name}")
    print(f"\n{len(cases)-bad}/{len(cases)} classifier cases pass")
    return bad == 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(0 if selftest() else 1)
    main()
