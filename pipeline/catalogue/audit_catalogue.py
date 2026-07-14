#!/usr/bin/env python3
"""audit_catalogue.py — validate a v2 catalogue against the JSON schema and
policy checks. Exit code 1 on any error. Writes reports/catalogue-audit.json.

  python3 pipeline/catalogue/audit_catalogue.py --in platform/catalogue/catalogue.v2.json
"""
import argparse, json, re, sys, collections, datetime

MOJIBAKE = ["â€”", "â€“", "Â·", "Ã—", "ðŸ", "â†’", "â‰¤"]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--schema", default="schemas/vehicle-asset.schema.json")
    ap.add_argument("--report", default="reports/catalogue-audit.json")
    a = ap.parse_args()

    try:
        import jsonschema
    except ImportError:
        print("jsonschema not installed: pip install jsonschema", file=sys.stderr)
        sys.exit(2)

    cat = json.load(open(a.src, encoding="utf-8"))
    schema = json.load(open(a.schema, encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)

    errors, warnings = [], []
    ids = collections.Counter(e.get("assetId") for e in cat)

    for i, e in enumerate(cat):
        tag = f"[{i}] {e.get('make')}/{e.get('model')}"
        for err in validator.iter_errors(e):
            errors.append(f"{tag}: schema: {err.message[:140]}")
        if ids[e.get("assetId")] > 1:
            errors.append(f"{tag}: duplicate assetId {e.get('assetId')}")
        if not e.get("sourceTitle"):
            errors.append(f"{tag}: missing sourceTitle")
        for field in ("sourceTitle", "renderColourLabel", "quarantineReason"):
            v = e.get(field)
            if isinstance(v, str) and any(m in v for m in MOJIBAKE):
                errors.append(f"{tag}: mojibake in {field}: {v[:60]!r}")
        ys, ye = e.get("yearStart"), e.get("yearEnd")
        if ys and ye and ye < ys:
            errors.append(f"{tag}: yearEnd < yearStart")
        if e.get("publicationStatus") == "approved":
            if e.get("qualityGrade") == "rejected":
                errors.append(f"{tag}: approved but qualityGrade=rejected")
            if not e.get("desktopGlbUrl", "").startswith("https://"):
                errors.append(f"{tag}: approved without https GLB URL")
            if e.get("supportsOpenableParts") and not (e.get("hasSeparateDoors") or e.get("hasSeparateBonnet")):
                errors.append(f"{tag}: openable parts claimed without separate geometry")
            if e.get("oemPaintVerified") and not e.get("oemPaintCode"):
                errors.append(f"{tag}: oemPaintVerified without a paint code")
        if e.get("contentHash") in (None, ""):
            warnings.append(f"{tag}: missing contentHash (pending hash backfill)")
        if e.get("technicalStatus") == "pending":
            warnings.append(f"{tag}: technical QC pending")

    # generation overlap sanity: same make/modelFamily entries with overlapping
    # year ranges AND different generations are ambiguous
    by_family = collections.defaultdict(list)
    for e in cat:
        if e.get("publicationStatus") == "approved":
            by_family[(e["make"], e["modelFamily"])].append(e)
    for k, group in by_family.items():
        for x in group:
            for y in group:
                if x is y or not (x.get("yearStart") and y.get("yearStart")):
                    continue
                if x.get("generation") and y.get("generation") and x["generation"] != y["generation"]:
                    xe = x.get("yearEnd") or 9999; ye_ = y.get("yearEnd") or 9999
                    if x["yearStart"] <= ye_ and y["yearStart"] <= xe:
                        warnings.append(f"{k}: overlapping year ranges across generations {x['generation']}/{y['generation']}")

    report = {
        "auditedAt": datetime.datetime.utcnow().isoformat() + "Z",
        "entries": len(cat),
        "errors": sorted(set(errors)),
        "warnings": sorted(set(warnings))[:200],
        "errorCount": len(set(errors)),
        "warningCount": len(set(warnings)),
    }
    json.dump(report, open(a.report, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(f"entries={len(cat)} errors={report['errorCount']} warnings={report['warningCount']}")
    for e in report["errors"][:15]:
        print("ERROR:", e)
    sys.exit(1 if report["errors"] else 0)

if __name__ == "__main__":
    main()
