#!/usr/bin/env python3
"""migrate_catalogue.py — v1 (flat make/model) -> v2 (versioned VehicleAsset).

Rules enforced here (docs/asset-quality-policy.md):
  * source titles preserved verbatim
  * only defensible facts extracted: years/generations parsed from the source
    title itself, never invented; anything uncertain is null + flagged
  * spec'd quarantine list applied with reasons
  * mojibake (UTF-8-as-latin1) repaired
  * originals preserved: v1 backed up, v2 written alongside

Usage:
  python3 pipeline/catalogue/migrate_catalogue.py \
      --in backups/catalogue.v1.2026-07-14.json \
      --sizes scratch/audit_cat.json \
      --out platform/catalogue/catalogue.v2.json \
      --report reports/catalogue-migration.json
"""
import argparse, hashlib, json, re, sys, datetime

MOJIBAKE = ["â€”", "â€“", "Â·", "Ã—", "ðŸ", "â†’", "â‰¤", "â€œ", "â€\x9d", "Ã©"]

def repair_utf8(s):
    """Repair classic UTF-8-decoded-as-latin1 mojibake, safely."""
    if not isinstance(s, str) or not any(m in s for m in MOJIBAKE):
        return s
    try:
        fixed = s.encode("latin-1").decode("utf-8")
        return fixed if not any(m in fixed for m in MOJIBAKE) else s
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s

GEN_PATTERNS = [
    (re.compile(r"\bmk\s?(\d+(?:\.\d)?)\b", re.I), lambda m: f"mk{m.group(1)}"),
    (re.compile(r"\b([wcefgj]\d{2,3})\b", re.I), lambda m: m.group(1).lower()),
    (re.compile(r"\b(8[pvy])\b", re.I), lambda m: m.group(1).lower()),
    (re.compile(r"\b(b[5-9])\b", re.I), lambda m: m.group(1).lower()),
    (re.compile(r"\b(t3[23])\b", re.I), lambda m: m.group(1).lower()),
    (re.compile(r"\b(fk8|nd|f56|f82|f90|f01|g30|g20|g60|j1[12]|w17[67]|w20[456]|w222|w463|c118|c253|w213|w166)\b", re.I),
     lambda m: m.group(1).lower()),
]
YEAR_RE = re.compile(r"\b(19[89]\d|20[0-2]\d)\b")
RANGE_RE = re.compile(r"\b(19[89]\d|20[0-2]\d)\s*[-–]\s*(19[89]\d|20[0-2]\d)\b")

BODY_HINTS = {
    "hatchback": ["hatch", "sportback", "5door", "5 door"],
    "estate": ["estate", "touring", "tourer", "avant", "sw ", "combi", "shooting brake"],
    "saloon": ["sedan", "saloon", "gran coupe"],
    "suv": ["suv", "x-trail", "crossover"],
    "coupe": ["coupe", "coupé"],
    "convertible": ["cabrio", "convertible", "roadster", "spyder"],
    "pickup": ["pickup", "pick-up", "double cab", "crew cab"],
    "van": ["van", "transporter", "sprinter", "crafter", "combo", "nv200", "caddy", "expert", "vito"],
    "mpv": ["touran", "zafira", "meriva", "caravelle", "roomster"],
}

COLOUR_TO_FAMILY = {
    "black": "black", "white": "white", "grey": "grey", "gray": "grey",
    "silver": "silver", "blue": "blue", "red": "red", "green": "green",
    "yellow": "yellow", "orange": "orange", "brown": "brown", "beige": "beige",
    "purple": "purple", "gold": "gold", "bronze": "bronze",
    "gunmetal": "grey", "magnetic": "blue", "floret": "silver", "ibis": "silver",
    "pearl": "white", "dolphin": "grey",
}

# spec §26 quarantine / investigate list  (slug -> reason)
QUARANTINE = {
    ("dacia", "logan"): "stub asset: 86 KB",
    ("kia", "ceed"): "stub asset: 147 KB",
    ("mini", "countryman"): "stub asset: 113 KB",
    ("skoda", "octavia"): "stub asset: 61 KB",
    ("suzuki", "jimny"): "stub asset: 44 KB",
    ("land-rover", "discovery-sport"): "source title says 'Crushed' — damaged-car scan",
    ("mercedes-benz", "glb"): "source title '2027 Lite' — concept/unverifiable year",
}
HEAVY_QUARANTINE = {
    ("hyundai", "ioniq"), ("hyundai", "i20"), ("honda", "accord"),
    ("peugeot", "2008"), ("peugeot", "407"), ("kia", "stinger"),
}
INVESTIGATE = {
    ("audi", "a3"): "8P-era mesh — generation set from source, confirm before exact claims",
    ("mercedes-benz", "c-class"): "W204 mesh — generation set from source",
    ("vauxhall", "astra"): "Bertone G 1998-2013 mesh",
    ("mercedes-benz", "g-class"): "1997 W463 mesh",
    ("toyota", "corolla"): "2011 mesh",
    ("ford", "focus"): "source is a saloon; UK Focus is typically hatchback",
    ("land-rover", "defender"): "source is a pickup body style",
    ("volkswagen", "golf"): "mesh generation unconfirmed (source title 2021 GTI, body resembles Mk7.5) — confirm before serving under v2 resolver",
}

def body_from_title(title, model):
    t = (title + " " + model).lower()
    for style, hints in BODY_HINTS.items():
        if any(h in t for h in hints):
            return style
    return None

