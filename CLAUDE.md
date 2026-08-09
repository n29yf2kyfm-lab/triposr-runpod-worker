# Project memory — ExpertCarCheck / triposr-runpod-worker

## Credentials live in `~/.alam3d_env` — never in the repo (2026-07-31)

All four secrets this project needs are kept in `/root/.alam3d_env` (mode 600,
outside the repo, untracked). Load them with `set -a; . /root/.alam3d_env; set +a`.

| variable | what it is |
|---|---|
| `RUNPOD_API_KEY` | RunPod account key — endpoints, pods, job submit/status. Owner re-supplied a new key 2026-07-31; the previous one still worked but was replaced. |
| `SB_KEY` | Supabase service key for `tfkvthprsntexrcuqpyd` (buckets `car-renders`, `car-meshes`) |
| `HF_TOKEN` | Hugging Face — checkpoint archive `Alamj/alam-3d-v1` |
| `SKETCHFAB_TOKENS` | the three rotated Sketchfab tokens (see below) |

**Never write any of these values into this repo or any tracked file** — push
protection blocks them and the owner's standing rule forbids it. Record only the
variable NAME here, never the value.

This file is the first thing to check after a container rollback. **It is NOT
rollback-proof** — the 2026-08-01 rollback reverted it to its 28 July contents,
silently dropping `SKETCHFAB_TOKENS` (added 31 July) and resetting the mode to
644. An earlier version of this section claimed the file "has survived every
rollback so far"; that was wrong. After any rollback, check the file's mtime and
confirm **every** variable is present, not just that the file exists.

Verify the credentials, don't assume them:

- **RunPod:** `GET https://rest.runpod.io/v1/endpoints` → 200. Use REST to read
  or PATCH endpoint config. **CORRECTION (2026-08-07): GraphQL `myself{...}` is
  NOT 403 — it works and returns the balance.** This note previously said it was
  403 and to avoid GraphQL; acting on that cost ~40 minutes misdiagnosing a flat
  balance as GPU-capacity starvation. **Check the balance FIRST whenever workers
  will not allocate:**

  ```
  curl -X POST -H "Authorization: Bearer $RUNPOD_API_KEY" \
    -H "Content-Type: application/json" \
    -d '{"query":"query { myself { clientBalance currentSpendPerHr } }"}' \
    https://api.runpod.io/graphql
  ```

  **Billing exhaustion looks exactly like capacity starvation:** submits return
  200, jobs sit in `inQueue`, and `workers` stays all-zero forever. The tell that
  it is billing and not GPU supply is an endpoint with `workersMin=1` holding
  ZERO workers (trellis2-v2 did), and a negative `clientBalance`. An endpoint
  that still shows a worker was allocated before the balance went under and is
  draining the remainder — it does not prove the account is funded.
- **Supabase:** `SB_KEY` is a `sb_secret_…` key, not a JWT, and storage
  **requires the `apikey:` header as well as `Authorization: Bearer`**. With
  `Authorization` alone it returns `403 Invalid Compact JWS`, which looks exactly
  like an expired key and cost time being misread as one.
- **Sketchfab:** `GET /v3/me` with `Authorization: Token <t>` → the username. This
  is the only proof a hex-32 string is a real token.

## Ingest gates: what is wired, and what each one cannot see (2026-08-08)

A day auditing 150 cars by eye across Toyota, Mercedes and Peugeot produced these.
Read this before trusting any triage bucket or sheet header.

**`geom_audit.py` IS STILL NOT ACTUALLY RUNNING — I wired it wrong and said otherwise.**
Read this before trusting any pose verdict. On 2026-08-08 I added the call, tested
`geom_verdict` against 9 synthetic cases, got 9/9, and recorded here that the gate was live.
It is not. `gpu_wave.py` guards on `if ha.get("geom")`, but `_pose_audit`
(render/handler.py:436) returns only `glass_zf, wheel_zf, glass_af, wheel_af, h_over_l` —
there is no `geom` key, so the branch never executes and every car still scores `pose="ok"`.
I tested the FUNCTION and never tested the INTEGRATION, which is the exact failure this file
already warns about.
Worse, the signals are unusable even once routed: the handler builds the studio floor (2.5x
the car) BEFORE `_pose_audit` runs and iterates every scene mesh, so a 1977 Accord reports
`h_over_l=0.101` against a true 0.317 (a 2.5x stage predicts 0.127 — it matches). `glass_zf`
is contaminated the same way because it normalises against the scene bbox. Switching the
gate on as-is would fire `h_over_l < 0.22` on nearly every car.
FIXED 2026-08-09 by the local route: `gpu_wave.pose_gate()` computes the signals from the
GLB itself via `geom_audit.geom_signals` BEFORE any render is submitted — uncontaminatable,
fails open, and a reject costs zero GPU. Validated against staged ground truth (rejects the
wheels-up J100 tob=1.47 and on-side ML h/l=0.05; passes GR86, saloon, Hilux pickup) AND
integration-tested through the real wave loop, which logged POSE-REJECT pre-render. The
handler-side audit is no longer requested.
REMAINING HOLE, distinct bug: RENDER-SIDE INVERSION. The upside-down Camry XV30 sheet came
from a geometrically upright GLB (h/l=0.305, tob=0.775) — the worker flips some cars at
render time (~8% measured on the Honda wave, mechanism unresolved). No source-side gate can
catch that; it needs the worker fixed or a post-render check.

