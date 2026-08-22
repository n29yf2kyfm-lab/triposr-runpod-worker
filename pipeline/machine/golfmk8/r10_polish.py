#!/usr/bin/env python3
"""r10_polish.py — give a recovered car a real paint finish, so it can be judged.

WHY THIS IS NEEDED AT ALL. r8_reglaze fixes the GLAZING and nothing else. The
cars coming out of the glazing-quarantine pool ship a body material that is a
flat untextured grey -- aston-martin-vantage-v1's `Body` is 0.5, ford-focus-w6-v1's
`body1` is 0.8 -- with no clearcoat, no metallic flake and roughness near 0.87.
Rendered, that reads as unfired clay, and the owner's standing ruling is that a
car which reads as a prototype fails the audit however clean its geometry is.
Judging a reglazed car off a clay render therefore answers the wrong question:
it tells you the source pack shipped a grey placeholder in the paint slot, which
was already known, not whether the car underneath is worth keeping.

WHAT IT DOES NOT DO. It does not invent detail. Paint is a MATERIAL, and setting
it cannot sharpen a soft panel, close a shut line or fix a torn shell -- the
same distinction this project has drawn since the generated-car work: the
material layer and the surfacing layer are separate, and fixing one has never
fixed the other. A car that is still soft under good paint is still a fail; this
just stops good cars failing for the wrong reason.

FINDING THE PAINT MATERIAL: BY VISIBILITY FROM OUTSIDE, measured with rays.
A name test would find `body1` and `Body` and would miss skoda-octavia-w7-v1
entirely, whose body shell is called `ext_glass_9`. Two cheaper measurements
were tried first and BOTH picked the wrong material, which is why this does the
expensive thing:

  * LARGEST SURFACE AREA picked `black` on the Aston -- 28.24 area against
    `Body`'s 11.77. `black` is the inner shell: door-card backing, boot lining,
    the underside of panels. It is bigger than the body precisely because it is
    every hidden surface at once. Painting it silver paints the car's insides.
  * TRIANGLE DENSITY (tris per unit area, on the theory that body panels are
    finely tessellated and filler sheets are coarse) was worse still: the top of
    the list is decals and badges -- SIDEREF_EMI at 106,554, ASV8_RIM_SUBLOGO at
    82,774 -- because a tiny material with any detail at all wins a ratio.

Both failed the same way: they measure how MUCH of a material exists, and paint
is not the material there is most of, it is the material you can SEE. So this
casts rays at the car from all round and counts which material each ray hits
FIRST. That is the definition of the outer skin, it needs no name, and it puts
the inner shell at zero because rays never reach it.

Rays, not a render, because a render would need the camera, lighting and view
transform to be right before the measurement means anything -- and this project
has three recorded cases of a view transform producing a false verdict.

THE EXCLUSIONS ARE THE WHOLE JOB. Painting glazing makes an opaque car; painting
a tyre is the exact defect the owner ruled on twice; painting a rim makes a
wheel vanish. Each exclusion below is a name list AND, for lamps, a geometric
check, because CLAUDE.md records four separate rounds of a lamp name list being
incomplete.

Run: blender -b --python r10_polish.py -- in.glb out.glb <colour> [report.json]
     colour: a palette name below, or r,g,b in linear 0-1
Env: R10_ROUGH (0.28) · R10_CLEARCOAT (1.0) · R10_METALLIC (0.55)
     R10_TYRE (1) set 0 to leave tyre materials untouched
"""
import json
import os
import sys

import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
SRC, DST = argv[0], argv[1]
COLOUR = argv[2] if len(argv) > 2 else "racing-green"
REPORT = argv[3] if len(argv) > 3 else None

