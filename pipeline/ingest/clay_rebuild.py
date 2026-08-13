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
RULES = [
    (r"lights?_glass|glass_red|lamp|headlight|taillight", "lamp"),
    (r"glass|window|windscreen|windshield|win_int",        "glass"),
    (r"tire|tyre|rubber",                                  "tyre"),
    (r"rim|alloy|wheel",                                   "rim"),
    (r"chrome",                                            "chrome"),
    (r"brake|caliper",                                     "brake"),
    (r"plate",                                             "plate"),
    (r"interior|seat|dash|leather|fabric|carpet|int\b|_int", "interior"),
    (r"copper",                                            "copper"),
    (r"silver",                                            "silver"),
    (r"black.*(matt|mat)\b|matt",                          "trim_matt"),
    (r"black.*shiny|shiny",                                "trim_gloss"),
    (r"black",                                             "trim_matt"),
    (r"body|carpaint|paint",                               "paint"),
    (r"mirror",                                            "chrome"),
    (r"red",                                               "accent_red"),
]

PBR = {
    "paint":      dict(baseColorFactor=[0.60, 0.61, 0.63, 1.0], metallicFactor=0.10, roughnessFactor=0.35),
    "glass":      dict(baseColorFactor=[0.030, 0.035, 0.045, 0.72], metallicFactor=0.0, roughnessFactor=0.05),
    "lamp":       dict(baseColorFactor=[0.080, 0.080, 0.090, 1.0], metallicFactor=0.0, roughnessFactor=0.08),
    "tyre":       dict(baseColorFactor=[0.028, 0.028, 0.030, 1.0], metallicFactor=0.0, roughnessFactor=0.90),
    "rim":        dict(baseColorFactor=[0.42, 0.43, 0.45, 1.0], metallicFactor=0.85, roughnessFactor=0.35),
    "chrome":     dict(baseColorFactor=[0.65, 0.66, 0.68, 1.0], metallicFactor=1.0, roughnessFactor=0.08),
    "brake":      dict(baseColorFactor=[0.45, 0.03, 0.03, 1.0], metallicFactor=0.2, roughnessFactor=0.40),
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


def rebuild(src, dst, paint_rgb=None):
    raw = open(src, "rb").read()
    if raw[:4] != b"glTF":
        sys.exit("not a GLB")
    ln = struct.unpack("<I", raw[12:16])[0]
    g = json.loads(raw[20:20 + ln])
    rest = raw[20 + ln:]                       # BIN chunk(s), byte-identical

    counts = {}
    for m in g.get("materials", []):
        cls = classify(m.get("name"))
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


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--paint", help="r,g,b for the body paint")
    a = ap.parse_args()
    rgb = tuple(float(x) for x in a.paint.split(",")) if a.paint else None
    rebuild(a.src, a.out, rgb)
