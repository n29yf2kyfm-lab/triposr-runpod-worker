"""
Build / refresh pgvector embeddings for the coding knowledge base.

Run after each ingest so the RAG layer can find definitions by natural language.
Embeddings provider is pluggable (Voyage AI — Anthropic's recommended partner — or
OpenAI). Vector dim in db/schema.sql is 1024 (voyage-3 / text-embedding-3-small@1024).

    python ai/embeddings.py            # embeds rows missing an embedding
    python ai/embeddings.py --all      # re-embeds everything
"""
from __future__ import annotations

import argparse
import os
from typing import Iterable

from coding_engine.supabase_store import get_client

PROVIDER = os.environ.get("EMBEDDINGS_PROVIDER", "voyage")


def embed(texts: list[str]) -> list[list[float]]:
    if PROVIDER == "voyage":
        import voyageai
        vo = voyageai.Client(api_key=os.environ["EMBEDDINGS_API_KEY"])
        return vo.embed(texts, model="voyage-3", input_type="document").embeddings
    elif PROVIDER == "openai":
        from openai import OpenAI
        client = OpenAI(api_key=os.environ["EMBEDDINGS_API_KEY"])
        r = client.embeddings.create(model="text-embedding-3-small",
                                     input=texts, dimensions=1024)
        return [d.embedding for d in r.data]
    raise ValueError(f"Unknown EMBEDDINGS_PROVIDER={PROVIDER}")


def _text_for_definition(row: dict) -> str:
    opts = ", ".join(o.get("label", "") for o in row.get("options", []))
    return (f"{row['label']}. {row.get('description') or ''} "
            f"Feature {row['feature_key']} ({row['kind']}). Options: {opts}.")


def _text_for_dtc(row: dict) -> str:
    return f"{row['code']} {row['title']}. {row.get('plain_english') or ''} " \
           f"Cause: {row.get('typical_cause') or ''}."


def _refresh(table: str, textfn, only_missing: bool):
    db = get_client()
    q = db.table(table).select("*")
    rows = q.execute().data
    if only_missing:
        rows = [r for r in rows if not r.get("embedding")]
    if not rows:
        print(f"{table}: nothing to embed")
        return
    print(f"{table}: embedding {len(rows)} rows via {PROVIDER}")
    # batch to respect provider limits
    for i in range(0, len(rows), 100):
        batch = rows[i:i + 100]
        vecs = embed([textfn(r) for r in batch])
        for r, v in zip(batch, vecs):
            db.table(table).update({"embedding": v}).eq("id", r["id"]).execute()
    print(f"{table}: done")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="re-embed everything")
    args = ap.parse_args()
    only_missing = not args.all
    _refresh("coding_definition", _text_for_definition, only_missing)
    _refresh("dtc_library", _text_for_dtc, only_missing)


if __name__ == "__main__":
    main()
