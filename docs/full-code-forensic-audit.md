# Full-Repo Forensic Code Audit
**Owner document · 2026-07-15 · every code file in the repository read end-to-end.**
Companion to `docs/render-blender-forensics.md` (the render/Blender deep-dive,
whose findings F1–F7 are all FIXED and deployed) and
`docs/alam3d-forensic-report.md` (the generation-stack review).

Estate: ~5,600 lines of code across 35 files (plus data/catalogue JSON).
Verdicts: **SOLID** (production-ready) · **OK** (works, minor notes) ·
**FINDING** (defect, see below) · **LEGACY** (superseded, keep as record) ·
**ATTIC** (fenced off, do not run).

---

## 1. Serving workers (the money path)

| File | Lines | Role | Verdict |
|---|---|---|---|
| `render/handler.py` | 793 | GPU studio renderer: draco catalogue, flat/tint recolour, finish-aware paint, fill cards, plate, mat_audit | **SOLID** — rebuilt + live-verified this session |
| `render/Dockerfile` | 56 | bpy 4.5.11 + build-time draco/import check | **SOLID** |
| `trellis/handler.py` | 309 | TRELLIS.2-4B image→GLB: multi-view, cutout detection, quality knobs, Supabase upload, licence patches (free BiRefNet repin, DINOv3 version-proofing) | **SOLID** — note A6 style nit |
| `trellis/alam3d_multiview.py` | 62 | multi-photo token-fusion conditioning [N,T,D]→[1,N·T,D] | **SOLID** |
| `trellis/Dockerfile` | 92 | CUDA build with every hard-won lesson documented in-line (arch pinning, MAX_JOBS, setup.sh getopt trap) | **SOLID** |

## 2. Resolution & identity (TypeScript)

| File | Lines | Role | Verdict |
|---|---|---|---|
| `src/lib/vehicle-resolver.ts` | 137 | v2 generation-aware resolver: hard gates, conflict rejection, score<75 → unavailable, disclosures | **SOLID** (tested) |
| `src/lib/vehicle-normalisation.ts` | 138 | DVLA strings → canonical identity; all aliases in `data/*.json` (verified present) | **SOLID** |
| `src/lib/oem-paint-resolver.ts` | 86 | owner's 8-step OEM paint workflow; image ranking may reorder, never decide, never confirm | **SOLID** (34/34 tests) |
| `platform/resolver/index.ts` | 117 | **deployed** Supabase Edge Function resolver | **FINDING A1** |
| `platform/dvsa-lookup/index.ts` | 88 | DVSA MOT-history decode; token cached; only real DVSA fields returned; reg never stored | **SOLID** |
| `src/types/*`, `tests/*` (3 suites) | ~400 | schema types + resolver/paint/catalogue tests with real-field factories | **SOLID** |

