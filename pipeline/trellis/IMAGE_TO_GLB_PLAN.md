# IMAGE → GLB: the software plan

Written 2026-08-15 at the owner's request: *"software that can take a 2D image
and generate it to a 3D GLB file — plan it out, look at the previous sessions,
look at the tool research."* Everything below is grounded in what this project
has **measured**, not in vendor claims. Sources: `STUDY_3D.md` (the physics),
`MACHINE_PLAN.md` (the fine-tune route), `build_car.py` (the proven gate
chain), the Vizcom/SAM-3D/Hi3DGen research of 2026-08-14, and the owner's
rulings in `CLAUDE.md`.

---

## 0. The honest frame, first

The software can absolutely be built — most of it already exists in this repo
as tested pieces. What is **known and measured** is the quality ceiling:

| route | sharp_share | verdict |
|---|---|---|
| catalogue (sourced, human-made) | **18.6%** | the bar |
| owner's parametric v4 | 4.6% (crease 143) | best authored yet |
| our authoring machine | 3.4% | correct shape, soft |
| Hunyuan 2.1 / 2mv (generated) | 0.8–1.9% | melt |
| raw generated, pre-decimation | 0.4% | melt |

Physics, not opinion: a 3–5 mm shut line is **0.19–0.38 of one voxel** at every
open generator resolution — unrepresentable. Vizcom (the commercial leader,
$29–49/seat) says of its own output: *"~1 in 10 models are client-ready"* and
*"not CAD"*. So this software's honest job description is:

> **Image in → complete, gate-passing, structured GLB out — at gap-filler /
> preview tier. Premium stays sourced or licensed.**

Every stage below exists to make the output *correct* (materials, structure,
pose, names) even where it cannot be *premium* (surfaces).

---

## 1. What already exists (built and tested, this repo)

| stage | tool | status |
|---|---|---|
| capture gating | demo README contract (4+ views, MP floor) | spec exists |
| background removal | BiRefNet / manual cutouts | proven; contamination = spikes (measured) |
| shape generation | Hunyuan3D-2.1 (single) / 2mv (multi-view) | proven on pods, ~$1/car |
| part structure | PartCrafter canopy @16 parts + P3-SAM wheels/trim | measured split of labour |
| label transfer | `hybrid_transfer.py` v4 | glass 13.5% band, clear/proven |
| wheel replacement | `wheel_swap.py` + catalogue donors | proven |
| material scheme | `partcrafter_materials.py` / authoring materials | owner's rulings by construction |
| gates | `build_car.py` G1–G5 + `glass_probe` + red control | proven, caught real defects |
| pose / Y-up | `pose_fix.py` + boundary checks | proven |
| structured tree + named parts | `structured_car.py` (owner's spec) | proven |
| QC render | `prod_render.py` through the real rig | proven |

**The missing piece is not a stage — it is the orchestrator** that runs them as
one command with one folder in and one GLB out, plus the two untested levers
that could raise the ceiling (§3).

---

## 2. The software: `car-glb` (working name)

One command, mirroring the owner's demo README contract:

```
car-glb generate <folder>/ -o car.glb
    folder: front.png rear.png left.png right.png [f34 r34 roof]  + dims.json
```

### Pipeline (all local/RunPod, no third-party API — owner's rule)

```
A. CAPTURE GATE      reject weak sets before spending GPU money
     - >=2 views (front + rear minimum), warn below 4
     - resolution floor, same-car consistency check
     - dims.json REQUIRED (published mm) — pixels never set scale

B. PREPROCESS        cutouts; refuse dirty masks loudly
     (measured: background junk becomes roof spikes)

C. SHAPE             Hunyuan3D-2mv on the labelled views  (~$0.50, 5 min)
     - octree 380, the proven settings from the Yaris run
     - candidate upgrades gated in §3, drop-in replaceable

D. STRUCTURE         the measured split of labour:
     - PartCrafter num_parts=16 -> canopy label     (same input image)
     - P3-SAM on the shape mesh -> wheels/mirrors/trim
     - hybrid_transfer v4       -> labels onto the Hunyuan mesh

E. CORRECTION        wheel_swap (catalogue donors) · pose to Y-up ·
     scale to dims.json · owner's named part tree (structured groups)

F. MATERIALS         Material_0 / Glass_Tint BLEND / Tyre_Rubber /
     Rim_Alloy / Lamp_Lens — the scheme every gate keys on

G. GATES (fatal)     glass_probe clear/proven · glazing band 2.5–9.5% ·
     four corners placed · expected material names · red respray control

H. QC OUT            production-rig renders (4 az) + forensics numbers
     (sharp_share, crease_density) written next to the GLB
```

Delivery: `pipeline/carglb/` CLI. Stages C–D run on a RunPod A40 via the
hardened bootstrap pattern (preflight URL, torch pin, artefact asserts,
progress polling — all the paid-for traps from CLAUDE.md). Everything else is
local CPU.

### Cost & time per car
- GPU: ~$0.60–1.00 (shape + parts on one pod boot)
- wall time: ~15–20 min end to end
- build effort for the orchestrator itself: it is wiring, not research —
  build_car.py already proved the chain on staged files.

---

## 3. The two levers that could raise the ceiling (gated experiments)

Run BEFORE polishing the orchestrator — each is ~$1 and each has a hard gate:

1. **Hi3DGen** (open weights, normal-bridging — attacks sharpness at the
   conditioning stage, the one lever never tried).
   GATE: sharp_share ≥ 3% on a car (Hunyuan baseline 0.8%) else discard.
2. **4-view Hunyuan-2mv** (we only ever tested 2 views; Vizcom's whole
   contract is built on 4–6 consistent views).
   GATE: visibly better rear/side coherence than the 2-view Yaris, judged on
   the same sheet.
3. *(cheap third, optional)* **SAM 3D Objects** — open weights, but documented
   output is Gaussian splats; needs mesh conversion and is tuned for cluttered
   scenes. Lowest expectation; test only if 1–2 disappoint.

Whichever wins becomes stage C. If none clears its gate, stage C stays
Hunyuan-2mv and the ceiling statement in §0 stands confirmed.

**Explicitly deferred** (needs owner top-up + a decision): the 2.1 fine-tune
pilot on the 225 curated sharp cars. It can improve proportions and big
features; it can never produce shut lines (latent bandwidth + voxel maths).
Only worth $150–400 after levers 1–2 are measured.

---

## 4. What this software will NOT do — written down so it is never resold

- No shut lines, badges, grille texture or panel language at premium tier —
  those are below the representable bandwidth of every open generator.
- No likeness guarantee: proportions from dims.json + silhouette from photos,
  identity beyond that is not promised.
- No publication: output lands in `staging/carglb/`, and NOTHING ships without
  the owner's per-car sign-off (standing rule, 2026-08-14).

## 5. Decision points for the owner

1. Approve the two $1 experiments (Hi3DGen, 4-view)?
2. Approve building the orchestrator CLI around the proven chain?
3. The fine-tune pilot stays parked until 1 is measured — agreed?