ROUGH = float(os.environ.get("R10_ROUGH", "0.28"))
COAT = float(os.environ.get("R10_CLEARCOAT", "1.0"))
# 0.55 was the first value tried and it is WRONG for car paint: the Aston came
# back looking like liquid mercury, a mirror rather than a painted panel. Real
# metallic paint is a dielectric clearcoat over a base carrying a little flake,
# so the Principled metallic input belongs near 0.15 with the coat doing the
# gloss. Judged on the render, which is the only thing that can judge it.
METAL = float(os.environ.get("R10_METALLIC", "0.15"))
DO_TYRE = os.environ.get("R10_TYRE", "1") == "1"
# Reglazing makes the CABIN visible for the first time, and some source packs
# ship a violently saturated placeholder in there -- ford-focus-w6-v1's seats
# are pure green, which is not a colour any car interior has ever been. This
# desaturates an interior material only when it is BOTH strongly saturated and
# bright, so a genuine tan or red leather (saturated but not neon) is left
# alone. Off by default: it changes appearance, and appearance changes should
# be asked for.
DO_CABIN = os.environ.get("R10_CABIN", "0") == "1"
# Share of exterior visibility at which a measurement overrules an "interior"
# name. 0.35 sits well above what any real cabin part can reach when glazing
# blocks the ray (the Aston's best interior scores under 1%) and well below
# what a real skin reaches (52-58% on all three cars measured).
OVERRIDE_VIS = float(os.environ.get("R10_OVERRIDE_VIS", "0.35"))

# Linear values, not sRGB. Blender's Base Color socket is linear, and feeding it
# sRGB numbers is how a "dark grey" arrives on screen as mid grey.
PALETTE = {
    "racing-green": (0.012, 0.055, 0.030),
    "silver":       (0.520, 0.530, 0.545),
    "gunmetal":     (0.075, 0.082, 0.092),
    "black":        (0.015, 0.015, 0.017),
    "white":        (0.780, 0.780, 0.790),
    "red":          (0.380, 0.020, 0.022),
    "blue":         (0.020, 0.055, 0.230),
}

GLASSY = ("glass", "window", "windscreen", "windshield", "screen", "glas",
          "scheibe", "fenster", "vidro", "backlight", "quarter")
# Wheels, rubber and brakes. `disc`/`caliper`/`brake` matter because they sit
# inside the wheel and a mispainted caliper is as visible as a mispainted tyre.
WHEELY = ("tire", "tyre", "rubber", "rim", "wheel", "alloy", "hub", "caliper",
          "brakedisk", "brake_disc", "disc", "disk", "spoke")
# Interior. `int_`/`_int` as affixes so they cannot match "print" or "paint".
INTERIOR = ("interior", "seat", "leather", "carpet", "dash", "gauge", "steering",
            "alcan", "alcantara", "console", "trim_int", "cabin", "headliner")
# Everything that is exterior but must keep its own finish.
KEEPOUT = ("chrome", "carbon", "grill", "grille", "exhaust", "exh", "logo",
           "badge", "emblem", "plate", "mirror", "wiper", "underbody", "shadow",
           "lamp", "light", "lens", "reflector", "keyhole", "vent", "mesh")

TYRE_WORDS = ("tire", "tyre", "rubber")


def affix(nm, tok):
    return nm.startswith(tok) or nm.endswith(tok) or f"_{tok}" in nm


def excluded(nm):
    """Why this material cannot be the paint, or None."""
    if any(g in nm for g in GLASSY):
        return "glazing"
    if any(w in nm for w in WHEELY):
        return "wheel/tyre/brake"
    if any(i in nm for i in INTERIOR) or affix(nm, "int"):
        return "interior"
    if any(k in nm for k in KEEPOUT):
        return "keeps its own finish"
    return None


bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=SRC)

# --- measure every material: exterior area, and where it sits ---------------
lo = [1e18] * 3
hi = [-1e18] * 3
area = {}
box = {}
for ob in bpy.data.objects:
    if ob.type != "MESH" or not ob.data.polygons:
        continue
    mw = ob.matrix_world
    mats = list(ob.data.materials)
    for v in ob.data.vertices:
        w = mw @ v.co
        for i in range(3):
            lo[i] = min(lo[i], w[i])
            hi[i] = max(hi[i], w[i])
    for poly in ob.data.polygons:
        if not mats:
            continue
        mat = mats[min(poly.material_index, len(mats) - 1)]
        if mat is None:
            continue
        area[mat.name] = area.get(mat.name, 0.0) + poly.area
        b = box.setdefault(mat.name, [[1e18] * 3, [-1e18] * 3])
        for vi in poly.vertices:
            w = mw @ ob.data.vertices[vi].co
            for i in range(3):
                b[0][i] = min(b[0][i], w[i])
                b[1][i] = max(b[1][i], w[i])

span = [hi[i] - lo[i] for i in range(3)]
L = 0 if span[0] >= span[1] else 1        # length is the longer of X/Y; Z is up
mid = (lo[L] + hi[L]) / 2.0
half = max(span[L] / 2.0, 1e-9)


