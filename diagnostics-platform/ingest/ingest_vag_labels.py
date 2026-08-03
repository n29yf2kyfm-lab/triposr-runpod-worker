"""
Parse *plaintext* VCDS label files into `coding_definition` rows (VAG).

VCDS ships human-readable .lbl/.clb label files. The **plaintext** ones describe
long-coding bits and adaptation channels, e.g.:

    ;LONG CODING
    Byte;7;Bit;0;;Mirror fold on lock active
    Byte;7;Bit;1;;Cornering lights active

We map each "Byte;X;Bit;Y" line to a coding_definition with byte_offset=X,
bit_offset=Y, a boolean On/Off option, kind='long_coding'.

⚠️ Only ingest plaintext labels you are licensed to use. Do NOT decrypt Ross-Tech
compiled .CLB files — that format is proprietary (see SAFETY.md).

    python ingest/ingest_vag_labels.py --labels ./labels/ --platform-id <uuid> --ecu-key 09_CENTRAL_ELECTRICS
"""
from __future__ import annotations

import argparse
import glob
import os
import re

LINE = re.compile(r"Byte\s*;\s*(\d+)\s*;\s*Bit\s*;\s*(\d+)\s*;.*;\s*(.+)", re.IGNORECASE)


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:60]


def parse_label_file(path: str):
    with open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            m = LINE.search(line)
            if not m:
                continue
            byte_off, bit_off, label = int(m.group(1)), int(m.group(2)), m.group(3).strip()
            if not label or label.startswith(";"):
                continue
            yield {
                "feature_key": slugify(label),
                "label": label,
                "description": f"VAG long-coding: {label} (byte {byte_off}.{bit_off}).",
                "kind": "long_coding",
                "did": 0x0600,                    # coding block DID (adapt per ECU/platform)
                "byte_offset": byte_off,
                "bit_offset": bit_off,
                "bit_length": 1,
                "options": [{"label": "On", "raw": 1}, {"label": "Off", "raw": 0}],
                "legal_class": "lighting" if "light" in label.lower() else "comfort",
                "risk": "low",
                "source": "vcds_label",
                "verified": False,
            }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", required=True, help="dir OR single plaintext .lbl file")
    ap.add_argument("--ecu-id", default="DRY", help="Supabase ecu.id to attach these to")
    ap.add_argument("--dry-run", action="store_true",
                    help="parse and print rows without touching Supabase")
    args = ap.parse_args()

    if os.path.isfile(args.labels):
        files = [args.labels]
    else:
        files = glob.glob(os.path.join(args.labels, "**", "*.lbl"), recursive=True)

    if args.dry_run:
        db = None
    else:
        from coding_engine.supabase_store import get_client
        db = get_client()
    total = 0
    for path in files:
        rows = [dict(r, ecu_id=args.ecu_id) for r in parse_label_file(path)]
        if not rows:
            continue
        if args.dry_run:
            for r in rows:
                print(f"  [{r['byte_offset']}.{r['bit_offset']}] "
                      f"{r['feature_key']:<32} → {r['label']}")
        else:
            db.table("coding_definition").upsert(rows, on_conflict="ecu_id,feature_key").execute()
        total += len(rows)
        print(f"{os.path.basename(path)}: +{len(rows)}")
    tail = "(dry run — nothing written)" if args.dry_run else "Now run: python ai/embeddings.py"
    print(f"✓ {total} coding definitions parsed. {tail}")


if __name__ == "__main__":
    main()
