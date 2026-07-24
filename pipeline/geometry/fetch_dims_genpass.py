#!/usr/bin/env python3
"""fetch_dims_genpass.py — second pass for vehicle_dims.csv blanks.

High-volume models (Focus, Corsa, Golf...) have multi-generation Wikipedia
overview pages with no dims in the infobox; the numbers live on per-generation
pages. For every row still missing length+width, this pass re-searches with the
asset's year in the query (biasing to the right generation page) and with
explicit generation-page phrasings, then updates the row in place. Same
verifiability rules: parsed mm or blank, source_page recorded.

Usage: python3 pipeline/geometry/fetch_dims_genpass.py [--sleep 0.8]
"""
import argparse, csv, datetime, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_dims import SANE, extract_dims, search_page, wikitext, REPO

CSV = os.path.join(REPO, "platform", "geometry", "vehicle_dims.csv")
CAT = os.path.join(REPO, "platform", "catalogue", "catalogue.v2.json")


def year_for(make, model):
    for e in json.load(open(CAT)):
        if (e.get("make") or "").strip().lower() == make.lower() and \
           (e.get("model") or "").strip().lower() == model.lower():
            return e.get("yearStart")
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sleep", type=float, default=0.8)
    a = ap.parse_args()
    import time
    rows = list(csv.DictReader(open(CSV)))
    cols = rows[0].keys()
    today = datetime.date.today().isoformat()
    fixed = tried = 0
    for r in rows:
        if r["length_mm"] and r["width_mm"]:
            continue
        tried += 1
        yr = year_for(r["make"], r["model"])
        queries = []
        if yr:
            queries.append(f"{r['make']} {r['model']} {yr}")
        queries += [f"{r['make']} {r['model']} generation",
                    f"{r['make']} {r['model']} Mk"]
        got = None
        for q in queries:
            title = search_page(q)
            if not title:
                continue
            d = extract_dims(wikitext(title))
            if d.get("length_mm") and d.get("width_mm"):
                got = (d, title)
                break
            time.sleep(a.sleep)
        if got:
            d, title = got
            for c in SANE:
                if d.get(c):
                    r[c] = d[c]
            r["source_page"] = title
            r["fetched"] = today
            fixed += 1
            print(f"  FIXED {r['make']} {r['model']}: {d} ({title})", flush=True)
        else:
            print(f"  still blank: {r['make']} {r['model']}", flush=True)
        time.sleep(a.sleep)
        # write-through every row so kills lose nothing
        with open(CSV, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader(); w.writerows(rows)
    full = sum(1 for r in rows if r["length_mm"] and r["width_mm"])
    print(f"\nGENPASS_DONE tried={tried} fixed={fixed} -> {full}/{len(rows)} full pairs")


if __name__ == "__main__":
    main()
