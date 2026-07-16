# Sketchfab → premium-catalogue ingest pipeline

Gated so no bad build reaches the live catalogue. Every car passes three gates.

## Gate 1 — automated QC (`pipeline.py qc <uid> [outdir]`)
Runs BEFORE a human looks. Emits a JSON report + 4 audit angles.
- **integrity** — valid glТF, has mesh primitives, sane vertex count, ≥100 KB
  (rejects scenes, dashboards, empties, corrupt files).
- **exploded** — flags a mesh whose bounding-box centre sits far outside the car
  (a detached / flying panel). Pure-glТF, no Blender.
- **coverage** — recolour body-paint share via the render worker's classifier.
  A *failed* measurement (model too large to audit) reads as **unknown**, never
  as bad — the visual gate is the backstop. Only a real low value warns.
- **glass share** — warns on see-through-shell risk.
- **oversized** — warns when the GLB is >60 MB (mobile-lightweight pass needed).
Verdict: `REJECT` (auto, on any hard-fail) or `REVIEW` (goes to a human).

## Gate 2 — human approval
The 4 angles are shown to the owner for the subjective call only
(toy-like / ugly / wrong car). Not automatable.

## Gate 3 — robust store (`pipeline.py store <spec.json>`)
Only on approval. Refuses to leave a half-finished entry.
- draco + upload GLB, **re-fetched and verified**.
- each OEM colour rendered with retries, uploaded, **re-fetched and verified**;
  ANY colour failing after retries **aborts the whole store** (no partial entry).
- catalogue written **atomically** (temp file → JSON-validated → `os.replace`).
- resolver + `finished/index.json` updated, then the entry is **read back from
  the live resolver** and confirmed `approved` before success is reported
  (`STORE_VERIFIED`).

## Metadata rule (no fabrication)
Only verifiable fields are written. `year`/`trim`/`generation` stay `null` unless
the spec passes a factual value (e.g. a model's documented production span). The
app's DVLA/DVSA decode is the authority for spec at lookup time.

## Secrets (never hardcoded)
Read from the environment: `SKFB_TOKEN`, `RUNPOD_KEY`, `RENDER_ENDPOINT`,
`SUPABASE_URL`, `SUPABASE_KEY`.

## store spec schema
```json
{
  "uid": "<sketchfab uid>", "assetId": "make-model-vN",
  "make": "porsche", "model": "macan", "modelFamily": "macan",
  "modelAliases": [], "bodyStyle": "suv",
  "yearStart": 2014, "yearEnd": 2021, "generation": null,
  "exactDerivative": null, "sourceTitle": "<verbatim source title>",
  "generationNote": "<verifiable note or omit>",
  "az": 40, "plate": "AL24 3D",
  "paintMaterialNames": [], "glassMaterialNames": []
}
```
`az` frames the car's FRONT so UK plate sides land correctly (use ~220 for
reverse-oriented / rear-engined models — confirm in the Gate-1 angles).
