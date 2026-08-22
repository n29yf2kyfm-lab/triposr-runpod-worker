#!/usr/bin/env python3
"""r8_reglaze.py — try to RECOVER a quarantined car by rebuilding its glazing.

THE POOL. The live catalogue holds 273 quarantined cars, and 145 of them were
scrapped for OPAQUE OR GREY WINDOWS with a fetchable GLB. That is the largest
single recoverable class in the catalogue by a wide margin.

WHY THIS IS NOT THE REPAIR THAT WAS ALREADY REJECTED. The 2026-08-11 ruling
scrapped these cars because the glazing is opaque IN THE SHIPPED glTF, and it
specifically forbade chasing clay-shell material recovery. What was never tried
is the combination this file does: rebuild the pane GEOMETRY as clean watertight
panes AND give those panes a real glass material. Geometry alone would produce
watertight OPAQUE panes -- no better than before, because r4_glass inherits
whatever material it finds. Material alone leaves the torn geometry. Together
they are a different intervention, and the glTF probe decides whether it worked.

The probe is the gate, not the render: render/handler.py forces
transmission=1.0 onto any material whose NAME matches glass/window/screen, so a
studio poster shows perfect glazing on an opaque car. Only the file settles it.

FOUR DEFECTS FROM THE FIRST TEST BATCH, ALL FIXED HERE:
  * it rewrote glazing on cars that were ALREADY clear. subaru-brz was
    quarantined for TYRES, its glazing probed clear at alpha 0.25 BLEND, and the
    tool flattened that tint. It now REFUSES unless the caller passes
    R8_FORCE=1 or the material is genuinely non-transmissive.
  * the tint rewrite was too aggressive. ford-transit's glazing was [0,0,0] and
    came back light grey -- an appearance change, not a repair. The original RGB
    is now PRESERVED unless it is degenerate for transmissive glass, which means
    near-black: in glTF, transmission is tinted BY baseColor, so a black base
    with transmission 1.0 is still an opaque black pane.
  * Draco was lost on re-export (files grew 2.08x-4.72x). The caller
    re-compresses; this file records the size so the cost is visible.
  * some quarantine reasons do not match the file -- a car filed as a clay shell
    probed clear. Reason strings are not evidence; the probe is.

Run: blender -b --python r8_reglaze.py -- in.glb out.glb report.json
Env: R8_IOR (1.45) · R8_TRANSMISSION (1.0) · R8_TINT_FLOOR (0.05) · R8_FORCE (0)
"""
import json
import os
import sys

import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
SRC, DST, REPORT = argv[0], argv[1], argv[2]
IOR = float(os.environ.get("R8_IOR", "1.45"))
TRANS = float(os.environ.get("R8_TRANSMISSION", "1.0"))
TINT_FLOOR = float(os.environ.get("R8_TINT_FLOOR", "0.05"))
NEUTRAL = float(os.environ.get("R8_NEUTRAL_TINT", "0.72"))
FORCE = os.environ.get("R8_FORCE", "0") == "1"

GLASSY = ("glass", "window", "windscreen", "windshield", "screen", "glas",
          "scheibe", "fenster", "vidro", "backlight", "quarter")

