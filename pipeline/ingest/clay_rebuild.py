#!/usr/bin/env python3
"""clay_rebuild.py — rebuild materials on a Sketchfab converter-clay GLB.

Owner experiment 2026-08-13. The converter-clay defect (see CLAUDE.md: the
0.588/0.800 flat shells are Sketchfab's converter, not our pipeline) flattens
every baseColorFactor to ONE value but KEEPS the material names and their
binding to the right geometry: the Juke 2023 ships body/glass/d_glass/
tire_mat4/chrome/interior as 20 separate correctly-bound materials, all
0.588 grey.

That makes it the EASY case, unlike the generated cars: no segmentation, no
label transfer, no PartCrafter — classify each material BY NAME and write
proper PBR values back. Pure glTF JSON edit; the mesh bytes are untouched
(BIN chunk copied verbatim), so geometry cannot be damaged by construction.

The value scheme is the proven golf 4+1 set extended with trim classes.
Glass gets alpha BLEND 0.72 like Glass_Tint, so glass_probe reads a real
transparent material and the owner's opaque-glazing ruling is satisfied by
the FILE, not by the render worker's name-forgery.

This deliberately does NOT touch the 64 scrapped live cars (owner ruling
2026-08-11 stands: those are re-source, not repair). It exists for FRESH
candidates whose mesh the owner judges worth keeping.

Usage:
  clay_rebuild.py --in juke.glb --out juke_rebuilt.glb [--paint 0.60,0.61,0.63]
"""
import argparse
import json
import re
import struct
import sys

# (regex, class) — FIRST match wins, so order is specificity.
# paint comes BEFORE interior: the first Astra run classed BOTH `carpaint`
# materials as interior because `int\b` matches the tail of "carpa-int" —
# the body would have rendered cabin-black. The interior rule now requires
# `int` as its own token (start/underscore-delimited), which still catches
# plasticblack_int_ao / black_int / intD but can never eat a *aint name.
RULES = [
    # LAMPS BEFORE GLASS, and matched without requiring an underscore: the
    # Mondeo names its rear lamps `BrakeLightsGlass`, which the old
    # `lights?_glass` missed and the glass rule then caught — brake lights
    # rendered as clear window glass. Also catches DRLs and *_light_*.
    (r"lights?_?glass|glass_red|lamp|headlight|taillight|rear_?light|\bdrls?\b|fog_?light", "lamp"),
    (r"glass|window|windscreen|windshield|\bwin(_|\b)",    "glass"),
    (r"body|carpaint|paint",                               "paint"),
    (r"tire|tyre|rubber",                                  "tyre"),
    # chrome BEFORE rim, and rim must not fire inside "t-rim-s": the Mondeo's
    # `ChromeTrims` was classed rim (alloy metal) off the substring.
    (r"chrome|mirror",                                     "chrome"),
    (r"\brim|alloy|wheel(?!.*arch)",                       "rim"),
    # rotors/discs are bare metal; only the CALIPER is painted red, and
    # colouring both made the wheels glow red through the spokes.
    (r"rotor|brakedisc|brake_?disk|disc_?brake",           "rotor"),
    (r"brake|caliper",                                     "brake"),
    (r"grille|grill\b|mesh_?front",                        "trim_matt"),
    (r"undercarriage|undercarrier|underbody|floorpan",     "trim_matt"),
    (r"plate",                                             "plate"),
    (r"interior|seat|dash|leather|fabric|carpet|(^|_)int($|[a-z_])", "interior"),
    (r"copper",                                            "copper"),
    (r"silver",                                            "silver"),
    (r"black.*(matt|mat)\b|matt",                          "trim_matt"),
    (r"black.*shiny|shiny",                                "trim_gloss"),
    (r"black",                                             "trim_matt"),
    (r"red",                                               "accent_red"),
    # Second pass, added from the Astra 2022's 15 unmapped names. Everything
    # here was rendering neutral dark trim, which read wrong on the bumper
    # insert and roof. Grouped by what the part physically is, not by guess:
    (r"roof",                                              "paint"),        # ROOF_AO is body panel
    (r"wiper|suspension|clutch|chassis|engine|exhaust",    "trim_matt"),    # under-car / hardware
    (r"leds?_|led\b|charge_tex|rpm_tex|speed_tex|gauge|instrument", "interior"),  # dials, charge port UI
    (r"reflect|texpattern|plasticglossy",                  "trim_gloss"),   # gloss black trim
    # Third pass, from the Elantra N 2024's unmapped names. Lamp FUNCTIONS
    # are named by what they do, not by the word "lamp": daylight running
    # lights, reverse lights, stop lights and emissive badge glows are all
    # lit elements, and were rendering as dark trim on the lamp clusters.
    (r"daylight|drl|emissive|emmisive|\bstop\b|\brevers",   "lamp"),
    (r"stitch|android_auto|carplay|screen|infotain",        "interior"),
]

