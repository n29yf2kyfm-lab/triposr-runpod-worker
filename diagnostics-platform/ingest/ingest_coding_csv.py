"""
Generic coding-definition CSV loader — brand-agnostic (BMW FDL, VAG, anything).

Use this to bring your own feature lists (community-sourced or your own
reverse-engineering notes) into `coding_definition`. For BMW, FDL definitions
derive from CAFD/PSdZData which is proprietary/binary — do NOT parse that here;
instead export the human feature list to CSV and load it with this.

CSV columns (header required):
    feature_key,label,description,kind,did,byte_offset,bit_offset,bit_length,
    on_raw,off_raw,legal_class,risk,security_level,sfd_required,source

    python ingest/ingest_coding_csv.py --csv ingest/samples/bmw_fem_features.csv \
        --ecu-id <uuid>              # write to Supabase
    python ingest/ingest_coding_csv.py --csv ingest/samples/bmw_fem_features.csv --dry-run
"""
from __future__ import annotations

import argparse
import csv


def _bool(v: str) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "y")


def rows_from_csv(path: str, ecu_id: str):
    with open(path, newline="", encoding="utf-8") as f:
        for d in csv.DictReader(f):
            yield {
                "ecu_id": ecu_id,
                "feature_key": d["feature_key"].strip(),
                "label": d["label"].strip(),
                "description": d.get("description", "").strip() or None,
                "kind": d.get("kind", "fdl").strip(),
                "did": int(d["did"], 0) if d.get("did") else None,
                "byte_offset": int(d["byte_offset"]) if d.get("byte_offset") else None,
                "bit_offset": int(d["bit_offset"]) if d.get("bit_offset") not in (None, "") else None,
                "bit_length": int(d.get("bit_length") or 1),
                "options": [{"label": "On", "raw": int(d.get("on_raw") or 1)},
                            {"label": "Off", "raw": int(d.get("off_raw") or 0)}],
                "legal_class": d.get("legal_class", "comfort").strip() or "comfort",
                "risk": d.get("risk", "low").strip() or "low",
                "security_level": int(d["security_level"], 0) if d.get("security_level") else None,
                "sfd_required": _bool(d.get("sfd_required", "")),
                "source": d.get("source", "community").strip() or "community",
                "verified": False,
            }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--ecu-id", default="DRY")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    rows = list(rows_from_csv(args.csv, args.ecu_id))
    if args.dry_run:
        for r in rows:
            gate = "SFD" if r["sfd_required"] else (f"sec{r['security_level']}" if r["security_level"] else "open")
            pos = f"{r['byte_offset']}.{r['bit_offset']}" if r["byte_offset"] is not None else "-"
            print(f"  [{pos:>5}] {r['feature_key']:<28} {gate:<5} {r['legal_class']:<9} → {r['label']}")
        print(f"✓ {len(rows)} coding definitions parsed (dry run — nothing written).")
        return

    from coding_engine.supabase_store import get_client
    db = get_client()
    db.table("coding_definition").upsert(rows, on_conflict="ecu_id,feature_key").execute()
    print(f"✓ {len(rows)} coding definitions loaded. Now run: python ai/embeddings.py")


if __name__ == "__main__":
    main()