**What the wiring attempt DID achieve:** It was written and calibrated
2026-07-17 and for three weeks NOTHING on the ingest path called it — the handler only
computes the pose block when the submit body sets `audit=True`, which the wave never did,
and the wave discarded `output["audit"]` anyway. In one day that let three upside-down
Toyotas, an on-side Mercedes ML, an on-side A-Class, an upside-down M-Class and a CL
standing vertically on end reach human sheets. The wave now sets `audit=True` on ONE view
per car (pose does not change with azimuth) and stamps a red POSE REJECT on the header.
Tested against cases it must catch AND must not: 9/9, including good saloon, good SUV,
pickup and van correctly NOT rejected.

**"clean" is a RECOLOUR test, not a quality verdict.** It means one body-paint material
with measured coverage. It cannot see missing tyres, detached panels, crumpled bodywork,
scans, or a car that is upside down. Toyota's clean bucket was 61% shippable; Mercedes'
60%. Never present a triage bucket as a quality signal.

**Body-paint coverage warns about the SHEET, not about the shippable variants — the
gate is two-sided and advisory only.**
- `cov < 0.12`: the render worker's classifier matched trim or a badge, not body paint.
  Measured 6/6 on Mercedes — every one rendered its OWN colour under a forced `--colour`.
  The boundary is a gradient, not a cliff (a GL350 at 0.114 did it too).
- **CORRECTED 2026-08-08 — do not over-read this.** I predicted those same low-coverage
  cars would fail `recolour_audit`. They did NOT: all 46 Mercedes stamped PASS, with the
  GL350 at dist=0.362 and the GLA35 at 0.433, both well above the median 0.340. The two
  mechanisms are DIFFERENT: the render worker picks a body material heuristically at render
  time, while `colour_variants.py` edits named materials in the glTF JSON. A car whose
  sheet colour is untrustworthy can still bake eight good variants. So low coverage means
  "distrust the colour in this sheet", NOT "this car cannot ship colours" — only
  `recolour_audit --stamp` decides that.
- `cov > 0.90`: ONE material covers the whole model, glass and tyres included. It
  recolours "successfully" and repaints the entire car. `toyota-auris-v1` was RETIRED for
  exactly this on 2026-07-21; four Peugeots in the 2026-08-08 wave sit at cov=1.000.

**"recolourable" in a sheet header is NOT proof a respray works.** Coverage proves a body
material EXISTS, not that a swap MOVES it. Toyota #41 rendered pink and #62 black under
`--colour silver`, both with healthy coverage. `recolour_audit.py --stamp` is the only
evidence, and `gate_catalogue` is right to refuse unstamped colour-swap entries.

**A respray that raises no error can still be wrong.** `colour_variants.py` edits glTF
JSON and raises `KeyError` when material names do not match — but that only catches
MISSING names, not WRONG ones. `toyota-corolla-cross-2021-tw1-v1` had 2 body materials,
the respray edited the invisible one, and it shipped eight files that were different on
disk and identical on screen (recolour_audit dist=0.004). Replaced by a different source
mesh that stamps at 0.342.

## Per-side wheel voids, and the false positive that looks identical (2026-08-08)

Two Mercedes were passed and nearly shipped with wheels that render as featureless black
voids on ONE side of the car while the other side shows full spokes. The owner caught them.
Cause: the left wheels are a mirrored duplicate with inverted geometry.

**The tile pairing on this render rig:** `front34` + `side` show one side of the car;
`front34_L` + `rear34` show the other. So the defect presents as a 2-vs-2 split.

