# Emailed GLB batch — 2026-08-08

30 GLBs (229MB) emailed by Imaad Ahmed, downloaded from Drive, staged to
`car-meshes/staging/inbox/<uid>.glb`, four-view sheets at `car-meshes/audit/inbox/<uid>.jpg`.
Sender said the full set is >6GB; this is a first slice.

Data sheet: https://claude.ai/code/artifact/b735e043-7bfc-4431-b316-9dcc0bf1c7b6

## Result

| outcome | n |
|---|---|
| real gap | 7 |
| duplicate of a live car | 13 |
| not-UK market / concept | 7 |
| broken (zero body materials) | 1 |
| already owner-scrapped (2006 RR Supercharged) | 1 |

**Shippable now — clean split, fills a gap, all Jaguar:**
- `1995_jaguar_xj12_lwb_x305` — 1 body mat, cov 0.304
- `2005_jaguar_xj6_tdvi_x350` — 1 body mat, cov 0.380
- `2009_jaguar_xkr_5.0_supercharged_speed_pack` — 2 body mats, cov 0.331

**Gap but split fails:** XJ220 (cov 0.703; `XJ220MI_Engine1` 20.8% is classed as body, so
paint would cover the engine, exhaust and rims), XJ X308 Daimler (0.571), Audi Quattro B2
(0.792), Golf GTI Mk1 (0.420, borderline).

## Gotcha that cost a bad call

`mat_audit` returns **`body_pct`**, NOT `coverage`. Reading the wrong key silently yields 0
for every car, which looks exactly like "no paintable body" and nearly got the whole batch
written off. `coverage` only exists on the RENDER response when recolour is on
(see `wave_render.py`, which reads it from `H._render`'s return, not from mat_audit).

Re-run the audit with `pipeline/ingest/inbox/inbox_audit.py <folder>` — resumable against
the bucket.