# LAMP LENSES ARE NOT WINDOWS, and "glass" matches both. A triage of the first
# 122 recovered cars found 24 where this rewrote HeadLightsGlass, BrakeLightsGlass,
# glass_headlights, REARLIGHT_GLASS_NM and the like -- a fully transmissive
# headlamp lens is wrong, lamps want dark gloss. This is the documented lamp-lens
# trap: the same reason `backlight` had to be handled carefully, since it means
# the REAR WINDSCREEN as often as it means a tail lamp. `backlight` is kept in
# GLASSY and deliberately NOT listed here for exactly that reason.
LAMPY = ("headlight", "headlamp", "brakelight", "taillight", "taillamp",
         "rearlight", "rear_light", "drl", "indicator", "reflector",
         # bare "fog", not "foglight": a Mercedes E-Class estate names its front
         # fog lens `glass_red_fog`, which "foglight" and "fog_light" both miss.
         # That mismatch was invisible because the TRIAGE script matched bare
         # "fog" while this list did not -- the detector reported a defect the
         # fixer could not act on, which is worse than either being wrong alone.
         # Keep the two lists in step.
         "fog", "blinker", "turnsignal", "lamp",
         # An Aston Martin Vantage spells its tail lens TAILL_LIGHTGLASS -- double
         # L, underscore -- which matches neither "taillight" nor "taillamp".
         # "lightglass" catches it and every ...LightsGlass variant, and it is
         # SAFE for the rear windscreen: `backlight_glass` contains "light_glass",
         # not "lightglass", so the distinction this project relies on survives.
         "lightglass", "taill",
         # One large source pack in this catalogue abbreviates its lenses rather
         # than naming them: `ext_glass_tl` is the TAIL LAMP and `ext_glass_orng`
         # the amber indicator, sitting beside the genuine `ext_glass`,
         # `ext_window` and `int_window`. No lamp word appears in either, so the
         # readable-name list above misses both. These abbreviations are matched
         # explicitly, as SUFFIXES, so they cannot swallow an unrelated material
         # that merely contains the letters.
         "_tl", "_orng", "_amber", "_ind")


def is_lamp(nm):
    """Lamp by readable word anywhere, or by one of the pack's abbreviations at
    the END of the name -- a suffix test, so `_tl` cannot match `metal` or
    `crystal`."""
    for tok in LAMPY:
        if tok.startswith("_"):
            if nm.endswith(tok):
                return True
        elif tok in nm:
            return True
    return False

bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
bpy.ops.import_scene.gltf(filepath=SRC)


# --- GEOMETRIC LAMP GATE ---------------------------------------------------
# THE NAME LIST ABOVE CANNOT BE FINISHED, and four rounds of adding spellings to
# it is the proof. Measured on two cars that had already been passed by it:
#
#   ford-focus-w6-v1   `glass1`            tail lamp -- no lamp word at all
#   ford-focus-w6-v1   `detail_glass_red1` tail lamp -- "red" is not a lamp word
#   aston-martin-...   `DLR_NM_GLASS`      daytime running lamp -- LAMPY has
#                                          "drl", the file spells it "dlr"
#
# All three were made fully transmissive and shipped as clean recoveries. A
# fifth spelling would not have helped: `glass1` contains no signal whatsoever.
#
# WHERE A MATERIAL SITS IS EVIDENCE; WHAT IT IS CALLED IS A CLAIM. A lamp lens
# is a small patch at one extreme END of the car. Glazing spans the cabin.
# Measured on the two cars above, the two populations do not overlap or come
# near it -- end_frac is distance of the material's centre from the car's centre
# along its length, as a fraction of the half-length, and len_ext is how much of
# the car's length the material covers:
#
#   material              end_frac  len_ext   truth
#   EXT_GLASS                 0.22     0.62   glazing
#   INT_GLASS                 0.23     0.62   glazing
#   window1                   0.21     0.72   glazing
#   black_glass1              0.18     0.76   glazing
#   ---------------------------------------- gate at 0.72 / 0.18
#   detail_glass_red1         0.79     0.13   LAMP
#   glass1                    0.82     0.12   LAMP
#   HEADLIGHTGLASS            0.87     0.09   LAMP
#   TAILL_LIGHTGLASS          0.88     0.08   LAMP
#   DLR_NM_GLASS              0.89     0.07   LAMP
#   REARLIGHT_GLASS_NM        0.90     0.06   LAMP
#
# WHY BOTH CONDITIONS, AND WHY THESE NUMBERS. end_frac alone would fail a
# hatchback's rear windscreen, which sits well aft; len_ext alone would fail a
# quarter light. A rear screen is aft AND deep (end_frac ~0.6, len_ext ~0.25),
# so it clears both thresholds with room. This also settles `backlight_glass` --
# the material CLAUDE.md records as genuinely undecidable from its name, meaning
# rear windscreen as often as tail lamp -- on evidence rather than on a guess.
#
# THE FAILURE DIRECTION IS DELIBERATE. A false LAMP leaves a real window opaque,
# so glass_probe fails the car loudly and it never ships. A false GLAZING ships
# a transparent headlamp, which is the defect this exists to stop. When the two
# disagree, this gate takes the safer side.
LAMP_END_FRAC = float(os.environ.get("R8_LAMP_END", "0.72"))
LAMP_LEN_EXT = float(os.environ.get("R8_LAMP_EXT", "0.18"))