# --- what can actually be SEEN from outside --------------------------------
def visibility_counts():
    """Fire rays at the car from all round; count first-hit material.

    GLAZING BLOCKS THE RAY AND SCORES NOTHING. The first version let rays pass
    through glass and score whatever was behind, on the reasoning that a
    windscreen is genuinely see-through. That was wrong for this purpose: it
    put the CABIN into the exterior tally, and on the Aston it credited
    INT_LEATHER_HARD with 4.8% of the car's outside. What this needs to find is
    the painted SKIN, so the right question is what the silhouette is made of
    with the glass treated as solid. Blocking also makes the measurement robust
    on a car whose names are scrambled, where an interior exclusion cannot be
    trusted either way."""
    import mathutils
    from mathutils.bvhtree import BVHTree

    verts = []
    polys = []
    owner = []
    for ob in bpy.data.objects:
        if ob.type != "MESH" or not ob.data.polygons:
            continue
        mw = ob.matrix_world
        base = len(verts)
        verts.extend([mw @ v.co for v in ob.data.vertices])
        mats = list(ob.data.materials)
        for poly in ob.data.polygons:
            idx = [base + i for i in poly.vertices]
            mat = mats[min(poly.material_index, len(mats) - 1)] if mats else None
            for k in range(1, len(idx) - 1):
                polys.append((idx[0], idx[k], idx[k + 1]))
                owner.append(mat.name if mat else None)
    if not polys:
        return {}
    tree = BVHTree.FromPolygons(verts, polys, all_triangles=True)
    ctr = mathutils.Vector([(lo[i] + hi[i]) / 2.0 for i in range(3)])
    diag = max(span)
    counts = {}
    N = int(os.environ.get("R10_RAY_GRID", "44"))
    import math as _m
    dirs = []
    for az in range(0, 360, 30):
        for el in (-25.0, 5.0, 35.0, 65.0):
            a, e = _m.radians(az), _m.radians(el)
            dirs.append(mathutils.Vector((_m.cos(a) * _m.cos(e),
                                          _m.sin(a) * _m.cos(e),
                                          _m.sin(e))))
    up = mathutils.Vector((0, 0, 1))
    for d in dirs:
        d = d.normalized()
        u = d.cross(up)
        u = (u.normalized() if u.length > 1e-6
             else d.cross(mathutils.Vector((1, 0, 0))).normalized())
        v = d.cross(u).normalized()
        for i in range(N):
            for j in range(N):
                p = (ctr + d * diag
                     + u * ((i / (N - 1) - 0.5) * diag * 1.05)
                     + v * ((j / (N - 1) - 0.5) * diag * 1.05))
                hit = tree.ray_cast(p, -d)
                if hit[0] is None:
                    continue
                nm = owner[hit[2]]
                # glazing blocks and scores nothing: the ray is spent, and the
                # cabin behind it never enters the exterior tally
                if nm and not any(g in nm.lower() for g in GLASSY):
                    counts[nm] = counts.get(nm, 0) + 1
    return counts


VIS = visibility_counts()
TOTAL_VIS = max(sum(VIS.values()), 1)

candidates = []
for name, a in area.items():
    nm = name.lower()
    why = excluded(nm)
    b = box[name]
    end_frac = abs((b[0][L] + b[1][L]) / 2.0 - mid) / half
    len_ext = (b[1][L] - b[0][L]) / max(span[L], 1e-9)
    # A lamp lens is small and sits at one end -- the same geometric test
    # r8_reglaze uses, for the same reason: four rounds of name lists were not
    # enough there and would not be enough here.
    if why is None and end_frac >= 0.72 and len_ext <= 0.18:
        why = "lamp lens (by geometry)"
    # Paint spans the car. A big exterior patch that covers a third of it is a
    # bumper or a sill, not the body.
    if why is None and len_ext < 0.45:
        why = f"covers only {len_ext:.0%} of the car's length"
    vis = VIS.get(name, 0)
    # EVIDENCE OVERRIDES THE NAME. skoda-octavia-w7-v1 is a merged re-export
    # whose material names were reassigned wholesale: its outer skin is called
    # `Int_gauges_rs_A_4` and its body panels `Merged_materials`, so the
    # interior exclusion above rejects the actual paint and hands the job to a
    # 4.7% scrap of trim. With glazing blocking, no genuine interior part can
    # own a third of what you see from outside -- the cabin is not reachable by
    # a ray at all. So a large enough share overrules the name, which is the
    # same principle as the geometric gates in r8_reglaze: where a material sits
    # is evidence, what it is called is a claim.
    if why in ("interior",) and vis >= OVERRIDE_VIS * TOTAL_VIS:
        print(f"R10_NAME_OVERRIDE {name}: named like interior trim, but it is "
              f"{vis / TOTAL_VIS:.0%} of everything visible from outside with the "
              f"glazing solid -- an interior part cannot be. Treating the "
              f"measurement as the truth and the name as mislabelled.")
        why = None
    candidates.append((vis, name, why, end_frac, len_ext, a))