def migrate_entry(c, sizes):
    make = c["make"]; model = c["model"]
    title = repair_utf8(c.get("source_title") or "")
    key = (make, model)
    trellis = "TRELLIS.2" in title

    gen = None
    for rx, fmt in GEN_PATTERNS:
        m = rx.search(title)
        if m:
            gen = fmt(m); break

    year_start = year_end = None
    mr = RANGE_RE.search(title)
    if mr:
        year_start, year_end = int(mr.group(1)), int(mr.group(2))
    else:
        ys = [int(x) for x in YEAR_RE.findall(title)]
        if len(ys) == 1:
            # single stated year: defensible as "around this year", ±1 window
            year_start, year_end = ys[0] - 1, ys[0] + 1

    kb = sizes.get(f"{make}/{model}")
    status, reason, review = "approved", None, []
    if key in QUARANTINE:
        status, reason = "quarantined", QUARANTINE[key]
    elif key in HEAVY_QUARANTINE:
        status, reason = "quarantined", f"over mobile weight limit ({kb} KB) — optimise then re-approve"
    if key in INVESTIGATE:
        review.append(INVESTIGATE[key])
        if key == ("volkswagen", "golf"):
            status = "needs-review" if status == "approved" else status
    if gen is None: review.append("generation unconfirmed")
    if year_start is None: review.append("year range unknown")

    quality = "B"
    if kb is not None and kb < 300: quality = "C"
    if status == "quarantined" and "stub" in (reason or ""): quality = "rejected"

    colour_label = repair_utf8(c.get("colour_rendered") or "")
    fam = "unknown"
    for k, v in COLOUR_TO_FAMILY.items():
        if k in colour_label.lower():
            fam = v; break

    gen_slug = (gen or "x").replace(".", "")
    yr = f"{year_start}-{year_end}" if year_start else "undated"
    entry = {
        "schemaVersion": 2,
        "assetId": f"{make}-{model}-{gen_slug}-{yr}-v1".replace("--", "-"),
        "make": make, "model": model, "modelFamily": model,
        "modelAliases": [], "generation": gen, "generationAliases": [],
        "generationConfirmed": False,
        "yearStart": year_start, "yearEnd": year_end,
        "bodyStyle": body_from_title(title, model),
        "compatibleFuelTypes": [], "compatibleTrimFamilies": [],
        "exactDerivative": None, "exactTrim": False,
        "provenance": "generated-from-reference" if trellis else "sourced",
        "sourceTitle": title,
        "sourceUrl": None, "sourceCreator": None, "sourceReferenceId": None,
        "sourceRetrievedAt": None, "sourceEvidenceUrl": None,
        "licence": repair_utf8(c.get("licence")) if c.get("licence") else None,
        "generatedFromReference": trellis,
        "referenceImageCount": 1 if trellis else 0,
        "accuracyGrade": "approximate" if trellis else "representative",
        "qualityGrade": quality,
        "technicalStatus": "pending", "visualStatus": "pending",
        "publicationStatus": status, "quarantineReason": reason,
        "hasInterior": False, "interiorMode": "none",
        "hasSeparateDoors": False, "hasSeparateBonnet": False,
        "hasSeparateBoot": False, "supportsOpenableParts": False,
        "paintMaterialNames": [], "glassMaterialNames": [],
        "defaultColourFamily": fam,
        "renderColourLabel": colour_label or None,
        "oemPaintVerified": False, "oemPaintCode": None, "oemPaintName": None,
        "colourVariants": c.get("colour_variants") or {},
        "desktopGlbUrl": c["glb_url"],
        "mobileGlbUrl": c["glb_url"] if (kb is not None and kb <= 3072) else None,
        "fallbackGlbUrl": None,
        "posterUrl": None,
        "turntableUrl": c.get("manifest_url"),
        "interiorUrl": None,
        "fileSizeBytes": kb * 1024 if kb is not None else None,
        "mobileFileSizeBytes": kb * 1024 if (kb is not None and kb <= 3072) else None,
        "triangleCount": None, "vertexCount": None,
        "textureMemoryBytes": None, "maxTextureResolution": None,
        "contentHash": None,
        "pipelineVersion": "migration-2026-07-14",
        "publishedAt": None, "replacedAssetId": None,
        "needsHumanReview": review,
        "notes": [repair_utf8(n) for n in ([c["notes"]] if isinstance(c.get("notes"), str) else c.get("notes", []))]
                 + ([repair_utf8(c["replaced"])] if c.get("replaced") else []),
    }
    return entry

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--sizes", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--report", required=True)
    a = ap.parse_args()

    v1 = json.load(open(a.src, encoding="utf-8"))
    sized = json.load(open(a.sizes, encoding="utf-8"))
    sizes = {f"{c['make']}/{c['model']}": c.get("_kb") for c in sized}

    out, ids = [], set()
    for c in v1:
        e = migrate_entry(c, sizes)
        while e["assetId"] in ids:
            e["assetId"] += "b"
        ids.add(e["assetId"])
        out.append(e)

    json.dump(out, open(a.out, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    rep = {
        "migratedAt": datetime.datetime.utcnow().isoformat() + "Z",
        "total": len(out),
        "approved": sum(1 for e in out if e["publicationStatus"] == "approved"),
        "quarantined": [(e["make"], e["model"], e["quarantineReason"]) for e in out if e["publicationStatus"] == "quarantined"],
        "needsReview": sum(1 for e in out if e["publicationStatus"] == "needs-review"),
        "generationParsed": sum(1 for e in out if e["generation"]),
        "yearParsed": sum(1 for e in out if e["yearStart"]),
        "mojibakeRepaired": sum(1 for c in v1 for v in c.values() if isinstance(v, str) and repair_utf8(v) != v),
    }
    json.dump(rep, open(a.report, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(json.dumps(rep, indent=1, ensure_ascii=False))

if __name__ == "__main__":
    main()
