"""
RAG: natural language -> the right stored coding definition (+ plain-English explain).

Guarantees (see ai/README.md and SAFETY.md):
  - Retrieval is restricted to coding_definition rows for THIS vehicle's ECUs.
  - Claude may only SELECT among retrieved rows and EXPLAIN them. It returns a
    definition id + option label. It must NOT invent coding values.
  - The engine then re-reads the value from that row before writing.
"""
from __future__ import annotations

import json
import os

import anthropic

from coding_engine.supabase_store import get_client
from ai.embeddings import embed

MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5")

SYSTEM = """You are the coding assistant for a car diagnostics app.
You are given a driver's request and a list of RETRIEVED coding definitions that
exist for their exact vehicle. Your job:
  1. Choose the single best matching definition, or say none match.
  2. Pick the correct option label for what the driver asked.
  3. Explain in one friendly sentence what it does, and flag risk/legal if any.
You MUST only choose from the provided definitions. You must NEVER output raw
coding bytes or values — those are applied from the database, not by you.
Respond as strict JSON: {"definition_id": "...|null", "option_label": "...|null",
"explanation": "...", "risk": "low|medium|high", "refuse_reason": "...|null"}."""


def _retrieve(vehicle_ecu_ids: list[str], request: str, k: int = 6) -> list[dict]:
    """pgvector cosine search over coding_definition, filtered to the car's ECUs.

    Uses an RPC `match_coding_definitions(query_embedding, ecu_ids, match_count)`
    — see the SQL function at the bottom of this file to create it in Supabase.
    """
    db = get_client()
    qvec = embed([request])[0]
    rows = db.rpc("match_coding_definitions", {
        "query_embedding": qvec,
        "ecu_ids": vehicle_ecu_ids,
        "match_count": k,
    }).execute().data
    return rows


def resolve(request: str, vehicle_ecu_ids: list[str]) -> dict:
    """Return {definition_id, option_label, explanation, risk, refuse_reason}."""
    candidates = _retrieve(vehicle_ecu_ids, request)
    slim = [{
        "definition_id": c["id"], "label": c["label"],
        "description": c.get("description"), "feature_key": c["feature_key"],
        "options": [o["label"] for o in c.get("options", [])],
        "risk": c.get("risk"), "legal_class": c.get("legal_class"),
    } for c in candidates]

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    msg = client.messages.create(
        model=MODEL, max_tokens=400, system=SYSTEM,
        messages=[{"role": "user", "content":
                   f"Driver request: {request}\n\n"
                   f"Retrieved definitions:\n{json.dumps(slim, indent=2)}"}],
    )
    text = msg.content[0].text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"definition_id": None, "option_label": None,
                "explanation": text, "risk": "high",
                "refuse_reason": "model_output_not_json"}


# ---------------------------------------------------------------------------
# Supabase RPC to create once (pgvector search filtered to a vehicle's ECUs):
#
#   create or replace function match_coding_definitions(
#       query_embedding vector(1024), ecu_ids uuid[], match_count int)
#   returns setof coding_definition language sql stable as $$
#     select * from coding_definition
#     where ecu_id = any(ecu_ids)
#     order by embedding <=> query_embedding
#     limit match_count;
#   $$;
# ---------------------------------------------------------------------------
