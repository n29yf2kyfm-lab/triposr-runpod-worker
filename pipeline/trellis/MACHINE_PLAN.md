# The 3D Machine — two-month review and the plan to a shippable generated car

Written 2026-08-14 at the owner's request: "I just need a machine that can
produce perfect GLB 3D car with all my standards — glass clear, interior
perfect." Everything below is from the measured record (CLAUDE.md, staged
artefacts, render evidence), not from hope. Where something is unproven it says
so.

---

## PART 1 — What two months actually proved

### Solved. Finished. Do not reopen.

| Problem | Status | Evidence |
|---|---|---|
| Opaque glazing (the #1 killer: 119 of 1,154 live cars, ~80% of all audit fails) | **SOLVED** for any mesh entering our pipeline | `hybrid_transfer` + `assign_materials`: glass 13.5–13.7% of faces, `glass_probe` **clear/proven**, on the Golf all 5 gates pass |
| Body-coloured / white tyres | **SOLVED** | `wheel_swap` fits catalogue donor wheels with our own `Tyre_Rubber`/`Rim_Alloy`; red control holds |
| Respray (8 colour variants) | **SOLVED** | `respray_gltf` + `recolour_audit --stamp`; `body_probe` finds the true body material even under junk names (validated 6/6) |
| Nothing ships unchecked | **SOLVED** | `build_car.py` gates G1–G5, all thresholds measured from catalogue cars, integration-tested (caught a real over-glazing defect) |
| Wrong pose, converter-clay materials (sourcing side) | **SOLVED** | `pose_fix`, `clay_rebuild` — 13 cars published this week from sources that were being thrown away |

The material layer is genuinely done. It was never the thing that made the
generated car look bad.

### Not solved, and measured to be not solved: SURFACING

Owner verdict on the finished hybrid car, after every material gate passed:
**"It fukin look shit."** The record behind that verdict:

| Generator | Structure | Surfacing | Verdict |
|---|---|---|---|
| TRELLIS.2 (Alam 3D v1) | one fused part = 99.3% of verts | melted panels, no shut lines — **invariant across all 5 levers** (input prep, view count, resolution, seed, Blender correction) | SHELVED by owner 2026-08-09 |
| PartCrafter (16 parts) | **greenhouse separates** (13.6% canopy), wheels separate | melt, worse than TRELLIS | label source only |
| Hunyuan3D-2 | 100% fused, one component | **best of any open model tested** — formed mirrors, readable spokes — but no shut lines, blobby lamp recesses | shape source in the hybrid |
| P3-SAM segmentation | cannot separate glazing **by design** (it segments physical parts; glazing on a fused shell is a region) | n/a | wheels/trim cuts only — settled, do not retry |
| Hybrid (PartCrafter labels → Hunyuan mesh + wheel_swap) | all 5 gates pass | soft panels, no shut lines, melted front end | the "looks shit" car |

### Why every open model hits the same ceiling — physics, not tuning

Open image-to-3D models generate at **512–1024³ voxel-equivalent resolution ≈
8 mm per voxel on a 4 m car. A shut line is 2–4 mm.** The detail the premium
bar demands is *below the representational floor* of every open-weights
generator tested. This is why five different levers on TRELLIS and three
different generators all produced the same softness: it is not a settings
problem. The 1536³-class tier (Hunyuan3D 3.0/3.5, Hitem3D, Tripo/Rodin latest)
is commercial-API only.

**CORRECTION 2026-08-15 — "the 1536 tier is commercial-API only" IS NO LONGER
TRUE.** `TencentARC/Pixal3D` (SIGGRAPH 2026) ships **MIT-licensed weights on
HuggingFace**, runs a **1536 cascade** (1024 low-VRAM mode) and exports GLB
with PBR. Two reasons it is worth ONE gated test rather than a shrug:
  * it is built on the **TRELLIS.2 backbone we have already run**, changing the
    CONDITIONING — pixel back-projection lifting multi-scale image features
    into a 3D volume, instead of loose attention injection. Conditioning is the
    exact lever that produced this project's only measured tier change
    (Hi3DGen = TRELLIS + normal-map conditioning, crease 145 vs 37);
  * it therefore is NOT the "turn the resolution knob" experiment we already
    ran and closed.
Against it, from OUR OWN measurements: we ran TRELLIS.2 at `1536_cascade` and
recorded "wheels and grille slats genuinely improve; **panel surfacing does
not**". Resolution alone is necessary-not-sufficient on this exact backbone.
The project page publishes **no quantitative comparisons** — only hand-aligned
qualitative shots vs TRELLIS.2 and HY3D v3.1 — so "near-reconstruction-level
fidelity" is a claim, not evidence. Parts separation is not mentioned, so
assume a fused shell and expect `fit_panes` to refuse it (hollow-cabin guard)
and the hybrid path to be needed for glazing.
**Pre-registered gate before any adoption:** same Golf capture, measure
`crease_density` and `sharp_share` against the recorded ladder (Hunyuan-2.1
63.3 / Hi3DGen 92.4 noisy / our catalogue keepers 162–271). It must beat
**Hi3DGen's crease 145 / sharp_share 2.07%** on mesh_forensics AND survive the
eye, or the route stays closed. Est. cost ~$0.30–0.50, one pod.

### The interior standard — stated plainly

**No generator tested produces an interior.** Hunyuan emits a closed shell;
PartCrafter's body has window openings with a bare cavity behind them. An
exterior-photo model *cannot know* the interior. "Interior perfect" will never
come out of the generator — it has to be added by the pipeline (Part 2,
Phase 3) the same way wheels already are.

### What the machine is FOR (product context)

Tier B (sourced) is live and shipped 13 cars this week. AI is the **gap
filler** for cars sourcing cannot reach — the top UK gaps (Puma, Kuga,
Qashqai, XP130 Yaris) are scan-only on Sketchfab. The alternative for those
gaps is licensed models (~€1,000–2,600 for the top 20). The generation machine
only earns its place if a generated car passes the same per-car eyeball rubric
as a sourced one. A generated car that reads "AI" undercuts the whole
catalogue — the owner has already refused to ship one.

---

## PART 2 — The plan. Cheapest decisive test first, hard gate at every step.

Total cost to KNOW the answer: **under $50.** No step publishes anything;
owner eyeballs every output (standing rule 2026-08-14).

### Phase 1 — pick the base. SETTLED 2026-08-14, $0 spent.

Both candidates turned out to already have Golf artefacts in the bucket from
earlier runs (`staging/hybrid/hi3dgen_car.glb`, `hunyuan21/golf_gte_eval.glb`),
so the shootout was done locally from existing evidence — no GPU rented.
Three-way sheet: `scratchpad p1/base_shootout3.jpg`, quad_views rig.

| Base | Geometry | Trainability |
|---|---|---|
| Hi3DGen | most nose micro-detail (grille slats, badge) but NOISY: ragged window borders, fused blob wheels | **inference-only** (verified in repo), MIT, TRELLIS-adapted |
| **Hunyuan3D-2.1** | **best overall**: glazing separates with visible pillars, wheels with spokes, faint door lines, clean panels — far beyond 2.0 | **full training code released**, explicitly for community fine-tuning |
| Hunyuan3D-2.0 | smooth blob (the recorded baseline) | superseded |

**VERDICT: the base is Hunyuan3D-2.1.** Best geometry AND the only official
fine-tune path. Hi3DGen stays as a label/normal source if ever needed; do not
re-run it as a shape candidate.

**"Is there a Hunyuan 3 to clone?" — checked 2026-08-14, answer NO.** Tencent's
official HF org holds exactly: 1, 2, 2mini, 2mv, 2.1, Part, Omni. The 3.0/3.5
tier is API-only; weights never released. Two findings that support this plan:
Hunyuan3D-Part is itself tagged `finetune:tencent/Hunyuan3D-2.1` — Tencent
builds its own specialist models by fine-tuning 2.1, the exact move we are
making with cars. And our Phase 2a dataset is in Hunyuan's native training
layout, so if a 3.x ever opens (a standing revisit trigger) the dataset
transfers as-is. Hunyuan3D-Omni (2.1-based, control signals: point cloud /
bbox / skeleton) is parked as a possible later conditioning add-on.

### Phase 2 — OUR OWN MODEL: fine-tune open weights on our own catalogue

**Owner decision 2026-08-14: no commercial API in the loop. The machine must be
owned weights on our own RunPod.** The API tier is dropped from the plan.

What "own model" realistically means, stated once so it is never re-litigated:
- **Training from scratch is out.** The base models trained on 500k+ objects
  across GPU clusters for months. Not a £-thousands project.
- **Fine-tuning an open base on OUR cars is in**, and it is the one lever the
  record itself points at: shut-line engraving was deferred because "that fix
  belongs to Hi3DGen / car fine-tuning". The melt is not only resolution — it
  is also *generic-object priors*. A base that has seen a thousand clean,
  audited cars regresses toward crisp panels, round wheels, structured lamps.
- **The honest ceiling stays:** fine-tuning sharpens priors, it does not raise
  the architecture's resolution floor. If the pilot fails its gate, that is
  the answer for current architectures.

**The training asset we already own (counted 2026-08-14):** 1,026 approved,
audited, material-separated GLBs. This is exactly the (views → mesh) pair data
these models fine-tune on.

### ⚠ MEASURED 2026-08-14, BEFORE ANY TRAINING SPEND — the premise was half wrong

The plan assumed "our cars are crisp, generated cars are soft, so fine-tuning
teaches crispness". **Nobody had measured whether our catalogue actually carries
the detail we want taught.** `pipeline/trellis/crease_density.py` measures it:
total length of edges whose dihedral angle is 25–150°, divided by the bounding-box
diagonal (scale-free), i.e. how much genuinely sharp geometry a mesh contains.

| mesh | faces | crease/diag |
|---|---|---|
| Kia Sportage (ours) | 585k | **270.7** |
| Kia Picanto (ours) | 458k | **227.8** |
| Skoda Octavia RS (ours) | 674k | **162.1** |
| **Hi3DGen (generated)** | 523k | 92.4 |
| **Hunyuan3D-2.1 (generated)** | 665k | **63.3** |
| MG ZS (ours) | 1.13M | 47.9 |
| MG4 (ours) | 1.05M | 30.9 |
| Hunyuan3D-2.0 (generated) | 626k | 29.8 |
| MG3 (ours) | 894k | 12.0 |

**Three of six sampled catalogue cars carry LESS sharp geometry than what
Hunyuan-2.1 already generates.** Fine-tuning on those would teach the model to be
*softer*, not sharper. "Train on all 1,026" is therefore wrong and is struck from
this plan.

**The confound was tested and ruled out.** Coarse tessellation can fake creases
through faceting, and the raw numbers looked like that (the 458k Picanto scored
above the 1.13M MG ZS). Control: decimating MG ZS 1,133,062 → 280,498 faces moved
its score only 47.9 → 51.2 (+7%). Tessellation density does not drive the metric;
the spread is real geometric variation between cars.

**What this changes:**
1. **Phase 2a gains a CURATION step.** Score all 1,026 by crease density, keep the
   top slice (the Sportage/Picanto/Octavia band, ~4x the generated car), and
   train only on that. Cheap: the scorer is local and free.
2. **The headroom is real but narrower than assumed** — our best cars are ~4x the
   generated Golf, not "the whole catalogue is better".
3. ~~If the curated set turns out to be small~~ **RESOLVED — full sweep run
   2026-08-14, 1,019 of 1,026 scored (7 read errors):**

   | threshold | cars |
   |---|---|
   | crease ≥ 200 (3x the generated car) | **225** |
   | crease ≥ 150 | **365** |
   | crease ≥ 100 | 567 |
   | ≥ 63.3 (what Hunyuan-2.1 already generates) | 693 |

   The curated set is NOT small: the pilot's 200 best cars all sit at roughly
   ≥170, ~3x the base model's output. One in three catalogue cars would TEACH
   SOFTNESS if included — the curation step is confirmed necessary, and the
   training pool is confirmed sufficient. Full scores:
   `pipeline/trellis/TRAINSET_SCORES.jsonl`. Top scorers still need the EYE
   before training (the metric counts sharp, not good).

**Limit of the metric, stated so it is not over-read:** it counts sharp geometry,
not GOOD geometry. Hi3DGen scores 92.4 largely because it is NOISY (ragged window
borders — visible in the Phase 1 sheet). Curate with crease density AND the
existing audit/eye, never on the number alone.

**The exact training-data spec (read from the 2.1 repo, not guessed):**
per object `{uid}_sdf.npz` + `{uid}_surface.npz` + `{uid}_watertight.obj`
plus `render_cond/000..023.png` (24 posed views) + `transforms.json` — and
**their `tools/` directory generates all of it from a raw mesh**, so we run
their preprocessor over our GLBs rather than inventing a renderer. Training
enters at `main.py` / `train_demo.sh`; an overfitting config and an 8-case
mini-trainset exist for smoke-testing; stated minimum is 10GB VRAM (default
recipe is 8-GPU DeepSpeed, a pilot does not need that).

**Phase 2a-0 — trainer smoke test: PASSED 2026-08-14, ~$1.05 total.**
`SMOKE_OK` on attempt 8: the loop ran 24 capped steps on their mini-trainset on
one H100-class GPU and wrote a real 10.28 GB checkpoint
(`ckpt-step=00000020.ckpt`). Seven prior attempts each died inside 3 minutes by
design (~$0.12 each) and every fix is permanent in
`pipeline/trellis/hy21_smoke.sh`, which the pilot inherits:
  1. `timm` undocumented; latest transformers self-disables on torch 2.4 → pinned 4.46.3, check made fatal
  2. `pythreejs` (mesh-log callback chain) → full static import scan replaced pod-by-pod discovery
  3. pymeshlab needs `libopengl0` — the DOCUMENTED hybrid-deploy trap, missed on first pass
  4. matplotlib/scipy/pandas/skimage/sklearn are NOT in the runpod image — assumed wrongly
  5. their single-GPU branch sets `strategy=None`; PL 2.x demands `'auto'` (their own comment)
  6. `training_step(optimizer_idx)` is PL 1.x era — exactly two signatures, patched
  7. custom logger callbacks have PL 1.x hooks → dropped from config (guarded in main.py; ModelCheckpoint unaffected)
Also fixed mid-campaign: `set -x` traced the service key into a PUBLIC bucket
log on attempt 1 — deleted, uploads now run with xtrace off, owner advised to
rotate SB_KEY.

**Phase 2a — preprocess OUR cars with THEIR tools:** pilot slice first — the
~200 best cars (~$2–8), full 1,026 (~$10–40) only after the pilot gate passes.
Output is the ExpertCarCheck training set in 2.1's native layout: durable,
owned, reusable.

**Phase 2b — fine-tune pilot (~$150–400):** the 200-car set, single node.
**GATE:** same Golf reference through base 2.1 vs pilot, side by side at 5× —
panels crisper, lamp structure appears, shut lines begin to read. Any doubt =
fail.

**Phase 2c — full fine-tune (~$500–2,000):** only after 2b passes its gate,
all 1,026 cars, the production checkpoint becomes **Alam 3D v2 — our weights,
our RunPod, no API.**

**Money, honestly:** balance today is ~$24.52. Phases 0/1/2a fit it; 2b/2c
need a top-up. No training spend starts without the owner seeing the 2b
number first.

### Phase 3 — the interior, in parallel (pipeline work, $0 GPU)

The proven pattern is `wheel_swap`: donor geometry + our own materials. Same
move, bigger part:

1. Harvest a **cabin kit** (dash + front seats + wheel + console) from 2–3
   catalogue donors that have real interiors (hatch, saloon, SUV variants).
2. Scale-fit the kit into the generated shell's cabin volume (cabin bounds are
   already computed by hybrid_transfer's canopy/beltline logic), dark
   fabric/plastic materials of our own.
3. **GATE:** through the 0.72-alpha glass at studio zoom the cabin reads as a
   real interior (seats + dash silhouette, no empty shell); magenta backlight
   still resolves interior structure — the same test the glazing ruling uses.

This also upgrades REPAIRED sourced cars whose interiors are weak — it is not
generation-only work.

### Phase 4 — only after a Phase 1 or 2 pass: the scale test

5 target-gap cars (Puma, Kuga, Qashqai, XP130 Yaris, Corsa) through winning
shape stage + finisher + cabin kit. Owner eyeballs all 5 sheets against
sourced-car sheets from the same wave. **Ship only what the owner approves,
car by car.** If 4/5 read as catalogue-grade, the machine is real; wire it as
the standing gap-filler.

### Decision tree (one screen)

```
Phase 1: Hi3DGen vs Hunyuan on the Golf ─▶ pick the BASE model
                       │
Phase 2a: render our 1,026-car dataset (owned, reusable)
                       │
Phase 2b: fine-tune PILOT on ~200 best cars
     gate: base vs pilot at 5× — crisper? shut lines appearing?
     │pass                                │fail
     ▼                                    ▼
Phase 2c: full fine-tune = Alam 3D v2    Own-model route CLOSED on current
(our weights, our RunPod, no API)        architectures. Budget → sourcing
     │                                   (13 cars/week proven) + licensed
     ▼                                   top-20 (~€1k–2.6k). Re-test on
+ finisher + cabin kit                   triggers below.
     ▼
5-car scale test (Puma, Kuga, Qashqai, XP130 Yaris, Corsa)
     ▼
owner eyeballs all 5 — ships or kills, car by car
```

### Revisit triggers (do not re-test before one of these)

- an open-weights model released at ≥1536³ effective resolution
- a part-native generator trained on vehicles (PartCrafter-class, car dataset)
- Hunyuan3D open release closes the gap to its commercial tier

### Standing constraints that bind every phase

- **No publish without owner sign-off** (2026-08-14, hard rule)
- Glazing verdict from the FILE (`glass_probe`), never the sheet or poster
- The eye outranks every numeric gate; sheets are candidate finders
- Do not reopen: material-layer work, P3-SAM-for-glazing, TRELLIS knob-turning,
  clay-recovery of the 64 scrapped live cars
