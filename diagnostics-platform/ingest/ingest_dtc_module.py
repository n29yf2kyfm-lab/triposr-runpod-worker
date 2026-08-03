"""
Load the curated DTC database (data/dtc_curated.py) into Supabase `dtc_library`.

This is the human-written plain-English layer (better wording than the bulk open
DBs). Run this, then optionally ingest a bulk DB for coverage, then embed for RAG.

    python ingest/ingest_dtc_module.py --dry-run
    python ingest/ingest_dtc_module.py
"""
from __future__ import annotations

import argparse
import importlib.util
import os

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_curated():
    path = os.path.join(_HERE, "data", "dtc_curated.py")
    spec = importlib.util.spec_from_file_location("dtc_curated", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def rows():
    m = _load_curated()
    out = []
    # generic (SAE J2012) — make = null
    for code, (title, plain, causes) in m.GENERIC.items():
        out.append({"code": code, "make": None, "title": title,
                    "plain_english": plain, "typical_cause": causes})
    # manufacturer-specific
    brand_to_make = {
        "VAG (VW / Audi / Skoda / Seat)": "VAG", "BMW": "BMW",
        "Toyota / Lexus": "Toyota", "Ford": "Ford",
    }
    for brand, codes in m.MANUFACTURER.items():
        make = brand_to_make.get(brand, brand)
        for code, (title, plain, causes) in codes.items():
            out.append({"code": code, "make": make, "title": title,
                        "plain_english": plain, "typical_cause": causes})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    data = rows()
    if args.dry_run:
        for r in data:
            tag = r["make"] or "generic"
            print(f"  {r['code']:<6} [{tag:<8}] {r['title']}")
        print(f"✓ {len(data)} DTCs parsed (dry run — nothing written).")
        return

    from coding_engine.supabase_store import get_client
    db = get_client()
    db.table("dtc_library").upsert(data, on_conflict="code,make").execute()
    print(f"✓ {len(data)} curated DTCs loaded. Now run: python ai/embeddings.py")


if __name__ == "__main__":
    main()