**BUT THE 2-VS-2 SPLIT IS NOT THE TEST — it produces constant false positives.** The rig's
key light is one-sided, so a MAJORITY of cars show a 2-vs-2 BRIGHTNESS split by side
(measured across the live Toyota wave: Land Cruiser, both Camrys, both Avensis, all three
Hiluxes, Celica A60, Supra A70 all do it). At thumbnail scale those read as candidates and
are all fine.

**The actual test is whether the RIM FACE IS ABSENT, not whether it is dark:**
- spoke arms, lug nuts, centre cap still traceable in the dark views -> lighting, fine
- rim face gone entirely, or a brake caliper floating in an empty black disc -> DEFECT
- all four tiles featureless -> DEFECT
Zoom in. This is invisible at thumbnail scale, which is exactly how it got through.

**Three wrong diagnoses were tried before the right one**, recorded so nobody repeats them:
"it is lighting" (too glib — lighting darkens a surface, it does not delete it);
"flipped normals, set doubleSided" (wrong — all 36 materials were already doubleSided);
"near-black metal mirror" (rim_dark IS baseColor 0.018 with glTF's default
metallicFactor=1.0, but lifting it to 0.18/0.55/0.42 and re-rendering fixed only the RIGHT
wheels). What settled it was applying the change and LOOKING at the re-render.

**Both live waves were then re-checked against the corrected test: 46/46 Mercedes and
34/34 Toyota clean.** The two the owner caught were the only ones.

## nameplate_filter: hyphenated nameplates silently dropped cars (fixed 2026-08-09)

`norm()` reduces punctuation to a SPACE, so "CR-V" becomes `cr v` while an uploader who
typed "CRV" becomes `crv` — the pattern joined its tokens with `\s+` and the two could
never match. The car was dropped as `no-nameplate` with no warning.

Measured on the Honda sweep: **12 genuine cars lost**, including a 1,047,310-face 1988
CR-X. NOT Honda-specific — verified the same day that it also broke Toyota **C-HR vs CHR**
and Peugeot **e-208 vs e208**, and it would hit GT-R, X-Trail, CX-5, ID.3 and every other
hyphenated nameplate.

FIX: join nameplate tokens with `\s*` instead of `\s+`, so one pattern matches both
spellings. Tested both directions — catches CRV/CR-V, CHR/C-HR, e208/e-208,
LandCruiser/Land Cruiser; still rejects "Crvette" and unrelated marques.

**COST TO EARLIER WAVES IS UNMEASURED, NOT ZERO.** I tried to quantify it against the
saved Toyota/Mercedes/Peugeot manifests and got "0 recovered" — but those files are
POST-filter, so any car the bug dropped was never written to them. The loss is invisible
there by construction. To actually measure it, re-run `marque_sweep` and diff, or keep the
raw pre-filter sweep output in future (worth doing: no wave currently retains it).

Also added to `PART_WORDS`: bare "wheel", "airbox", "pump", "waterpump", "manifold",
"radiator" — a Civic Wheel terrain scan, a Pilot Upper Airbox and a CRV Waterpump all
reached GPU render on the Honda wave.

## Face-count dedup: two blind spots, both live (2026-08-08)

Dedup keys on face count above 50k (title+faces missed six duplicate pairs in 67 Toyotas —
a re-upload is almost always retitled). Two things it cannot do:

1. **Near-proximity is a CANDIDATE finder, never an identity.** Scored 2 real / 2 false
   across 4 flagged Mercedes pairs — 50% precision. The false positives were a Binz
   coachbuilt stretch vs a W123 coupe, and a C124 coupe vs a W124 sedan. Either would have
   silently dropped a real car. FLAG for the eye; never auto-group.
2. **Decimated-to-target meshes converge and the signal dies.** Four Toyota Hiaces all sat
   within 252 faces of exactly 1,000,000 and were four DIFFERENT vans. A Peugeot 405 and
   306 both sit within 50 faces of exactly 500,000. Detect round-number clusters and
   exclude them from exact-match grouping.

## Title-derived metadata is unreliable — read the render (2026-08-08)