candidates.sort(reverse=True)
print("R10_CANDIDATES (by rays that hit it first, i.e. what you can SEE)")
for vis, name, why, ef, le, a in candidates[:12]:
    print(f"  {vis / TOTAL_VIS:6.1%} {vis:7d}  {name[:30]:30s} "
          f"area={a:8.3f} ext={le:.2f}  "
          f"{'PAINT?' if why is None else 'skip: ' + why}")

paint = next((c for c in candidates if c[2] is None and c[0] > 0), None)
if paint is None:
    raise SystemExit("R10_REFUSED: no material qualifies as body paint -- every "
                     "candidate is glazing, wheel, interior, lamp, too small, or "
                     "never visible from outside. Painting the wrong one is "
                     "worse than not painting.")
PAINT_NAME = paint[1]
print(f"R10_PAINT {PAINT_NAME} -- {paint[0] / TOTAL_VIS:.1%} of everything "
      f"visible from outside, spans {paint[4]:.0%} of the car")

rgb = (tuple(float(x) for x in COLOUR.split(",")) if "," in COLOUR
       else PALETTE.get(COLOUR))
if rgb is None:
    raise SystemExit(f"R10_REFUSED: unknown colour {COLOUR!r}; "
                     f"known: {', '.join(sorted(PALETTE))}")


def bsdf_of(m):
    m.use_nodes = True
    return next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)


rep = {"in": SRC, "out": DST, "colour": COLOUR, "rgb": list(rgb),
       "paint_material": PAINT_NAME, "tyres": []}

m = bpy.data.materials[PAINT_NAME]
b = bsdf_of(m)
if b is None:
    raise SystemExit(f"R10_REFUSED: {PAINT_NAME} has no Principled BSDF")
b.inputs["Base Color"].default_value = (*rgb, 1.0)
b.inputs["Roughness"].default_value = ROUGH
if "Metallic" in b.inputs:
    b.inputs["Metallic"].default_value = METAL
# Clearcoat is what makes paint read as PAINT rather than as plastic. Blender
# 4.x renamed the sockets, so both spellings are tried and the failure is
# printed -- a silently missing clearcoat is the difference between a premium
# finish and a matte one, and it would not raise.
for coat, val in (("Coat Weight", COAT), ("Clearcoat", COAT),
                  ("Coat Roughness", 0.03), ("Clearcoat Roughness", 0.03)):
    if coat in b.inputs:
        b.inputs[coat].default_value = val
        rep.setdefault("coat_sockets", []).append(coat)
if not rep.get("coat_sockets"):
    print("R10_WARN no clearcoat socket found -- paint will read matte")
print(f"R10_MAT {PAINT_NAME}: base -> {[round(x,3) for x in rgb]}, "
      f"rough {ROUGH}, metallic {METAL}, coat {COAT}")

# --- tyres --------------------------------------------------------------
# The owner has ruled twice that tyres must read as black rubber. A tyre
# material is only touched when its name says rubber AND it is not already
# dark, so a correct car is left exactly as it is -- and a WHITEWALL, which
# CLAUDE.md records as a genuine period detail repeatedly misread as a defect,
# keeps its light sidewall because only the material named as rubber is set.
if DO_TYRE:
    for mm in bpy.data.materials:
        nm = (mm.name or "").lower()
        if not any(t in nm for t in TYRE_WORDS):
            continue
        bb = bsdf_of(mm)
        if bb is None:
            continue
        cur = list(bb.inputs["Base Color"].default_value)[:3]
        if max(cur) <= 0.08:
            print(f"R10_TYRE_OK {mm.name}: already {max(cur):.3f} -- left alone")
            rep["tyres"].append({"name": mm.name, "action": "left alone",
                                 "was": [round(c, 4) for c in cur]})
            continue
        bb.inputs["Base Color"].default_value = (0.022, 0.022, 0.024, 1.0)
        bb.inputs["Roughness"].default_value = 0.85
        if "Metallic" in bb.inputs:
            bb.inputs["Metallic"].default_value = 0.0
        print(f"R10_TYRE {mm.name}: {[round(c,3) for c in cur]} -> black rubber")
        rep["tyres"].append({"name": mm.name, "action": "darkened",
                             "was": [round(c, 4) for c in cur]})

