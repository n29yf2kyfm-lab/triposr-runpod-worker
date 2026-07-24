#!/usr/bin/env python3
"""validate_dims.py — reject dims rows whose source page doesn't name the model.

The searches in fetch_dims/fetch_dims_genpass can land on a page for a
DIFFERENT vehicle that still has dims (observed: Taigo<-Golf Mk4, Model Y<-
Geely, Civic<-Prelude). Accent-aware check: some token of the model name must
appear in the source page title. Used as a library by the fetchers and as a
CLI sweep over vehicle_dims.csv (blanks offending rows; blank beats wrong).

CLI: python3 pipeline/geometry/validate_dims.py [--csv PATH] [--dry]
"""
import argparse
import csv
import re
import unicodedata


def _norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", s.lower())


def page_matches(model, source_page):
    """True iff the source page plausibly names this model."""
    page = _norm(source_page)
    key = _norm(model)
    toks = [t for t in re.findall(r"[a-z0-9]+", (model or "").lower())
            if len(_norm(t)) >= 2 and not (t.isdigit() and len(t) == 4)]
    return bool(page) and ((key and key in page) or any(_norm(t) in page for t in toks))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=None)
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    import os
    path = a.csv or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "platform", "geometry", "vehicle_dims.csv")
    rows = list(csv.DictReader(open(path)))
    cols = rows[0].keys()
    blanked = []
    for r in rows:
        if not (r["length_mm"] or r["width_mm"]):
            continue
        if not page_matches(r["model"], r["source_page"]):
            blanked.append(f"{r['make']} {r['model']} <- {r['source_page']}")
            if not a.dry:
                for c in ("length_mm", "width_mm", "height_mm", "wheelbase_mm"):
                    r[c] = ""
    if not a.dry and blanked:
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
    full = sum(1 for r in rows if r["length_mm"] and r["width_mm"])
    print(f"validate_dims: {len(blanked)} wrong-page rows{' (dry)' if a.dry else ' blanked'}; "
          f"{full}/{len(rows)} verified full pairs")
    for b in blanked:
        print("  ", b)


if __name__ == "__main__":
    main()
