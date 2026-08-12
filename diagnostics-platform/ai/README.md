# AI layer — grounded on the coding knowledge base

## The decision: RAG, not fine-tuning (for anything that produces a value)

You asked whether to train an AI or use reverse-engineering data directly. Here's the call
and why:

| | Fine-tune a model on coding data | **RAG over the coding DB (chosen)** |
|--|--|--|
| Produces coding values | Model *generates* them → can **hallucinate a byte → brick an ECU** | Values read **verbatim from a DB row**; model never invents them |
| New cars / ECUs | Retrain every time | Just insert rows |
| Traceability | Opaque | Every answer **cites the exact `coding_definition.id`** |
| Cost | High, recurring | Low |
| Safety | ❌ unacceptable for writes | ✅ auditable |

**So:** the AI's job is **understanding intent and explaining** — turn "make the mirrors fold
when I lock it" into *the right stored definition*, and explain a fault in plain English. The
**write value always comes from Postgres, not the model.** That's the only responsible design
for something physical and irreversible.

Fine-tuning stays on the table for exactly one thing later: the *tone/style* of fault
explanations (a small model that sounds like a friendly mechanic). Never for values.

## How it works

```
user: "fold the mirrors when I lock the car"  (BMW G20)
   │
   ├─ embed the request (voyage-3 / openai)
   ├─ pgvector cosine search over coding_definition.embedding  (filtered to the car's ECUs)
   │     → top match: coding_definition{feature_key:'mirror_fold_on_lock', id:…, options:[…]}
   │
   ├─ Claude: given the retrieved rows ONLY, pick the definition + option, explain it,
   │          flag risk/legal, and return the definition id + chosen option label
   │
   └─ engine: bmw.apply_feature(..., feature_key, option_label)  ← value re-read from DB
```

Claude is **constrained to the retrieved rows** and instructed to refuse if none match — it
cannot free-style a coding value.

## Files
- `embeddings.py` — build/refresh pgvector embeddings for every `coding_definition` and
  `dtc_library` row (run after each ingest).
- `rag.py` — the retrieval + Claude explanation/selection step.

## Training data flywheel (the useful part of "train an AI")
Every real coding action and its outcome is captured in `coding_audit`, and every scan in
`scan`. Over time that becomes a labelled dataset:
- which faults co-occur, which fixes worked (improves the plain-English fix guidance),
- which coding requests map to which definitions (improves retrieval),
- verified-on-real-car flags (raises confidence).

That's your moat compounding — not a one-off fine-tune.