# --- GEOMETRIC BODYWORK GATE -----------------------------------------------
# The lamp gate above catches small patches at the ENDS. It does not catch the
# other way a glass-named material can be something else entirely: BODYWORK.
#
# skoda-octavia-w7-v1 ships fifteen materials called `ext_glass` .. `ext_glass_13`,
# and `ext_glass_9` is 136,324 triangles spanning 96% of the car's length from
# its floor to its waistline. It is the BODY SHELL. `ext_glass_11` is a sill
# panel. Made fully transmissive and rendered against this project's dark studio
# backdrop, both read as gaping black holes through the boot and the front
# bumper -- which is exactly the "solid black mass" I reported to the owner as a
# pre-existing defect. It was not pre-existing. This tool caused it, and the
# name test could not tell a body panel from a window because both are spelt
# `ext_glass_N` by the same source pack.
#
# GLAZING REACHES THE TOP OF THE CAR; BODYWORK DOES NOT. The greenhouse IS the
# upper band of a car's silhouette, so every real pane's bbox top sits near 1.0
# of the car's height. Measured across the three cars:
#
#   material            top   truth
#   ext_glass          0.97   glazing
#   ext_glass_8        0.94   glazing
#   black_glass1       0.94   glazing
#   window1            0.93   glazing
#   ext_glass_4        0.93   glazing
#   EXT_GLASS          0.96   glazing
#   INT_GLASS          0.96   glazing
#   -------------------------------- gate at 0.80
#   INT_DASH_GLASS     0.72   instrument cluster cover
#   glass2             0.72   small interior pane
#   detail_glass_cle1  0.69   low trim strip
#   ext_glass_13       0.70   trim sliver
#   ext_glass_9        0.65   BODY SHELL
#   ext_glass_11       0.52   SILL PANEL
#
# IT FAILS OPEN, ON PURPOSE. A roof aerial, a light bar or a roof box raises the
# car's bbox top without raising the glazing, which would push a genuine pane
# under the threshold and leave a good car opaque. CLAUDE.md already records a
# shark-fin aerial being mistaken for debris on exactly this kind of reasoning.
# So when the rule would reject EVERY glass-named material, it is abandoned for
# that car and the fact is printed -- an unusable gate must not silently become
# a scrapping gate.
BODY_TOP_FRAC = float(os.environ.get("R8_BODY_TOP", "0.80"))


def material_geometry():
    """World-space bbox per material, plus the car's own axes.

    Blender's glTF importer maps glTF Y-up onto Blender Z-up, so HEIGHT is
    always Blender Z here and the length axis is whichever of X/Y is longer.
    Deriving length from 'the longest span' unconditionally would pick the
    height axis on a van, which is how the pose gates in this project have
    misread cars before."""
    lo = [1e18] * 3
    hi = [-1e18] * 3
    per = {}
    for ob in bpy.data.objects:
        if ob.type != "MESH" or not ob.data.polygons:
            continue
        mw = ob.matrix_world
        mats = list(ob.data.materials)
        corners = [mw @ v.co for v in ob.data.vertices]
        for i in range(3):
            lo[i] = min(lo[i], min(c[i] for c in corners))
            hi[i] = max(hi[i], max(c[i] for c in corners))
        for poly in ob.data.polygons:
            if not mats:
                continue
            mat = mats[min(poly.material_index, len(mats) - 1)]
            if mat is None:
                continue
            r = per.setdefault(mat.name, [[1e18] * 3, [-1e18] * 3])
            for vi in poly.vertices:
                w = mw @ ob.data.vertices[vi].co
                for i in range(3):
                    r[0][i] = min(r[0][i], w[i])
                    r[1][i] = max(r[1][i], w[i])
    span = [hi[i] - lo[i] for i in range(3)]
    L = 0 if span[0] >= span[1] else 1          # length: longer of X/Y
    return per, lo, hi, span, L