# --- GLOBAL-ALPHA SHELL: force the EXTERIOR opaque -------------------------
# CLAUDE.md records this class under the Volvo/Mazda "global-alpha shell": the
# whole car is authored at alphaMode=BLEND alpha 0.25 with
# KHR_materials_transmission=1.0, including carpaint, tyres and chrome, so the
# body itself is ~75% see-through and a backlight render reads a checkerboard
# straight through the roof and bonnet. land-rover-range-rover-velar-v1 was
# quarantined for exactly this and still carries it: `vray_CarPaint` and
# `vray_Material_568` are both BLEND 0.25 / transmission 1.0.
#
# Painting the base material does not repair it -- a transmissive coat sits over
# the paint and the car stays see-through under any rig that puts light behind
# it. So every material that rays actually reach from outside, and that is not
# glazing, is forced fully opaque. Glazing is exempt by name AND by having been
# excluded from the visibility tally, which is what stops this undoing r8.
#
# Nothing is forced on a car that does not have the defect: a correctly authored
# exterior is already opaque and reports zero changes.
shell_fixed = []
for mm in bpy.data.materials:
    nm = (mm.name or "").lower()
    if any(g in nm for g in GLASSY):
        continue
    if VIS.get(mm.name, 0) <= 0:
        continue
    bb = bsdf_of(mm)
    if bb is None:
        continue
    a = float(bb.inputs["Alpha"].default_value)
    t = (float(bb.inputs["Transmission Weight"].default_value)
         if "Transmission Weight" in bb.inputs else 0.0)
    if a >= 0.99 and t <= 0.01:
        continue
    bb.inputs["Alpha"].default_value = 1.0
    if "Transmission Weight" in bb.inputs:
        bb.inputs["Transmission Weight"].default_value = 0.0
    try:
        mm.blend_method = "OPAQUE"
    except Exception:
        pass
    print(f"R10_SHELL {mm.name}: exterior surface was alpha={a:.3f} "
          f"transmission={t:.3f} -- forced opaque (global-alpha shell)")
    shell_fixed.append({"name": mm.name, "alpha": round(a, 4),
                        "transmission": round(t, 4)})
rep["shell_forced_opaque"] = shell_fixed
if shell_fixed:
    print(f"R10_SHELL_TOTAL {len(shell_fixed)} exterior materials were "
          f"see-through and are now solid")

if DO_CABIN:
    rep["cabin"] = []
    for mm in bpy.data.materials:
        nm = (mm.name or "").lower()
        if not (any(i in nm for i in INTERIOR) or affix(nm, "int")):
            continue
        bb = bsdf_of(mm)
        if bb is None:
            continue
        c = list(bb.inputs["Base Color"].default_value)[:3]
        mx, mn = max(c), min(c)
        sat = (mx - mn) / mx if mx > 1e-6 else 0.0
        if sat < 0.45 or mx < 0.25:
            continue
        grey = 0.045 + 0.25 * mx * 0.25
        bb.inputs["Base Color"].default_value = (grey, grey, grey * 1.02, 1.0)
        print(f"R10_CABIN {mm.name}: {[round(x,3) for x in c]} (saturation "
              f"{sat:.2f}) -> neutral {grey:.3f}. A placeholder colour, not upholstery.")
        rep["cabin"].append({"name": mm.name, "was": [round(x, 4) for x in c],
                             "saturation": round(sat, 3)})

bpy.ops.export_scene.gltf(filepath=DST, export_format="GLB", export_yup=True)
print("R10_EXPORTED", DST)
if REPORT:
    json.dump(rep, open(REPORT, "w"), indent=2)
print("R10_DONE")
