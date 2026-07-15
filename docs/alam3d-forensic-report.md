# ALAM 3D — Forensic Code Review & System Architecture
**Owner build document · 2026-07-15 · reviewed against live behaviour, not docs**

Alam 3D = the owner's vehicle-3D machine: an owned fork of open generation
cores + an owned assembly/QC/colour/publish pipeline. Everything below exists
in this repo or the pinned upstream sources today. Licence position: TRELLIS.2
is MIT (fork/rename/modify permitted, keep the MIT notice); Rodin is an API
contract; Hunyuan 2.x is UK-excluded and retired from infra.

---

## 1. Generation core — TRELLIS.2 (cloned, read, understood)

**Anatomy** (`trellis2/`):
- `pipelines/trellis2_image_to_3d.py` — the whole inference brain.
  Three cascaded 1.3B flow DiTs: sparse structure (64³ occupancy) →
  shape SLat (512→1024→1536³ cascade) → texture SLat (voxel PBR).
  `run()` knobs: `pipeline_type` ('512'|'1024'|'1024_cascade'|'1536_cascade'),
  `num_samples` (batched best-of-N), per-stage `sampler_params`, `seed`,
  `max_num_tokens` (auto-degrades resolution under VRAM pressure).
- `models/` — flow transformers + SC-VAEs. `o-voxel/` — the mesh/voxel
  container and `postprocess.to_glb` (decimation target, remesh hole-closing,
  texture bake up to 4K).
- `train.py` + `configs/gen/*ft1024*.json` + `data_toolkit/` — a complete,
  shipped fine-tune stack: download → Blender-render conditioning views →
  encode shape/PBR/ss latents → train. **Fine-tuning is a supported workflow,
  not research.**

**Forensic findings (measured tonight):**
- F1. Depth ambiguity: single-view conditioning guesses length; measured
  L/W error −13% (Golf GTE), −16% (Golf), −27% at elevated camera angle
  (Scirocco: 1.72 vs 2.35 real). Systematic, seed-independent.
- F2. Occluded-side hallucination: every rear generated from a front photo
  was invented (4/4 assets).
- F3. Output is one fused shell + baked texture. No parts, glass, interior —
  representation-level, unreachable by any config or fine-tune.
- F4. Our worker (`trellis/handler.py:212`) leaves every quality knob at
  default: no `pipeline_type` (1536 cascade unused), no `num_samples`,
  2K texture vs 4K max. **Cheapest available quality upgrade in the stack.**