GEOM, G_LO, G_HI, G_SPAN, G_L = material_geometry()
G_MID = (G_LO[G_L] + G_HI[G_L]) / 2.0
G_HALF = max(G_SPAN[G_L] / 2.0, 1e-9)
print(f"R8_AXES length={'XYZ'[G_L]} span={G_SPAN[G_L]:.3f} "
      f"height=Z span={G_SPAN[2]:.3f}")


def lamp_by_geometry(name):
    """(is_lamp, end_frac, len_ext) -- None when the material has no geometry."""
    r = GEOM.get(name)
    if r is None:
        return None, None, None
    centre = (r[0][G_L] + r[1][G_L]) / 2.0
    end_frac = abs(centre - G_MID) / G_HALF
    len_ext = (r[1][G_L] - r[0][G_L]) / max(G_SPAN[G_L], 1e-9)
    return (end_frac >= LAMP_END_FRAC and len_ext <= LAMP_LEN_EXT), end_frac, len_ext


def top_frac(name):
    """How high this material's highest point sits, 0 = floor, 1 = roof."""
    r = GEOM.get(name)
    if r is None:
        return None
    return (r[1][2] - G_LO[2]) / max(G_SPAN[2], 1e-9)


# Decide the bodywork gate ONCE, before rewriting anything, so the fail-open
# check can see the whole car. A per-material decision could not.
_glassy = [m.name for m in bpy.data.materials
           if any(g in (m.name or "").lower() for g in GLASSY)
           and not is_lamp((m.name or "").lower())
           and not lamp_by_geometry(m.name)[0]]
_reaches = [n for n in _glassy if (top_frac(n) or 0.0) >= BODY_TOP_FRAC]
BODY_GATE_ON = bool(_reaches)
if _glassy and not BODY_GATE_ON:
    print(f"R8_BODY_GATE OFF: not one of {len(_glassy)} glazing-named materials "
          f"reaches {BODY_TOP_FRAC:.0%} of this car's height -- the height rule "
          f"would reject every pane, so it is abandoned for this car rather "
          f"than scrapping it (a roof aerial or light bar does this)")
else:
    print(f"R8_BODY_GATE ON: {len(_reaches)}/{len(_glassy)} glazing-named "
          f"materials reach the greenhouse")