PBR = {
    "paint":      dict(baseColorFactor=[0.60, 0.61, 0.63, 1.0], metallicFactor=0.10, roughnessFactor=0.35),
    "glass":      dict(baseColorFactor=[0.030, 0.035, 0.045, 0.72], metallicFactor=0.0, roughnessFactor=0.05),
    "lamp":       dict(baseColorFactor=[0.080, 0.080, 0.090, 1.0], metallicFactor=0.0, roughnessFactor=0.08),
    "tyre":       dict(baseColorFactor=[0.028, 0.028, 0.030, 1.0], metallicFactor=0.0, roughnessFactor=0.90),
    "rim":        dict(baseColorFactor=[0.42, 0.43, 0.45, 1.0], metallicFactor=0.85, roughnessFactor=0.35),
    "chrome":     dict(baseColorFactor=[0.65, 0.66, 0.68, 1.0], metallicFactor=1.0, roughnessFactor=0.08),
    "brake":      dict(baseColorFactor=[0.45, 0.03, 0.03, 1.0], metallicFactor=0.2, roughnessFactor=0.40),
    "rotor":      dict(baseColorFactor=[0.30, 0.30, 0.32, 1.0], metallicFactor=0.75, roughnessFactor=0.55),
    "plate":      dict(baseColorFactor=[0.90, 0.90, 0.90, 1.0], metallicFactor=0.0, roughnessFactor=0.50),
    "interior":   dict(baseColorFactor=[0.045, 0.045, 0.050, 1.0], metallicFactor=0.0, roughnessFactor=0.90),
    "copper":     dict(baseColorFactor=[0.72, 0.45, 0.28, 1.0], metallicFactor=1.0, roughnessFactor=0.30),
    "silver":     dict(baseColorFactor=[0.55, 0.56, 0.58, 1.0], metallicFactor=0.70, roughnessFactor=0.40),
    "trim_matt":  dict(baseColorFactor=[0.035, 0.035, 0.038, 1.0], metallicFactor=0.0, roughnessFactor=0.85),
    "trim_gloss": dict(baseColorFactor=[0.020, 0.020, 0.022, 1.0], metallicFactor=0.0, roughnessFactor=0.15),
    "accent_red": dict(baseColorFactor=[0.45, 0.03, 0.03, 1.0], metallicFactor=0.2, roughnessFactor=0.40),
    # unmatched names: neutral dark trim, visibly distinct from paint so a
    # misclassification shows in the audit render instead of hiding
    "unknown":    dict(baseColorFactor=[0.12, 0.12, 0.13, 1.0], metallicFactor=0.0, roughnessFactor=0.70),
}


def classify(name):
    n = (name or "").lower()
    for rx, cls in RULES:
        if re.search(rx, n):
            return cls
    return "unknown"


def rebuild(src, dst, paint_rgb=None, paint_name=None):
    raw = open(src, "rb").read()
    if raw[:4] != b"glTF":
        sys.exit("not a GLB")
    ln = struct.unpack("<I", raw[12:16])[0]
    g = json.loads(raw[20:20 + ln])
    rest = raw[20 + ln:]                       # BIN chunk(s), byte-identical

    counts = {}
    for m in g.get("materials", []):
        cls = classify(m.get("name"))
        # Paint is often a COLOUR NAME no regex can know (the Mondeo's
        # body material is literally "Frozen_White", Ford's paint name,
        # and it was rendering as dark trim). --paint-name lets the
        # operator name it after reading the mapping table, which is
        # exactly what that table is printed for.
        if paint_name and paint_name.lower() in str(m.get("name", "")).lower():
            cls = "paint"
        counts[cls] = counts.get(cls, 0) + 1
        vals = dict(PBR[cls])
        if cls == "paint" and paint_rgb:
            vals["baseColorFactor"] = list(paint_rgb) + [1.0]
        pbr = m.setdefault("pbrMetallicRoughness", {})
        # textured materials keep their texture; only factors are corrected
        pbr["baseColorFactor"] = vals["baseColorFactor"]
        pbr["metallicFactor"] = vals["metallicFactor"]
        pbr["roughnessFactor"] = vals["roughnessFactor"]
        if cls == "glass":
            m["alphaMode"] = "BLEND"
            m["doubleSided"] = True
        print(f"  {str(m.get('name'))[:28]:28s} -> {cls}")

    body = json.dumps(g, separators=(",", ":")).encode()
    pad = (4 - len(body) % 4) % 4
    body += b" " * pad
    total = 12 + 8 + len(body) + len(rest)
    out = (b"glTF" + struct.pack("<II", 2, total)
           + struct.pack("<I", len(body)) + b"JSON" + body + rest)
    open(dst, "wb").write(out)
    print(f"classes: {counts}")
    print(f"WROTE {dst} ({len(out)/1e6:.1f}MB)")