- F5. Input hygiene decides quality: reflective/cluttered photos bake scene
  reflections into glass (Scirocco #1); clean diffuse photos produced the
  session-best asset (Scirocco #2). Enforce source-photo standards.

## 2. Alternative cores
- `pipeline/generators/rodin_api.py` — Hyper3D Rodin Gen-2.5 client
  (multipart submit ≤5 images, status poll, download; `--selftest`).
  Multi-image fusion is the only untested fix for F1/F2. Needs Business key.
- `pipeline/generators/hunyuan3_api.py` — Tencent 3.x cloud client (dormant).
- `hunyuan21/` — retained as documentation; endpoints deleted; three upstream
  build defects found and fixed there (nonexistent `bpy==4.0` pin;
  `pkg_resources` removed by setuptools 81; compile script writing a pybind
  module without its `.so` suffix — silent because of a bare `try/except`).
  Lesson institutionalised: **builds must import-check every compiled module.**

## 3. Assembly stage (the owned differentiator — this is Alam 3D's moat)
- `pipeline/blender/cabin_assembly.py` — glass split to real alpha-BLEND
  material + parametric interior (floor/dash/seats/bench/shelf) + wheel split.
  **First pipeline output ever to PASS all five audit gates** (Scirocco:
  glass ✓ interior 7,692 verts ✓ wheels ✓ paint 0.039 ✓ L/W 2.42≈2.35 ✓).
- `prop_fix` (scratchpad, to be committed) — axis-autodetecting proportion
  corrector; stretches body to real L/W, translates wheels rigidly (stay
  round), compresses above wheel-top to real H/W. Fixes F1 deterministically.
- `gte7_wheels` (scratchpad, unrun) — parametric wheel replacement (delete AI
  wheel blobs; tyre torus + rim + 10 spokes + arch liner). Stage-2 fix for
  wheel mush.
- Door articulation (stage 2, designed, not built): cut along detected
  shutlines, fill jambs, glTF hinge node + animation. Only worth building on
  Rodin-grade or licensed shells.
- Known heuristics with tuned constants (fragile, per-model): glass beltline
  0.60H, tumblehome 0.84, screen bands; wheel R 0.080–0.085L. Majority-vote
  cleanup pass fixes stragglers.

## 4. QC — the standard that makes it headache-free
- `pipeline/qc/asset_audit.py` — five gates, calibrated on known-good vs
  known-bad: G1 proportions (mirror-safe width, advisory without verified
  dims), G2 real glass (transmission/alpha), G3 interior (≥1500 verts in
  cabin core), G4 wheel patchiness (texture luma σ ≤0.22), G5 paint blotch
  (low-freq luma σ ≤0.10). Draco inputs decoded via gltf-transform.
  Library sweep: 173 audited → 4 A / 74 B / 95 quarantined / 0 errors.
- `pipeline/verify_public_asset.py` — byte-level publish verification.
- Render QC rule: verify BOTH sides at the owner's viewing angle; harness
  lighting must match the app (matte-gm28 lesson).

## 5. Colour & identity
- `src/lib/oem-paint-resolver.ts` + `data/oem-paints.json` (272 paints) —
  owner's 8-step OEM workflow; image analysis may rank, never decide;
  display always "Possible OEM colour: …". 34/34 tests green.
- `pipeline/blender/generic_recolour.py` (scratchpad→commit) — multiply
  factor on paint-named materials only; hard rule: never recolour models
  without a real paint material (95-quarantine sweep re-proved why).
- `render/handler.py` — studio renderer; palette covers every COLOUR_FAMILY.
- `add_plates.py` — GB plates; privacy invariant: source regs/dealer boards
  are masked before generation; a reg never enters a texture or key.

## 6. Serving & catalogue
- catalogue v2 (schema-validated, provenance verbatim, disclosures,
  quarantine reasons, colourVariants map, per-asset `qc` block), incremental
  commits + timestamped backups, reports in `car-renders/reports/`.
- Resolver: generation-aware gates, AI assets always disclosed; nothing
  below "approved" serves.

## 7. Infrastructure forensics (the headaches, and their cures)
| Headache (observed) | Cure (now standard) |
|---|---|
| `:latest` served by warm worker with stale image | pin per-commit tags `<worker>-<sha>` |
| Silent build breakage (bpy/pkg_resources/.so) | build-time import checks in Dockerfile |
| DC capacity throttle starving jobs 45+ min | volume-less any-DC endpoint; broaden GPU list; pod for batches |
| workersMax zeroed by balance guard | babysitter re-PATCH; real fix = billing top-up |
| Async status narrated, not polled | rule: no "running/landed" without a same-turn status call |
| Draco unreadable in audit/Blender | gltf-transform decode step |

## 8. Alam 3D — build order (each step verified before the next)
1. **Worker upgrade (free, today):** `pipeline_type='1536_cascade'`,
   `num_samples=3`, `texture_size=4096`, expose sampler params. Rebuild on
   pinned tag.
2. **Commit assembly stage as the standard post-process:** prop-fix →
   cabin assembly → (optional) wheel replacement → audit gate → only PASS
   assets publish, always with AI disclosure while generated.
3. **Rodin trial (on key):** same photos, fusion of front+side+rear;
   decides whether F1/F2 disappear. Baseline already rendered.
4. **Licensed base meshes (10–20)** for the premium tier — the only
   path to native A-grade; assembly stage still adds plates/colour/fit.
5. **Optional fine-tune** ("Alam 3D v1 weights"): only if Rodin disappoints;
   use the shipped `data_toolkit` + `ft1024` configs on licensed car meshes;
   fixes proportions/wheels at the weights level; still needs the assembly
   stage for glass/interior/doors.
6. **Doors (stage 2):** shutline cut + hinge on Rodin/licensed shells.

**Bottom line:** Alam 3D is not one model — it's the owned system:
open generation core (swappable, pinned) + owned assembly stage that
manufactures what no generator can (glass, interior, correct proportions,
clean wheels) + owned QC that refuses anything below the owner's bar.
Tonight's Scirocco proves the loop end-to-end: photo → generate → correct →
assemble → **PASS**.