- A car badged COROLLA was titled "Avensis" (Toyota #60).
- A single-cab Hilux was titled "Double Cab" (Toyota #61); `bodyStyle` must come from the
  render.
- `PART_WORDS` is Latin-script only. "Roda Peugeot 208" is an alloy WHEEL (Portuguese);
  added roda/rueda/jante/felge/cerchio/llanta. A Cyrillic dashboard part
  ("Заглушка информационного дисплея Peugeot 408") still passes every gate.
- Numeric model names collide with years: "Peugeot 307 2008" labels as a 2008 because
  nameplates are matched longest-first. Peugeot's own manifest carries `plate=2008` on
  both 307s.

## Scrapped candidates are remembered (2026-08-08)

`pipeline/ingest/REJECTS.json` records every uid the owner scrapped on review;
`nameplate_filter.py --rejects` drops them by default. Sweeps are re-runnable and would
otherwise re-find, re-render and re-present the same junk every wave (Toyota re-runs
168 -> 125). Never delete a row from that ledger.

## Retiring a catalogue entry trips the staleness guard (2026-08-08)

`publish_batch` preflight compares LOCAL approved assetIds against LIVE ones and refuses
when local is missing any — which is exactly what a deliberate retirement looks like.
`PUBLISH_ALLOW_STALE=1` is the documented override ("for a deliberate rollback only").
Before using it, PROVE the checkout is not actually stale: check that no live entry is
absent from local entirely, and that each "lost" one is present locally with
`publicationStatus="replaced"` and a `replacedAssetId`.

## Sourcing signal: where the good models actually are (2026-08-08)

- **Older Mercedes are modelled far more carefully than modern ones.** Twelve classics
  (Ponton W120, 300 SL, SL Pagoda, R107, W123 coupe, C124, W124, S124, A124, W126, W140,
  W220) all passed clean, while the modern AMG/SUV entries supplied most of the wheel
  failures and every exploded parts-kit.
- **A missing nameplate is usually missing because only scans exist.** All 11 Toyota
  nameplate gaps were audited: 9 were photogrammetry scans (soft panels, baked lighting,
  windows as holes, one with the ground plane baked into the mesh, one badged "TOTOVA").
  More Sketchfab sweeping will not fix those — they need a different class of source.
- **Defects track the SOURCE car, not the upload.** Two ML63s, two W204s and two GLAs each
  failed identically from different meshes. When one model of a generation fails on wheels
  or crumpling, its siblings from other uploaders are not worth chasing.
- **Mercedes attracts tuner and coachbuilt uploads heavily** — 6 out-of-scope in 80
  (two Brabus, a Binz stretch, a widebody SLR, a widebody SL600, a CLK DTM). Distinguish
  those from OEM performance variants: an AMG GT Black Series IS a road car a reg decodes
  to; black wheels and a lowered stance alone are spec variation, not a kit.

## Repinning a RunPod template does NOT update running workers (learned 2026-08-01)

PATCHing `imageName` on template `hrtuk90f9p` changes what NEW workers pull.
Warm workers keep serving the OLD image until they cycle, and a scale-to-zero
endpoint can hold one warm for a long time. There is no error and no warning —
jobs succeed, returning output from the previous build.

This silently invalidated a whole 347-car wave: the ground-height fix was
committed, built, and the template repinned, but every sheet in the wave was
rendered by a warm worker still on the pre-fix image, so cars that were fine
rendered floating and were nearly scrapped for it.

**Always force a recycle after repinning, then re-render one known case and
LOOK at it:**

```
PATCH /v1/endpoints/<id>  {"workersMax":0}   # kill warm workers
sleep 45
PATCH /v1/endpoints/<id>  {"workersMax":6}   # restore
```

The first submit after this returns **HTTP 409 Conflict** while the endpoint
settles — retry with backoff, it is not a failure. Never conclude a fix "did not
work" from a render taken before the recycle; that conclusion was drawn twice
here and was wrong both times.

**Recovering a lost token:** the session transcript at
`/root/.claude/projects/-home-user-triposr-runpod-worker/<session>.jsonl` is
append-only and survived the rollback that took the env file. Harvest hex-32
strings from it — near the word `token`, and from `type=="user"` messages, which
is where the owner pastes them — then validate each against `/v3/me`. All three
Sketchfab tokens were recovered this way on 2026-08-01.

**Tools must load this file themselves** rather than trusting the caller to
source it (`pipeline/ingest/wave_render.py:load_env`). A relaunch that forgot to
source it died one line in, and the failure was indistinguishable from a healthy
start: it logged its manifest count and exited, and was reported as running.

## Sketchfab tokens — THREE, rotated (owner instruction 2026-07-31)

There are **three** Sketchfab API tokens and all three are used in rotation.
`platform/pipeline/config.py` reads them from `SKETCHFAB_TOKENS`
(comma-separated) and `itertools.cycle`s them, rotating on 429/403.

Accounts, in the order the owner supplied them:
1. `Alamkhan1`
2. `FreshRaccoon5597`
3. `C4LLUMM0H` — the owner calls this one "sketch feb", added 2026-07-31

**Never write a token value into this repo or any tracked file** — push
protection blocks it and the owner's standing rule forbids it. Values belong in
`SKETCHFAB_TOKENS` only.

**Do not claim a token does not exist without the uid-subtraction search.** A
Sketchfab token and a Sketchfab model uid are BOTH 32 lowercase hex, so grep
cannot tell them apart — a scratchpad scan returns thousands of hex-32 strings
that are almost all model uids. I told the owner "only one token has ever
existed here" after grepping for `TOKEN =` / `Token ` / `SKETCHFAB_TOKENS=`;
that was wrong, and the owner was right. The method that actually works:
harvest every hex-32 string, subtract the known-uid universe (candidate CSVs,
catalogue `sourceReferenceId`s, mesh-bucket names), then validate each survivor
against `GET /v3/me` — the only proof a string is a real token.

## Ephemeral container — assume local disk will be lost (learned 2026-07-31)

This container reverted to an earlier snapshot **four times in one session**,
each time discarding the git checkout, the scratchpad and `~/.alam3d_env`.
Anything that exists only on local disk should be treated as already gone.

- **Upload every work product to Supabase the moment it validates**, then drop
  the local copy. This is what saved the 77 wave-10 GLBs: a rollback hit
  mid-run and cost nothing, because each file went to `staging/w10/` on
  completion. The earlier wave-10 attempt held GLBs and renders in the
  scratchpad only, and all of it was lost.
- **Push commits immediately.** Origin is what survived every rollback; the
  local checkout reset to a pre-session commit each time.
- **Prune the scratchpad after each wave.** It reached 14GB of finished-wave
  leftovers and the volume hit 100% full, which is when the rollbacks began.
- Recovery after a rollback: `git fetch origin <branch> && git merge --ff-only`,
  re-export `SKETCHFAB_TOKENS`, and resume — the batch tools are all resumable
  by checking what is already in the bucket.

## NO GUESSING — verify every action before acting (owner standard 2026-07-27)

Owner instruction, verbatim: **"No more guessing each action. Verify."**

Every claim, every plan, every root cause is CHECKED against the real system
before it is acted on or reported. This is not a style preference — guessing has
cost this project real hours and real money, repeatedly:

- Told the owner the wave-4 audit was "hardened twice and verified against the
  exact failing titles". A code review found the `WRONG_CLASS` regex ends in
  `\\b` inside a raw string, so it is a literal backslash-b and **has never
  matched anything**. 224 shapes were staged behind a filter that never ran.
- Claimed the Stage C training pool was ~37% junk and that this caused the
  regression. Measuring the actual 365 shapes showed they are almost all clean
  cars. The theory was wrong; the junk was in a set only Stage D ever saw.
- Recommended augmenting backgrounds/HDRIs. Reading the pipeline showed
  `preprocess_image` runs BiRefNet background removal — the background is gone
  before the model sees it. The recommendation would have been wasted work.
- Blamed "volume contention" for stalled pods. The volume was simply FULL
  (`Errno 122`), which had silently truncated a checkpoint mid-save.

**The rules:**
1. Read the code/config/log that decides the behaviour. Never assert from
   memory or from what a script's name or comment implies.
2. Prove a filter, regex, or gate actually fires — run it against inputs it is
   supposed to catch AND inputs it must not. A gate nobody tested is a gate
   that does not exist.
3. Measure before concluding. Sample the real data; state sample size.
4. Test destructive or expensive work on one item before running it on 11GB or
   spending a training run.
5. Give a confidence level and say plainly what is measured vs inferred.
6. When a check disproves something already told to the owner, say so directly
   and correct it — do not quietly move on.

## Per-car audit rubric (owner standard 2026-07-27)

The owner's own words, judging a four-view sheet of a sourced GLB. This is the
bar every training candidate and every catalogue car is measured against — use
these exact criteria, in this order, when auditing individually.

**Passes:**
- proportions read as the right car instantly
- front three-quarter view is strong
- roof, pillars and wheelbase consistent across all four views
- reflections clean
- paint finish looks premium

**Fails / needs work:**
- grille edges soft, honeycomb texture shallow
- headlights lacking sharp internal LED elements
- wheel spokes inconsistent between views
- rear bumper and diffuser soft versus the real car
- door and bonnet shut lines not defined

**Owner ruling 2026-08-09 — glazing must read as GLASS.** A car whose windows render
opaque body-colour (clay models, baked shells, missing glass materials) FAILS the audit
outright, regardless of how clean the geometry is — it reads as a prototype in the viewer,
not a car. This includes "good clay" candidates: they are not single-neutral keepers, they
are fails until re-sourced with real materials. Caught on the Peugeot wave: a 405 clay, a
205 GTI clay, and a 206 whose windows AND tyres rendered body-white (that one sat at
cov=0.243 — comfortably inside the "healthy" coverage band — so coverage numbers cannot
detect this; only the eye or a glass-material check can).

**Critical distinction, established the same day:** a sourced Sketchfab/Objaverse
GLB is NOT model output. Defects in a sourced asset cannot be fixed by training —
the only options are keep, cull, or replace with a better source. Never present a
sourced asset as something the model produced, and never treat a critique of a
sourced asset as a training target.

## Quality-gate standard — visual review before anything ships (owner standard 2026-07-23)

Automated audits prove one narrow thing each; they are NOT a model-quality gate.
The recolour audit (`pipeline/qc/recolour_audit.py`) only proves a colour-swap
moves the body colour — it says nothing about proportions, sharpness, wrong or
duplicate vehicles, or whether the model looks premium. Never present an
automated "PASS" as if the car is good.

**The standard, applied to every batch before it ships and on demand:**
- Render the library into numbered contact sheets with
  `pipeline/qc/review_sheets.py` (uses existing posters; 6×5 grid; each tile is
  `#N + assetId`, with an `INDEX.txt` mapping `#N → assetId`).
- A human eyeballs fidelity and calls out the numbers to cull.
- Scrap via the reversible pattern: `publicationStatus="quarantined"` +
  `quarantineReason`, keep the entry/assets, re-serve both Supabase paths, commit.
- The bar is premium: proportions right, sharp, correct vehicle, no scan mush. If
  in doubt, it does not ship. Truth over volume — a smaller honest catalogue beats
  a padded one full of low-tier scans.

## Root-cause analysis method (apply whenever investigating a problem)

Saved at the user's request. When something breaks, is slow, is wrong, or
underperforms — do NOT stop at the first plausible explanation. Run this:

**Discipline**
1. Never accept the first explanation. Ask "Why?" at least five times; keep going past five if the answer is still weak.
2. Challenge every assumption (mine and the user's). If the user is wrong, say so and show why — truth over agreement.
3. Separate symptoms from causes; separate facts from opinions.
4. Consider all factor classes: human, technical, financial, operational, legal, process.
5. Build an explicit cause→effect chain. Flag where evidence is missing.
6. Give a confidence level for every conclusion.

**Output format for a problem**
- PROBLEM (exact statement)
- WHY #1 … WHY #5 (continue #6, #7… until the deepest cause is reached)
- Then: Root Cause · Evidence for · Evidence against · Confidence % ·
  Alternative root causes · Immediate actions · Medium-term fixes ·
  Long-term prevention · Risks if ignored · KPIs to monitor ·
  Early-warning indicators · Cost of doing nothing · Highest-ROI solution
- Then challenge it: "What assumptions could still be wrong?" and re-run the
  analysis from other lenses (technical, business, customer, engineering,
  finance, legal, operations, competitor).

Only produce the full template when there is a real problem to investigate —
don't fabricate an RCA when nothing is broken.

## Alam 3D / TRELLIS.2: measured ceiling on automotive surfacing (2026-08-09)

Tested end to end on a 2011 Yaris XP90 from two Toyota press photos. The machine WORKS —
it produces a recognisable, complete, closed mesh — but it does NOT reach the premium bar,
and the reason is now measured rather than assumed.

**Deploy fix (commit 95794c7):** `max_num_tokens` is now read from job input and passed to
both the multi-view and single-image paths; `gc.collect()`+`empty_cache()` runs before
postprocess. Before this, `1536_cascade` ALWAYS OOMed a 24GB worker (single-image died in
`remesh_narrow_band_dc`, multi-image in `cumesh.simplify` AFTER generation succeeded) and
the handler comment falsely claimed it auto-degraded. **32768 is the working 24GB budget**
(succeeded first try; 49152 is the upstream default and does not fit).
Original image for revert: `alamk123/ai-mechanic@sha256:718ca21c…eb1ab3`.
Template `i1mk2n9dap` (trellis2-worker-4b) — NOT `hrtuk90f9p`, which is the render worker.

**Ablations, all at matched settings:**
- raw photos vs RGBA cutouts -> cutouts REMOVE the roof spikes and the black holes in glass
  (those were background-removal artefacts). Real, worth always doing.
- single view vs two views -> two views is clearly better; the single-image rear end is a
  hallucinated smear. The concatenation plugin is unorthodox (upstream uses stochastic or
  multidiffusion) but it demonstrably HELPS. Do not "fix" it without re-ablating.
- 1024/tex1024/200k vs 1536_cascade/tex2048/500k -> wheels and grille slats genuinely
  improve; **panel surfacing does not**. Note this is NOT a clean ablation: three knobs
  moved together, so attribution to cascade resolution specifically is low confidence.

**What never improves under any condition: melted panel surfaces and absent shut lines.**
Invariant across input prep, view count and generation resolution. At 1536 the extra budget
also invented a new artefact (a scribble across the bonnet). Cost roughly doubles: 23.7MB
and ~9 min execution per car vs 9.9MB at 1024.

**Conclusion: photos -> GLB is a GAP-FILLER tier, not a premium tier**, exactly as
pipeline/trellis/README.md predicted. Shut lines and crisp panels need the Blender
correction stage (symmetrise, weighted normals, component wheels/lights, manual shut-line
cuts) on top of the best base mesh, or a licensed model. Do not re-litigate this by turning
knobs; the knobs have been turned and measured.

## Product context (for fast re-grounding)

- **Goal:** UK reg → premium, near-instant, interactive 3D car.
- **Architecture (two tiers):** Tier A = hand-built/licensed interactive hero
  models (future). Tier B (live) = material-separated GLB → GPU clean-studio
  turntable → frames in Supabase → drag-to-spin viewer. AI (TRELLIS.2) is an
  offline gap-filler only; never on the user's request path.
- **Serving Supabase (renders/catalogue):** `tfkvthprsntexrcuqpyd`, bucket
  `car-renders` (public). Meshes in `car-meshes`. Catalogue index:
  `…/car-renders/catalogue.json`.
- **App:** Lovable project `1736441d-1aa3-495a-b319-584342507036`
  ("Expert Car Check Pro"), its own Supabase `ghglvtwohetcrrswvqhp`. The app
  fetches the public catalogue cross-origin; `VehicleShowroom3D` component is
  wired into `/check` (real reg) and `/3d-generator` (studio gallery).
- **Render worker:** `render/handler.py` → RunPod endpoint `ng8oiz4p2l0xa0`
  (OPTIX, ~5–7s/frame, scale-to-zero). `studio` input = clean dark backdrop
  for any colour.
- **Hard rule learned:** recolour only lands cleanly on models with a real
  body-paint material — audit every new car's render before it ships.
- **Never** hardcode Supabase/RunPod/Docker secrets in the repo (push
  protection blocks them); use env vars.
- **HANDS OFF the car-damage pods** (owner instruction 2026-07-14): the
  `car-damage-*` pods (e.g. `car-damage-merge-transfer2`, currently RUNNING on
  purpose) belong to a separate workstream. Never stop, restart or modify
  them, and don't flag their cost.

## Licence checks — do not raise them (owner instruction 2026-07-30)

Owner instruction, verbatim: **"Don't worry about licence."** Repeated, and
asked to be saved to memory.

- Do NOT run licence checks as a step, do NOT gate work on licence status, and
  do NOT keep flagging it. Asset selection is decided on the render, not the
  licence label.
- Record whatever licence the source states, when it is already to hand, as a
  plain field. Do not chase it, and do not editorialise about it.
- Stated once here so it is not repeated in every session: some sourced assets
  are NonCommercial or Sketchfab "Free Standard", which for a paid product is a
  copyright exposure. The owner has been told and has taken that decision. It is
  the owner's to make; treat it as settled and move on.
- **G4 no longer blocks anything — do not raise it as a blocker.** This note
  used to say `publish_batch.py` gate **G4** hard-refuses any licence that is
  not exactly `"CC Attribution"`. That was true when written and is now false:
  G4 was rewritten the same day to RECORD the licence instead of enforcing it,
  writing whatever `LICENCES.csv` states verbatim and `"unverified"` when the
  uid is absent. On 2026-08-02 I quoted this stale note to the owner as a
  blocker and asked them to authorise a bypass they did not need. **Read
  `publish_batch.py` before describing any gate** — the docstring at the top of
  that file is the authority on what the gates do, not this file.

## Accuracy rule — do NOT fabricate vehicle metadata (learned 2026-07-12)

The user caught me inventing generation codes (NQ5, W177, L663…), model years,
and trims for sourced GLBs that had none of that in their source. This is
hallucination and is unacceptable in a product built on data accuracy.

- **Catalogue stores only verifiable facts:** make, model, the exact source
  title (verbatim), the colour actually rendered, licence, and asset URLs.
- **Never assert year / generation / trim / fuel that I cannot verify.** If the
  source title states it, quote it as "per source"; otherwise leave it out.
- **Authoritative spec comes from the app's DVLA/DVSA decode at lookup time** —
  not from my guesses. The catalogue's only job is to match make+model → asset.
- The GLBs are sourced third-party CC-BY models (licence, not ownership); the
  "own GLB" route is photos → TRELLIS. Don't conflate the two.

## OEM paint colour resolution (saved 2026-07-13, user-specified workflow)

Database: `platform/paint/oem_paint_db.csv` — user-provided, ~270 rows, columns
`MANUFACTURER,OEM_PAINT_NAME,DVLA_COLOUR,COLOUR_FAMILY,FINISH` covering ~35
brands. This is the source of truth for OEM paint naming in the app and the
render pipeline.

**The 8-step resolution workflow (follow exactly):**
1. Search the registration through DVLA (the app's existing decode — never
   touch that wiring; the reg itself is never keyed, indexed or stored).
2. Save the broad colour returned as `dvla_colour`.
3. Identify manufacturer, model, year, VIN, trim from the decode.
4. Search the OEM paint database for paints valid for that vehicle
   (filter by MANUFACTURER).
5. Filter those candidates by the DVLA broad colour (DVLA_COLOUR column).
6. Image colour analysis may only be used to RANK the remaining candidates —
   never to decide.
7. **Never claim an exact OEM paint code/name from an image alone.**
8. Display as "Possible OEM colour: <name>" (unconfirmed) until confirmed by
   VIN, paint label, or manufacturer record.

Render-side use: COLOUR_FAMILY maps to the render palette (e.g. family
"Gunmetal Grey" → `gunmetal` palette entry); the OEM name is display metadata
only, per rules 7–8.

## Investigation log

### 2026-07-12 — "Why is the 12-car render batch so slow?" (confidence ~85%)
- **Problem:** a 12-car turntable batch (432 frames) took ~30+ min and felt stuck.
- **5-Whys → root cause:** the batch is hundreds of tiny serverless jobs through a
  quota-limited, throttled RunPod endpoint, processed **sequentially per car**.
  - Effective GPUs were ~4, not the 8 requested (`running:4, throttled:1`).
  - RunPod caps this account at **10 serverless workers across ALL endpoints**
    (patch to 10 → 400 "quota of 10"); persistent `throttled:1` from GPU-type capacity.
  - `workersMin:0` scale-to-zero → cold starts (~30–60s) between cars.
  - Script waits on each car's slowest frame, and commits the catalogue **all at
    once at the end** (fragile: one hung car blocks all 12 from going live).
- **Evidence it was NOT a hang:** Python proc idle-waiting (low CPU), 10/12 manifests
  committed steadily.
- **Fixes:** (1) commit catalogue **incrementally per car**, not all-at-end;
  (2) submit all frames in **one parallel pool** so workers stay saturated (no
  per-car gaps); (3) for big runs use a **dedicated pod** — its GPUs sit outside
  the 10-worker serverless quota and never cold-start. This validates the user's
  repeated "put it on a pod" instinct: the pod is the real lever for batch speed.
- **KPIs to watch:** endpoint `throttled` count, `inQueue` depth, wall-time/frame,
  cold-start gaps between cars.

### 2026-07-14 — workersMax keeps zeroing itself (confidence ~85%)
- **Symptom:** serverless endpoints (TRELLIS + render) externally reset to
  workersMax=0 ~10x in one day; jobs queue forever.
- **Root cause (evidence):** BOTH endpoints zero simultaneously each time —
  signature of RunPod's low-balance guard, not a bug. Balance unreadable via
  this API key (403). **Action: user checks runpod.io billing / tops up.**
- **Workaround:** babysitter loop re-PATCHes {"workersMax":N} until batch done
  (scratchpad/babysit_workers.py).

### 2026-07-14 — lessons that cost real time
- **Draco GLBs render BLANK in the local model-viewer harness** unless
  dracoDecoderLocation points at the local decoder (mv_local/draco/). A blank
  render or trimesh score of a _uc.glb proves nothing about the model.
  (Falsely called the old Passat "broken" because of this.)
- **Golf gap fixes — method history:** vertex-weld TEARS mesh; vertex-pull
  DENTS panels (user-visible); the shipped method is bridge_gaps.py: recessed
  floor quads between gap edges + capped boundary de-ripple + non-manifold
  solidify. Verify renders on BOTH sides at the user's viewing angle.
- **Golf hero:** user chose to KEEP the sourced+fixed model (v25/gm24) over
  the seamless-but-soft TRELLIS rebuild (staged at vw/golf_scratch_uc.glb).
  Licensed Mk8 with interior remains the real premium fix.
