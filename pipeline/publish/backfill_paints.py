"""Fill `colourVariantPaints` on entries that already ship colour variants.

Metadata only. This never touches a GLB, never re-uploads a variant and never
clears a recolour stamp -- which is the whole point of it existing separately
from `colour_variants.py --rebake`. Re-baking would rewrite the eight variant
GLBs, change `variantsHash`, and invalidate the render-verified stamp on every
car it touched, forcing a full re-audit to recover metadata that was only ever
missing from the JSON. For 143 cars that is hours of GPU time to fix a field
lookup.

Why the field is empty on so many entries: the older bake tool
(`wave_tools/variants_w7.py`) wrote `colourVariants` and nothing else -- the
OEM paint resolution did not exist yet. Those entries have shipped ever since
with no "Possible OEM colour" to show. Separately, `oem_paints()` matched the
make exactly, so the slugged makes the catalogue uses ("land-rover",
"alfa-romeo") missed the spelled-out ones the paint DB uses; that is fixed in
colour_variants._mk and this tool inherits it.

The paints are ranked candidates, never a claim -- step 7 of the resolution
workflow. A make the database does not cover resolves to nothing rather than
to another marque's palette, and this tool reports those separately instead of
quietly leaving them looking identical to a failure.

Usage:
    backfill_paints.py --dry-run
    backfill_paints.py            # writes the local catalogue; gate + serve after
"""
import argparse, json, os, sys, collections

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "pipeline", "publish"))
from colour_variants import oem_paints, PALETTE, DVLA                # noqa: E402

CAT = os.path.join(REPO, "platform", "catalogue", "catalogue.v2.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--overwrite", action="store_true",
                    help="also recompute entries that already carry paints")
    a = ap.parse_args()

    cat = json.load(open(CAT))
    entries = cat if isinstance(cat, list) else cat.get("entries", cat)

    db_cache, filled, empty = {}, [], collections.Counter()
    for e in entries:
        if e.get("publicationStatus") != "approved":
            continue
        if not (e.get("colourVariants") or {}):
            continue
        if not a.overwrite and sum(len(v) for v in (e.get("colourVariantPaints") or {}).values()):
            continue
        make = e.get("make")
        if make not in db_cache:
            db_cache[make] = oem_paints(make)
        db = db_cache[make]
        paints = {c: db.get(DVLA[c], []) for c in PALETTE}
        n = sum(len(v) for v in paints.values())
        if not n:
            empty[make] += 1
            continue
        if not a.dry_run:
            e["colourVariantPaints"] = paints
        filled.append((e["assetId"], make, n))

    by_make = collections.Counter(m for _, m, _ in filled)
    for m, c in sorted(by_make.items()):
        print(f"  {m:16s} {c:3d} car(s)  x {db_cache[m] and sum(len(v) for v in {k: db_cache[m].get(DVLA[k], []) for k in PALETTE}.values())} paint candidates")
    print(f"\n{len(filled)} entrie(s) gain OEM paints"
          + ("  [DRY RUN — nothing written]" if a.dry_run else ""))
    if empty:
        print(f"{sum(empty.values())} left empty — make not in oem_paint_db.csv: "
              + ", ".join(f"{m}({c})" for m, c in sorted(empty.items())))

    if filled and not a.dry_run:
        json.dump(cat, open(CAT, "w"), indent=1, ensure_ascii=False)
        print("catalogue.v2.json updated locally — gate, then serve BOTH paths.")


if __name__ == "__main__":
    main()
