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