**A1 — the deployed resolver is NOT the v2 resolver (HIGH).**
`platform/resolver/index.ts` (the Edge Function) is the old Phase-1 scorer:
additive points, `exact` = score≥80 (make+model alone = 80), **no generation
conflict rejection, no year hard gate, no quarantine/status awareness, no
disclosures**, reading the flat `variant_resolved` view. The v2 resolver with
the non-negotiable rules ("never silently cross generations", "no model beats
wrong model") exists only in `src/lib/` + its tests. Until the Edge Function is
replaced with the v2 logic + v2 catalogue, the app can serve a Mk7 for a Mk8
with an "exact" badge — the exact failure v2 was written to forbid.
*Fix: port `vehicle-resolver.ts` + `vehicle-normalisation.ts` into the Edge
Function (Deno-compatible, no deps beyond JSON imports) and point it at
`catalogue.v2.json`. Blocked only by Lovable credits for app-side wiring, but
the function itself deploys from here.*

## 3. Catalogue & publishing (Python)

| File | Lines | Role | Verdict |
|---|---|---|---|
| `pipeline/catalogue/migrate_catalogue.py` | 228 | v1→v2 migration: verbatim titles, defensible years only, quarantine, mojibake repair | **SOLID** (one-shot, job done) |
| `pipeline/catalogue/audit_catalogue.py` | 91 | schema + policy gates, exit-1 on error | **SOLID** |
| `pipeline/verify_public_asset.py` | 68 | byte-level publish verification (magic, hash, Khronos validator) | **OK** — A7 |
| `platform/catalogue/build_index.py` | 211 | curated UK vehicle master index (cars/vans/bikes) → Supabase | **OK** — A8 |
| `platform/catalogue/build_catalogue.py` | 99 | Phase-1 MVP frame publisher (4 cars) | **LEGACY** — superseded by v2 flow |
| `schemas/vehicle-asset.schema.json` | 80 | v2 asset contract | **SOLID** |

## 4. Generation & candidate pipeline (offline only)

| File | Lines | Role | Verdict |
|---|---|---|---|
| `pipeline/trellis/prep_images.py` | 77 | cutout prep with honest input-standards notes | **SOLID** |
| `pipeline/trellis/generate.py` | 82 | multi-seed candidate fan-out | **FINDING A2** |
| `pipeline/trellis/score.py` | 90 | candidate auto-scoring | **FINDING A3** |
| `pipeline/generators/rodin_api.py` | 147 | Hyper3D Rodin client (awaiting Business key) | **SOLID** (untested against live API) |
| `pipeline/generators/hunyuan3_api.py` | 123 | Tencent 3.x cloud client, TC3 signing, selftest | **OK** (dormant) |
| `hunyuan21/handler.py` + `Dockerfile` | 187 | 2.1 worker — endpoints DELETED; UK-excluded licence documented in header | **LEGACY** (documentation value: the alpha-binarise lesson + 3 build defects) |

**A2 — `generate.py` depends on an uncommitted helper (MEDIUM).**
`RP = …/scratchpad/rp.py` — the repo has no `scratchpad/`; the helper lives in
a session sandbox. Fresh clone → stage 3 cannot run. *Fix: commit a minimal
`pipeline/rp.py` (submit/status/patch via urllib, key from env) and point the
script at it.*

**A3 — `score.py` symmetry mirrors the WRONG axis (MEDIUM).**
`wa = 0 if ext[0] >= ext[2] else 2` picks the **larger** horizontal extent —
that's the car's LENGTH. The metric therefore scores front↔rear mirror
agreement, not left↔right: cars are left-right symmetric, so the headline
40%-weighted metric is systematically wrong (a perfectly good candidate scores
low; a front-back-symmetric blob scores high). Also dead code in
`cleanliness()` (`if False else 0`). *Fix: pick the smaller horizontal extent;
delete the dead branch.*

## 5. Blender & NURBS pipeline
Covered exhaustively in `docs/render-blender-forensics.md`; all seven findings
fixed and pushed this session. Current state: `car_common.py` (shared axes /
arch detection / role rules), assembly chain `prop_fix → cabin_assembly →
degap_shell → wheel_replace`, QC `qc_audit` + `pipeline/qc/asset_audit.py`
(five gates), `clean_export`/`golf_finish` (4.1+-safe), `bridge_gaps`/
`fill_gaps`/`add_plates`/`generic_recolour`/`decimate_heavy`, tooling-only
`pipeline/nurbs/loft_body.py` (proven-negative for premium bodies, kept for
.3dm ingest + section measurement), and `attic/` (four fenced one-offs).
`platform/undercarriage.py` (procedural underbody + pose normalisation +
plates): **OK** — heuristic front-detection documented, material names align
with the render worker's exclusion rules (verified `undercarriag` matches).

## 6. Build / CI / ops

| File | Verdict | Note |
|---|---|---|
| `.github/workflows/render-docker-build.yml` | **SOLID** | per-SHA tags, branch-triggered |
| `.github/workflows/trellis-docker-build.yml` | **SOLID** | **correction to the record: it DOES push `trellis2-<sha>` tags** — the long-standing "missing per-SHA tag fix" note was wrong; nothing to do |
| `.github/workflows/hunyuan-docker-build.yml` | **LEGACY** | endpoints deleted; workflow harmless (path-scoped) |
| `pipeline/install.sh`, `pipeline/optimise.sh` | **OK** | optimise.sh is the source of the draco-compressed library (now readable end-to-end since the worker fix) |
| `pipeline/validate.js` | **OK** | exists (verified) — used by verify_public_asset |

**A7 — `verify_public_asset.py` cache-bust appends `?cb=verify` blind (LOW):**
breaks if a URL ever carries a query string. **A8 — `build_index.py` carries
two `if False else` dead branches and a duplicate "Grey" in COLOURS (LOW,
cosmetic; the set() dedupes).** **A6 — `trellis/handler.py` two-space indent
inside the single-image `else:` block (LOW, style only).**

## 7. Priority actions from this audit
1. **A1 (HIGH):** deploy the v2 resolver logic into the `resolve-vehicle` Edge
   Function against `catalogue.v2.json` — the only place where written policy
   and running code disagree.
2. **A3 (MEDIUM):** one-line axis fix in `score.py` — the candidate gate is
   currently measuring the wrong symmetry.
3. **A2 (MEDIUM):** commit `pipeline/rp.py` so stage-3 generation runs from a
   fresh clone.
4. A7/A8/A6 (LOW): sweep in the next housekeeping commit.

**Overall:** the serving path (render worker, QC, catalogue integrity, DVSA
decode, paint rules) is in its best state ever — audited, tested, deployed,
and consistent. The one policy-critical gap is A1: the deployed resolver
predates the rules the rest of the system enforces.
