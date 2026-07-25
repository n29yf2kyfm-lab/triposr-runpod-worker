"""
Load an open DTC database into Supabase `dtc_library`.

Works with the public SQLite DTC database (e.g. Wal33D/dtc-database — 28k+ codes),
or any CSV with columns: code, make, title, plain_english, severity, cause, fix.

    python ingest/ingest_dtc.py --source dtc-database.sqlite
    python ingest/ingest_dtc.py --source my_codes.csv --format csv

After ingest, run `python ai/embeddings.py` to make them RAG-searchable.
"""
from __future__ import annotations

import argparse
import csv
import sqlite3

from coding_engine.supabase_store import get_client


def rows_from_sqlite(path: str):
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    # Adapt table/column names to the source DB you use.
    for r in con.execute("select * from dtc"):
        d = dict(r)
        yield {
            "code": d.get("code") or d.get("dtc"),
            "make": d.get("make"),                       # null => generic
            "title": d.get("description") or d.get("title") or "",
            "plain_english": d.get("plain_english") or d.get("meaning"),
            "severity": (d.get("severity") or "medium").lower(),
            "typical_cause": d.get("cause"),
            "typical_fix": d.get("fix"),
        }
    con.close()


def rows_from_csv(path: str):
    with open(path, newline="", encoding="utf-8") as f:
        for d in csv.DictReader(f):
            yield {
                "code": d["code"], "make": d.get("make") or None,
                "title": d.get("title", ""), "plain_english": d.get("plain_english"),
                "severity": (d.get("severity") or "medium").lower(),
                "typical_cause": d.get("cause"), "typical_fix": d.get("fix"),
            }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--format", choices=["sqlite", "csv"], default="sqlite")
    args = ap.parse_args()

    db = get_client()
    gen = rows_from_sqlite(args.source) if args.format == "sqlite" else rows_from_csv(args.source)

    batch, n = [], 0
    for row in gen:
        if not row.get("code"):
            continue
        batch.append(row)
        if len(batch) >= 500:
            db.table("dtc_library").upsert(batch, on_conflict="code,make").execute()
            n += len(batch); batch = []; print(f"…{n} codes")
    if batch:
        db.table("dtc_library").upsert(batch, on_conflict="code,make").execute()
        n += len(batch)
    print(f"✓ {n} DTCs loaded. Now run: python ai/embeddings.py")


if __name__ == "__main__":
    main()