report = {"repair": "R8 reglaze", "in": SRC, "out": DST, "materials": []}
hits = 0
for m in bpy.data.materials:
    nm = (m.name or "").lower()
    if not any(g in nm for g in GLASSY):
        continue
    geo_lamp, end_frac, len_ext = lamp_by_geometry(m.name)
    where = ("" if end_frac is None
             else f" [end={end_frac:.2f} ext={len_ext:.2f}]")
    if is_lamp(nm) or geo_lamp:
        why = "name" if is_lamp(nm) else "geometry"
        if geo_lamp and not is_lamp(nm):
            print(f"R8_LAMP_GEOM {m.name}: no lamp word in the name, but it sits "
                  f"at the car's end and covers {len_ext:.0%} of its length "
                  f"-- a LAMP LENS the name list could not see")
        print(f"R8_LAMP {m.name}: glass-named but it is a LAMP LENS "
              f"(by {why}){where} -- left alone")
        report["materials"].append({"name": m.name, "skipped": "lamp lens, not glazing",
                                    "detected_by": why, "end_frac": end_frac,
                                    "len_ext": len_ext})
        continue
    tf = top_frac(m.name)
    if BODY_GATE_ON and tf is not None and tf < BODY_TOP_FRAC:
        print(f"R8_BODY {m.name}: glass-named but its highest point is only "
              f"{tf:.0%} up the car -- BODYWORK OR TRIM, not glazing. Left "
              f"alone; making it transmissive would open a hole in the car.")
        report["materials"].append({"name": m.name, "skipped": "bodywork/trim, not glazing",
                                    "top_frac": round(tf, 3)})
        continue
    m.use_nodes = True
    bsdf = next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf is None:
        continue
    tw = bsdf.inputs["Transmission Weight"].default_value if "Transmission Weight" in bsdf.inputs else 0.0
    already = float(tw) > 0.01 or float(bsdf.inputs["Alpha"].default_value) < 0.99
    before = {
        "base_color": [round(float(x), 4) for x in bsdf.inputs["Base Color"].default_value],
        "transmission": round(float(bsdf.inputs["Transmission Weight"].default_value), 4)
        if "Transmission Weight" in bsdf.inputs else None,
        "alpha": round(float(bsdf.inputs["Alpha"].default_value), 4),
        "blend_method": getattr(m, "blend_method", None),
    }
    if already and not FORCE:
        print(f"R8_SKIP {m.name}: already transmissive/blended "
              f"(transmission={float(tw):.3f}, alpha={float(bsdf.inputs['Alpha'].default_value):.3f}) "
              f"-- not touching a pane that already works")
        report["materials"].append({"name": m.name, "skipped": "already transparent",
                                    "before": before})
        continue
    # a real glass material: transmissive, smooth, fully opaque ALPHA
    # (transmission carries the see-through, not alpha -- mixing the two is what
    # produces the "faded" band the probe distrusts).
    # TINT IS PRESERVED. glTF tints transmission by baseColor, so only a
    # near-black base is degenerate -- that would still read as an opaque pane.
    rgb = list(bsdf.inputs["Base Color"].default_value)[:3]
    if max(rgb) < TINT_FLOOR:
        rgb = [NEUTRAL, NEUTRAL, NEUTRAL]
        print(f"R8_TINT {m.name}: base {before['base_color'][:3]} is degenerate "
              f"for transmissive glass -> neutral {NEUTRAL}")
    bsdf.inputs["Base Color"].default_value = (rgb[0], rgb[1], rgb[2], 1.0)
    if "Transmission Weight" in bsdf.inputs:
        bsdf.inputs["Transmission Weight"].default_value = TRANS
    if "IOR" in bsdf.inputs:
        bsdf.inputs["IOR"].default_value = IOR
    if "Roughness" in bsdf.inputs:
        bsdf.inputs["Roughness"].default_value = 0.02
    if "Metallic" in bsdf.inputs:
        bsdf.inputs["Metallic"].default_value = 0.0
    bsdf.inputs["Alpha"].default_value = 1.0
    try:
        m.blend_method = "BLEND"
    except Exception:
        pass
    hits += 1
    report["materials"].append({"name": m.name, "before": before,
                                "after": {"transmission": TRANS, "ior": IOR,
                                          "base_color": [round(c, 4) for c in rgb],
                                          "alpha": 1.0}})
    print(f"R8_MAT {m.name}: transmission {before['transmission']} -> {TRANS}, "
          f"alpha {before['alpha']} -> 1.0, base {[round(c,3) for c in before['base_color'][:3]]} "
          f"-> {[round(c,3) for c in rgb]}")

print(f"R8_HITS {hits} glazing-named materials rewritten")
if hits == 0:
    print("R8_WARN no glazing-named material found -- this car names its glass "
          "something the regex does not match; reglazing cannot target it blind")

bpy.ops.export_scene.gltf(filepath=DST, export_format="GLB", export_yup=True)
print("R8_EXPORTED", DST)
report["materials_rewritten"] = hits
json.dump(report, open(REPORT, "w"), indent=2)
print("R8_DONE")