def glaze_fix(src, dst):
    """SURGICAL glazing repair: make opaque-but-GLASS-NAMED materials transparent.

    The narrow case the full rebuild is too big a hammer for: a car whose
    materials are otherwise real (colours, textures — NOT a converter clay) but
    whose glazing ships opaque. Under the owner ruling that is a hard fail, yet
    when the material is NAMED like glass the fix is one field. First seen on
    the Sketchfab Mk3 Yaris (`am5eunew1_glass`, glass_probe opaque/proven).

    Touches ONLY materials whose name matches the glass rule AND which are
    currently opaque; sets the proven Glass_Tint values (alpha 0.72 BLEND,
    doubleSided). Everything else — paint, textures, tyres — is byte-identical
    JSON fields, and the BIN chunk is copied verbatim as always. Refuses to
    write when NOTHING matched: a no-op "fix" reading as success is the
    documented respray trap.
    """
    raw = open(src, "rb").read()
    if raw[:4] != b"glTF":
        sys.exit("not a GLB")
    ln = struct.unpack("<I", raw[12:16])[0]
    g = json.loads(raw[20:20 + ln])
    rest = raw[20 + ln:]

    fixed = []
    for m in g.get("materials", []):
        if classify(m.get("name")) != "glass":
            continue
        pbr = m.setdefault("pbrMetallicRoughness", {})
        bcf = pbr.get("baseColorFactor") or [1, 1, 1, 1]
        alpha = bcf[3] if len(bcf) > 3 else 1.0
        if m.get("alphaMode") in ("BLEND", "MASK") and alpha < 0.99:
            continue                       # already transparent — leave it
        vals = dict(PBR["glass"])
        pbr["baseColorFactor"] = vals["baseColorFactor"]
        pbr["metallicFactor"] = vals["metallicFactor"]
        pbr["roughnessFactor"] = vals["roughnessFactor"]
        m["alphaMode"] = "BLEND"
        m["doubleSided"] = True
        fixed.append(m.get("name"))
        print(f"  glaze_fix: {str(m.get('name'))[:40]} -> alpha {vals['baseColorFactor'][3]} BLEND")
    if not fixed:
        sys.exit("glaze_fix: NO opaque glass-named material found — nothing to fix, refusing to write")

    body = json.dumps(g, separators=(",", ":")).encode()
    body += b" " * ((4 - len(body) % 4) % 4)
    total = 12 + 8 + len(body) + len(rest)
    out = (b"glTF" + struct.pack("<II", 2, total)
           + struct.pack("<I", len(body)) + b"JSON" + body + rest)
    open(dst, "wb").write(out)
    print(f"WROTE {dst} ({len(out)/1e6:.1f}MB), fixed: {fixed}")
    return fixed


def rebuild_from_map(src, dst, class_map):
    """Write PBR values from an EXPLICIT {material_name: class} map.

    Used by clay_geoclass, which names materials from the geometry they are
    bound to rather than from their strings — the only way to recover a car
    whose exporter wrote `1129_0`. Same guarantees as rebuild(): glTF JSON
    only, BIN chunk copied verbatim, glass gets real BLEND alpha.
    """
    raw = open(src, "rb").read()
    if raw[:4] != b"glTF":
        sys.exit("not a GLB")
    ln = struct.unpack("<I", raw[12:16])[0]
    g = json.loads(raw[20:20 + ln])
    rest = raw[20 + ln:]
    for m in g.get("materials", []):
        cls = class_map.get(m.get("name") or "(unnamed)", "trim_matt")
        vals = PBR.get(cls, PBR["unknown"])
        pbr = m.setdefault("pbrMetallicRoughness", {})
        pbr["baseColorFactor"] = vals["baseColorFactor"]
        pbr["metallicFactor"] = vals["metallicFactor"]
        pbr["roughnessFactor"] = vals["roughnessFactor"]
        if cls == "glass":
            m["alphaMode"] = "BLEND"
            m["doubleSided"] = True
        elif m.get("alphaMode") == "BLEND":
            m["alphaMode"] = "OPAQUE"          # clay files sometimes ship BLEND
    body = json.dumps(g, separators=(",", ":")).encode()
    body += b" " * ((4 - len(body) % 4) % 4)
    out = (b"glTF" + struct.pack("<II", 2, 12 + 8 + len(body) + len(rest))
           + struct.pack("<I", len(body)) + b"JSON" + body + rest)
    open(dst, "wb").write(out)
    return dst


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--paint", help="r,g,b for the body paint")
    ap.add_argument("--paint-name", help="substring of the material that IS the body paint (for colour-named materials like Frozen_White that no regex can infer)")
    ap.add_argument("--glaze-only", action="store_true",
                    help="surgical mode: ONLY make opaque glass-NAMED materials "
                         "transparent (alpha 0.72 BLEND); everything else "
                         "untouched. For real-material cars that fail solely on "
                         "opaque glazing.")
    a = ap.parse_args()
    if a.glaze_only:
        glaze_fix(a.src, a.out)
        sys.exit(0)
    rgb = tuple(float(x) for x in a.paint.split(",")) if a.paint else None
    rebuild(a.src, a.out, rgb, a.paint_name)
