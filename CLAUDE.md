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

## RENDER-SIDE INVERSION: the mechanism, found at last (2026-08-11, Mazda wave)

This file has carried "the worker flips some cars at render time (~8% measured on the
Honda wave, mechanism unresolved)" since 2026-08-09. It is resolved, for at least this
class, and it is a rounding tie.

`render/handler.py:981-1008`. The glTF importer converts Y-up to Blender Z-up, so a
correctly authored car can arrive with its LENGTH on Z. The auto-upright fires
(`uext[2] > 1.25 * max(uext[0], uext[1])`), rotates 90 deg about X to lay the length
down, then asks whether the car "landed on its side" with:

    if min(range(3), key=lambda i: ext2[i]) != 2:      # roll 90 deg about Y

Mazda 2 (DY) 2003, uid 55e34299, after that first rotation measures
**X 201.748, Y 411.622, Z 202.624**. X and Z differ by **0.4%**. argmin picks X, the
test concludes the car is on its side, and it rolls a correct car ONTO its side. The
sheet shows the roof from above in two tiles and the floor pan from below in the other
two. geom_audit passes the source mesh, correctly - the GLB is fine.

**DETERMINISTIC**: the extents are a property of the file, so the same wrong axis is
chosen on every render. Re-rendering cannot fix it -> `fail-rerender`, never a scrap.
Any car whose width and height are near-equal after the first rotation is a coin flip.

NOT fixed during the wave on purpose: the worker image is shared with concurrent waves
and repinning mid-flight silently invalidates their in-progress sheets (see the
warm-worker note below). The fix is to require a MARGIN before rolling - roll only when
`ext2[2] > 1.1 * min(ext2)` - and to prefer the axis that puts the wheels on the ground.

## Bare-digit nameplates: qualify them with the marque (2026-08-11, Mazda)

Mazda 2 / 3 / 6 are single digits. Both of the obvious approaches are measurably wrong,
in OPPOSITE directions, and the fix is the same one word either way.

**A bare digit in `nameplate_filter` is wrong both ways.** Measured on the real
235-row sweep:
- FALSE POSITIVES from digits that are not the nameplate: "1973 Mazda 1000 2-Door Sedan"
  and "Mazda Protege5 - Remake Test 2" both matched the Mazda 2 - off "2-Door" and off
  "Test 2". "Mazda MX-6" matched the 6; "Mazda MX-3" and "Mazda RX-3" matched the 3.
- FALSE NEGATIVES on the GLUED spelling, which is Mazda's own badging: `\b3\b` cannot
  match "Mazda3" because there is no word boundary between "mazda" and "3". Genuine
  "Mazda3" and "Mazda2 014" rows were dropped as no-nameplate.

**Write the nameplate as `Mazda 2`, `Mazda 3`, `Mazda 6`.** `build()` joins tokens with
`\s*`, so one pattern matches "Mazda 3", "Mazda-3" and "Mazda3", and the marque prefix
makes a stray digit impossible. It also cannot reach 323/626: the trailing `\b` fails
between "3" and "2". Verified in both directions on the live sweep.
Then add the OTHER real cars explicitly - MX-3, MX-6, RX-3, Protege, Mazdaspeed - rather
than relying on a bare digit to sweep them up.

**`uk_priority` needed the same treatment, via a new `_PHRASE` list checked before
`_OVERRIDE`.** The three `("mazda","6"/"3"/"2")` entries that used to sit in `_OVERRIDE`
tested marque and nameplate INDEPENDENTLY, which measurably mis-tiered:
  "Mazda 2 1.3"       -> T2 as a Mazda 3, off the ENGINE SIZE. Ordering 6/3/2 does not
                         help; the collision is with the displacement, not between digits.
  "Mazda 3 1.6"       -> T3 as a Mazda 6, same way.
  "Mazda6 Wagon 2018" -> T4, because `_tok_hit("mazda6","6")` is false, so every glued
                         spelling fell behind the MX-5s this file exists to hold back.
  "Mazda Xedos 6"     -> T3 as a Mazda 6. Different car.
Requiring the digit to be ADJACENT to the marque (`\bmazda\s*6\b`) fixes all four at
once and needs no ordering trick. 48/48 on Mazda cases it must catch and must not,
11/11 no regression on other marques.

**Rule of thumb: a nameplate that is a bare digit, or an ordinary word, is only
trustworthy adjacent to its marque.** Independent marque+plate tests are not enough.

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

**RESIDUAL GAP, measured 2026-08-10: write nameplates WITH their separator.**
`\s*` bridges tokens, so it only helps a nameplate that is already multi-token.
A nameplate written as one GLUED token cannot match a separated title:
  nameplate `E6`   -> matches "BYD E6", MISSES "BYD E-6"
  nameplate `E 6`  -> matches BOTH (and still rejects Handbrake/Sealant/Attorney)
An agent reported this as affecting "GT-R, CX-5, ID.3, e-208" and that is WRONG
-- those contain a hyphen, `norm()` turns it into a space, and they are already
multi-token, so they match both spellings today (verified). The rule is simply:
**never write a nameplate as a glued alphanumeric token.** Write `E 6` or `E-6`,
`F 3` or `F-3`. Both forms work; only `E6` fails.

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

## `paintMaterialNames` is BLENDER's name space, not the glTF's (2026-08-11)

`mat_audit` runs on the render worker, i.e. inside Blender, so the names it records
are Blender IDs. `respray_gltf.py` edits the glTF JSON and matches literally, and the
two name spaces disagree in two measured ways:

- **Blender invents `.001`/`.002` siblings.** `C1_Paint.001` was recorded against a glTF
  holding a single `C1_Paint`; `pan_paint.002` against a file holding only
  `pan_paint.001`; `CarPaint.001` against a file holding `CarPaint`.
- **Blender truncates at 63 characters** (`bpy.types.ID.name`'s cap).
  `…_2021Coloured_Materia` was recorded for a real `…_2021Coloured_Material`.

The symptom is `respray failed: "materials not present in <file>: [...]"`, which reads
like a bad audit and is actually a name-space mismatch. FIXED by
`respray_gltf.resolve_names`, which is deliberately narrow so it cannot widen paint onto
trim: an exact hit stops there, and only an unmatched name falls back to its `.NNN` base,
then `.NNN` siblings, then a prefix **only** at exactly 63 chars. It still raises when
NOTHING resolves — painting nothing would ship eight identical files.

**Do not "fix" this by relaxing the raise instead.** The raise is the only thing standing
between a no-op respray and eight identical GLBs; what makes the resolver safe is that
`recolour_audit --stamp` still renders and measures the result downstream.

## `pgrep -f` matches the harness wrapper — a wait loop can never exit (2026-08-11)

Every Bash tool call runs inside a wrapper shell **whose command line contains the
command text**, so `pgrep -f 'bash /tmp/foo.sh'` matches any tool call that merely
mentions that string — including the very wait loop doing the matching:

```
until ! pgrep -f 'bash /tmp/big_chain.sh'; do sleep 20; done   # never exits
```

Measured: the bake chain exited at 10:27 and both waiters (the chained
`after_bake.sh` and a `run_in_background` `until` loop) were still spinning 17 minutes
later against two wrapper shells. Nothing was wrong with the work; the guard was
matching itself. This is the same failure class as `supervisor.sh`'s `running()`.

Guard against it: match a pattern the wrapper cannot contain (`pgrep -f
'^python3 -u pipeline/…'`), or better, derive terminal state from an artefact — the
log's last line, a DONE file, an exit-code marker echoed by the script itself
(`echo "STAMP_STAGE_EXIT=$?"`), and wait on THAT. `supervisor.sh:reconcile` already
does this for the same reason.

Related trap already paid for: `pkill` on a broad pattern has killed this session's own
shell (exit 144) more than once. Kill by PID.

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
4. `NZM1` — supplied 2026-08-09 when the first two hit their download quota

**CORRECTION 2026-08-09: the file held only TWO tokens, not three.**
`FreshRaccoon5597`'s token was lost in a rollback and is NOT recoverable from this
machine — proven, not assumed: 3,409 unique hex-32 strings across 1,528 files, minus
the known model-uid universe, every survivor validated against `/v3/me`. Only
Alamkhan1 and C4LLUMM0H came back. It has to be regenerated from the account.

**Throttling is PER-ACCOUNT, not per-IP.** This was measured the hard way: with both
original accounts returning 429 on `/models/<uid>/download` while `/v3/me` returned
200 for both, I told the owner it looked IP-wide and that another token would not
help. That was WRONG — the owner supplied NZM1 and it downloaded 4/4 immediately.
More accounts DO buy more download quota. The quota window behaves like hours, not
minutes: the two exhausted accounts were still 429 more than two hours later.

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

**THE AUDIT SHEET IS STRUCTURALLY BLIND TO GLAZING DEFECTS (found 2026-08-11).**
Do not judge glass from a wave sheet. `render/handler.py` matches material NAMES against
`(glass|window|windscreen|windshield|screen|vidro|glas|scheibe|fenster)` and forces
`transmission=1.0, alpha=1.0, IOR=1.45` plus the studio tint onto every match — the comment
at handler.py:130 states it outright: "the worker OVERRIDES whatever glass material the GLB
ships with, so the GLB has no say". A car whose glazing is fully OPAQUE therefore renders
PERFECT CLEAR GLASS in its sheet, provided the material happens to be named glass-like.

This is stronger than the evidence rule above. For tyres the sheet is a weak witness; for
glass it is no witness at all. It also explains why clay shells DO show opaque windows —
their glazing carries a non-matching name (carpaint, Meshpart1Mtl, dummy_material_13), so
no override fires and the truth shows through. The defect is invisible exactly when the
model is otherwise well-built.

Measured on Porsche: 8 of 107 cars that had been passed with an explicit "glazing
transparent" reason are actually opaque. Six had name-matched glass materials, so the
worker manufactured the clear glass those reasons described; two were clay shells misread.

The test that works, in order of cost:
  1. glTF probe (free, decisive): pull the JSON by HTTP Range and check the glazing
     material for `alphaMode` BLEND/MASK, a baseColorFactor alpha below 1.0, or
     `KHR_materials_transmission`. Zero transparent materials in the file = opaque.
  2. Magenta-backlight render of the SHIPPED GLB: an emissive plane behind the car;
     transparent glazing glows magenta, opaque glazing stays body-coloured.
Judge "clear vs faded" only from these. Under backlight, genuinely heavy glazing
(alpha 0.78-0.94) still resolves interior and far-side openings — on Porsche the shipped
files were bimodal, either properly transparent or not transparent at all, so "faded"
came out zero.

**Owner ruling 2026-08-09 — glazing must read as GLASS.** A car whose windows render
opaque body-colour (clay models, baked shells, missing glass materials) FAILS the audit
outright, regardless of how clean the geometry is — it reads as a prototype in the viewer,
not a car. This includes "good clay" candidates: they are not single-neutral keepers, they
are fails until re-sourced with real materials. Caught on the Peugeot wave: a 405 clay, a
205 GTI clay, and a 206 whose windows AND tyres rendered body-white (that one sat at
cov=0.243 — comfortably inside the "healthy" coverage band — so coverage numbers cannot
detect this; only the eye or a glass-material check can).

**EVIDENCE RULE, learned the expensive way 2026-08-10: the wave audit sheet is NOT a
valid witness for a MATERIAL defect. Judge from the SHIPPED asset.**
39 live cars were quarantined tonight on sheet evidence (12 Fiat by me, 27 by an agent)
and ALL 39 were restored after re-checking the shipped asset. Nothing was actually wrong
with them.

Why the sheet lies: the render worker picks a body material HEURISTICALLY at render time
(this file already warns of that for colour) and on these cars it repainted the tyre. The
signature is an INVERTED PAIRING -- the sheet shows a white tyre on a dark hub while the
shipped glb has a dark tyre on a white hub. Seen identically on peugeot-205-pw1-v1 and on
all 12 Fiats.

Why the shipped glb is decisive for wave entries: fw1-era entries have posterUrl and
turntableUrl NULL, and platform/resolver/index.ts:207 hands desktopGlbUrl straight to the
viewer. No render worker sits between the asset and the customer, so for those entries the
glTF material IS what a user sees. Poster-backed waves are different -- there the poster is
the shipped artefact and is the thing to judge.

The hierarchy of evidence, best first:
  1. the published poster, where one exists (what customers actually see)
  2. a LOCAL Blender render of the shipped glb, plus the baseColor of the material bound to
     the tyre RING GEOMETRY (not merely a material *named* "tire")
  3. a coloured-body control: on a blue/red/tan car a body-painted tyre wears the body hue,
     so a NEUTRAL dark grey tyre proves innocence with no brightness argument at all
  4. a magenta cross-check: rewrite the tyre material and re-render; if the tyre changes,
     that material really is on the tyre
  5. the wave audit sheet -- CANDIDATE FINDER ONLY, never a verdict

Two rig traps that produced false failures during this exercise:
- Blender 4's default AgX view transform plus inherited light energies CLIPPED a tyre to
  pure white. The magenta control came back pastel pink, which is what exposed it. Use
  Standard, scale the lights, and verify numerically (a 0.22 world background must land
  near sRGB 130, 0% clipped) before trusting any render.
- A Y-up assumption rendered a Y-down glb upside down. Measure camera orientation from the
  wheels.

**The one tyre defect that IS real, and how to detect it without a render: the FLAT
SHELL (found 2026-08-10 across Honda/Peugeot/Nissan).** Some shipped GLBs have every
material set to ONE identical `baseColorFactor` — `tire`, `windowglass`, `clearglass`,
`chrome`, `black` and `carpaint` all the same value (seen at 1.0, 0.8 and 0.588). The
material NAMES survive; only the colours are gone. Nothing in the file is dark enough to
be rubber or transparent enough to be glass, so the car renders as a uniform clay: tyres
in body colour, windows opaque. 14 live cars carried it.

Detect it from the glTF JSON, not from pixels — this is immune to every rig trap above:
`len({tuple(baseColorFactor) for untextured materials}) == 1` and `minL >= 0.4` and no
`alphaMode != OPAQUE`. Check the textures are only number plates before calling it; a car
with real textures (peugeot-406-pw1-v1 has 22) can still be flat, but one where a texture
feeds the tyre or glass is not.

**The colour variants do NOT rescue it.** `colour_variants.py` rewrites only the body
material, so `<asset>__grey.glb` is a coloured body on the same flat white shell —
verified on four of them. And a good POSTER does not clear it either: the render worker
substitutes glass and spares tyres by name, so peugeot-2008-v1 has a perfect published
poster and a flat clay GLB. Where posterUrl/turntableUrl are null the resolver hands
`desktopGlbUrl` straight to the viewer, so the flat shell is exactly what the customer sees.

**Owner ruling 2026-08-09 — TYRES MUST READ AS BLACK RUBBER. This is a SEPARATE check
from glazing and it is the one the audit kept missing.** A car whose tyres render in body
colour FAILS: the paint material covers the rubber, so the car reads as an unfinished clay
studio model and no respray leaves black tyres.

The owner caught this on the Citroen BASALT sheet, and it was systematic — a re-check of
all 32 published Fiats at high zoom found **12 more**, which had to be quarantined after
going live. Read why it slipped through, because the mechanism will repeat:
- BASALT PASSED both documented checks. Its glass is genuinely transparent (interior
  visible at 3x zoom) and its rim faces are all present. The rubric named glazing and
  rim-voids; nothing told the auditor to look at tyre COLOUR, so nobody did.
- **Coverage is not merely blind to it, it is anti-correlated.** The 12 quarantined cars
  sit at cov 0.20-0.26 (inside the "healthy" band) while `Fiat_147` at cov=**1.000** has
  correctly black tyres. Never screen for this with cov or mats.
- **Do not try to automate it with pixel darkness.** That was tried and DISCARDED as
  invalid: the wheel crop contains the black backdrop and the floor reflection, so a
  "darkest pixel" probe returns 0 suspects for every car — it measures the background.
  A metric that confidently says "all clear" is worse than no metric.
- **A genuine WHITEWALL is not this defect.** Fiat Abarth 695 has a white sidewall ring
  with black tread — authentic period detail, correctly kept. The failure is the WHOLE
  tyre, tread included, in body colour.

Method that works: crop the side view's wheel region, upscale ~2x, and look. Compare
against a known-good car in the same batch — a correct one shows plainly black rubber
against the white body.

**CORRECTION 2026-08-10 — "the paint material covers the rubber" is NOT the only
mechanism, and on the Mercedes wave it is not the mechanism at all.** The retroactive
Toyota+Mercedes audit found seven mw1 Mercedes whose tyres render white. Controlled
re-renders of the same staged GLBs in RED, at az 270 and az 215, show the tyres staying
WHITE on a red car, and the worker's `recolour.materials` payload lists only
carpaint/paint0 — the paint never touched the tyre. The failure is per-CORNER: the same
car renders one white tyre and one black one from a byte-identical dark tyre material
(`tire`, baseColor 0.106, dielectric, roughness 0.9) and identical wheel geometry to a
sibling that renders black on all four. Points at the wheel meshes (normals), not paint.
Only `mercedes-benz-g-class-2018-v1` was the literal ruling — its live poster renders the
tyres in body BLUE.

Three traps this cost time on, all worth avoiding next time:
- **The RED re-render is the decisive test, and it is cheap.** Render the staged source
  GLB with `--colour red`: body-colour tyres go red, defect tyres stay white, good tyres
  stay black. It cost four renders to overturn a wrong verdict I had already written down.
- **The per-corner asymmetry is what separates a defect from a WHITEWALL** — and this
  matters, because a MAJORITY of pale-tyre suspects turn out to be whitewalls. Eleven cars
  (W123 coupe, Ponton, 190SL, Pagoda, R107, Avensis, Camry XV40, Celica A60, both Hiluxes,
  Land Cruiser 90) read as white tyres in the PURE PROFILE view and every one shows a
  plainly black tread in the 3/4 view. Judge the tread face in front34/rear34, never the
  sidewall in the side tile.
- **Material data is not a verdict either.** Passing and failing cars in this wave carry
  identical tyre materials and identical wheel prims, so a glTF probe cannot separate them
  — and a mid-grey tyre under the rig's one-sided key reads as pure white at thumbnail
  scale. It takes 5x AND a same-scale known-good control in the same image.

**Critical distinction, established the same day:** a sourced Sketchfab/Objaverse
GLB is NOT model output. Defects in a sourced asset cannot be fixed by training —
the only options are keep, cull, or replace with a better source. Never present a
sourced asset as something the model produced, and never treat a critique of a
sourced asset as a training target.

## Glazing and tyres: what the glTF probe can and cannot settle (2026-08-11, Mazda)

The probe is now the primary witness for both material rulings, and it earned that on
this wave. Three extensions and three limits, all measured.

**Extensions made 2026-08-11 (re-validated against PORSCHE_GLASS.json, 105/107 -> 106/107):**
- **Specular-glossiness materials keep colour in the EXTENSION.** `2019-porsche-911-gt3-rs`
  is entirely `KHR_materials_pbrSpecularGlossiness`, so `pbrMetallicRoughness` is absent
  and `baseColorFactor` fell back to the [1,1,1,1] DEFAULT - a ground-truth CLEAR car
  scored "opaque", which under the owner ruling is an outright FAIL. The probe was culling
  a good car off a value the file never states. Read `diffuseFactor` too. specGloss is
  legacy but common in older and JDM-market uploads, which is what a Mazda sweep is full of.
- **Interior trim can be WINDOWY.** `Airconditioningbuttonwindscreenventilationicons1Mtl`
  is a dashboard icon sheet containing "windscreen", so it was promoted to sole decider of
  that car's glazing. Same class as the lamp-lens bug, one level in. `TRIMMY` now excludes
  icon/button/instrument/dash/aircondition and mirror/rearview - the last of which also
  stops the Jaguar wave's `glassSideMirror` outvoting real glazing. Deliberately NOT
  excluding "interior": `interior_glass` is real glazing.
- **`glass_texture_alpha.py` (new) measures the alpha CHANNEL.** The probe reads FACTORS,
  so `alphaMode=BLEND` + `baseColorFactor` alpha 1.0 + transparency in the texture is all
  it can band "faded". Two Mazda FLEET cars sat in that band and are both properly
  transparent: Mazda 6/Atenza Sport `windows_glass` 128x128 LA at opacity 0.25, and
  Mazda CX-5 2020 `Index_0_2` 1024x1024 RGBA at opacity 0.36. A factor-only reading put
  both at risk.

**Whether the SHEET is admissible depends entirely on the material NAME.** The worker
overrides `transmission=1.0` onto any glass-matching name, so for `windows_glass` the
sheet's clear glazing is manufactured and worthless as evidence - but a car whose glazing
is called `Index_0_2` or `Meshesmadziocha...` gets no override, and there the sheet is an
honest witness. Check the name before deciding whether you are allowed to look.

**Three things the glazing probe still cannot settle on its own:**
1. A misspelt name. Mazdaspeed 3 (BK) spells its glazing `Windiow`; the only glass-NAMED
   material was `glass_surr`, the window SURROUND, correctly opaque. The probe degraded to
   "ambiguous" and routed it to the eye rather than failing a good car - which is the right
   behaviour, and why "ambiguous" must never be treated as a fail.
2. Alpha just under 1.0. A Mazda CX-5 KE ships `Glass` at BLEND alpha **0.986** - 98.6%
   opaque, a near-black solid panel - and the sheet shows perfect clear glass because the
   material is literally named "Glass". Banded "faded" and culled. The Porsche calibration
   is the yardstick: 0.78-0.94 still resolves interior, 0.986 does not.
3. A car that is transparent EVERYWHERE. `glass_probe` says "clear" for a Mazda 5 and a
   Mazda 8 MPV whose every material is BLEND at alpha 0.25 including `carpaint` and `tire`
   - true, and beside the point. The separate body/rubber-opacity check catches it. This
   GLOBAL-ALPHA SHELL was found on the Volvo wave the same day and is **not marque-specific**:
   both Mazda cases carry the identical 0.25 signature and the same carpaint/tire/chrome
   naming. The sheet header gives it away independently as `body mats=0, cov=0.000`.

**THE WHITE-TYRE RENDER ARTEFACT IS NOW PROVEN, not argued.** CLAUDE.md already said the
sheet is a candidate finder only. Here is the clean experiment: #28, #29 and #30 of this
wave carry a **byte-identical** tyre texture (512x512, mean sRGB 53.3) plus an `EXT_Rubber`
material at ~0.015, and on the same rig in the same run **#29 renders it BLACK while #28
and #30 render it WHITE**. Same data, opposite outcome. The rig is the variable; the
shipped assets are sound.
Separately, #11 and #12 carry byte-identical `tire` at baseColor **0.106** - the same value
recorded on the Mercedes wave - and again one renders black and one white.

**And the 1x read was wrong THREE times in this wave.** On the Mazda 3 Mk1, the CX-5 2020
and the Mazda 6 GG the thumbnail showed a white wheel and 5x showed a plainly dark tyre
band around a light rim. Zoom before writing anything down. A same-batch known-good control
in the same image is worth more than any brightness argument.

**Cheapest decisive order for a tyre verdict:** (1) the tyre material's baseColorFactor in
the shipped glTF; (2) if it is textured, EXTRACT the texture and take its mean - the Jaguar
XF precedent, and it is what settled #28/#30 here; (3) 5x crop of the tread face in
front34/rear34 against a same-batch control; (4) a red control render. Never the 1x sheet.

## A glTF TYRE probe cannot work. Measured, 0/8. Do not build it again (2026-08-11)

Written for the Mercedes retro-audit to run this file's own "cheapest decisive order for a
tyre verdict" steps 1 and 2 automatically. `pipeline/ingest/tyre_probe.py` reads the tyre
material's `baseColorFactor` and, when textured, extracts the texture from the BIN chunk by
HTTP Range and takes its mean. Then it was validated against `retro_tyre_audit.json` -- 131
live cars whose tyre verdicts were settled by RED control re-renders, live posters and 5x
crops, the strongest ground truth this project has:

    ground truth "tyre-fail"  (8 cars) -> 0 caught      RECALL 0/8
    ground truth "ok"       (108 cars) -> 13 flagged    FALSE ALARMS

**Zero recall. Not low -- zero.** Five of the eight real failures carry a genuinely DARK
tyre material (`tire` 0.106, `rubber` 0.012, `tire` 0.008) which the probe reads correctly
as black; the other three name no tyre material at all. This is the same finding as
"passing and failing cars carry identical tyre materials", reproduced from the other side.
There is no regex and no threshold that fixes it -- the defect is a per-CORNER render
artefact in the wheel meshes and the rig, and the material table does not contain it.

The file is kept as an EVIDENCE RECORDER with this result in its docstring so the next agent
does not rebuild it. A "black" reading rules out the body-paint-over-rubber and flat-shell
mechanisms for that car; it does NOT clear the car of the per-corner defect. Say which.

Two bugs found while validating, both of which MANUFACTURED failures out of missing
measurements, and both worth knowing for any texture reader:
- textures behind `KHR_texture_basisu` / `EXT_texture_webp` keep the image index in
  `texture["extensions"][ext]["source"]` and may omit `texture["source"]` entirely, so a
  plain `t["source"]` raises `KeyError`. Two Toyotas were unreadable and therefore "pale".
- an unreadable or absent texture must score UNKNOWN, never "opaque". The factor on a
  textured material is a MULTIPLIER and is `[1,1,1]` on nearly all of them, so treating a
  failed read as opaque white invents a tyre failure.
The ranged BIN read was verified byte-exact against a full download (mean sRGB 23.4 both
ways) -- it does not pull whole meshes, so it is cheap enough to use for evidence.

## Cross-reference every wave PASS against QUARANTINED sourceReferenceId (2026-08-11)

Defects track the SOURCE car, not the upload -- this file already says so, and the Mercedes
wave showed what it costs to not act on it. **8 of the wave's 70 clean passes were the exact
source uid of a car already quarantined live**: the CLK 55 AMG, an SLS AMG, the GLS, the
X-Class, the C-class S202 estate and three of the W124 family. Six had been pulled for white
tyres and two for the per-side wheel-void fault. Every one of them passed the wave audit
cleanly, because the wave audit re-derives quality from the sheet and the glTF and neither
of those carries the defect that got the car pulled.

**Make this a standing step before any CLEAN list is handed over:**

```python
byuid = {}                       # sourceReferenceId -> catalogue entries
for e in catalogue:
    if e.get("sourceReferenceId"): byuid.setdefault(e["sourceReferenceId"], []).append(e)
# then for each pass: any entry with publicationStatus == "quarantined" is a hard hold
```

`REJECTS.json` only records what the owner scrapped at REVIEW; it does not record what was
quarantined after going live. The catalogue is the other half of that ledger and nothing was
checking it. Also worth reporting from the same join: how many passes are already live under
an existing assetId (30 of 70 on Mercedes), because "70 keeps" and "32 genuinely new meshes"
are very different numbers to hand someone.

## glass_probe: texture-alpha is not evidence of OPACITY either (2026-08-11, Mercedes)

Re-validated against `PORSCHE_GLASS.json` before the Mercedes retro-audit, as this file
requires. It scored 103/107 and **three of the four misses were in the dangerous direction**
-- ground-truth-CLEAR cars banded "faded", which is a cull.

The last one standing was the mirror image of the bug the texture-alpha extension was
written to fix. `Porsche 911 GT3 RS (semester 2)` (5fd62615) names no glazing at all and its
only transparent materials are `UV6_TX`/`UV4_TX`, BLEND with 27 textures and factor alpha
1.0. The final fall-through treated "no glazing name AND no factor-transparent material" as
OPAQUE, so texture-alpha transparency was counted as evidence of opacity. It is ground-truth
CLEAR. Now returns **"ambiguous"** -- which must be routed to the eye and never failed, and
which `glass_texture_alpha.py` resolves. 106/107, sole miss in the safe direction.

**Two naming traps this wave added, both of which would have culled good cars:**
- **A misspelt nameplate is not a missing one.** A GL350 (live AND in the wave) spells its
  glazing **`Widnwos`**, alpha 0.947 BLEND, genuinely transparent; its only glass-NAMED
  material is `GlassParts1Mtl`, the window SURROUND, correctly opaque. Same class as the
  Mazdaspeed 3's `Windiow`. The probe degrades to "ambiguous", which is the right behaviour.
- **`backlight` means the REAR WINDSCREEN as often as it means a tail lamp.** `LAMPY`
  matches "light" and so eats `backlight_glass`. On `mercedes-benz-a-class-2018-w12-v1` the
  only plain window material is opaque and the only transparent ones are `backlight_glass`
  at 0.25 -- so whether that car has real glazing turns entirely on which sense is meant.
  Genuinely undecidable from the file; it needs a backlight render. Do not fail it.

**Scale of what this gate catches on a pre-ruling marque:** 77 of 196 Mercedes wave
candidates have opaque glazing, 57 proven, and **64 of the 66 hard material fails carry a
glazing name that matches the worker's override list** -- so their sheets render perfect
clear glass and always did. Eight cars the 2026-08-08 Mercedes audit PASSED are hard
material fails on this evidence. Always record, per car, whether ANY material name matches
the handler's regex: it decides whether the sheet is admissible for glazing at all. On
Mercedes only 36 of 196 sheets were.

## Read the material NAMES, not just their numbers (2026-08-11)

A Mazda 5 in this wave has clean geometry, correctly black tyres (`tire.001` at 0.01) and
genuinely transparent glazing - and it is a CARTOON CHARACTER. Its material list holds
`mouth.001`, `Iris.003`, `eye_cornea` and `eyePupil` alongside `body.car`. The grille is a
pair of pink lips and the windscreen carries eyes. It would pass every numeric screen in
the pipeline. Worth adding eye/mouth/iris/pupil/lips to a future name gate.

## OWNER RULING 2026-08-11: do NOT chase clay-shell recovery

64 live cars were found to be clay shells -- correct geometry, every material
colour flattened, no glass and no rubber. 23 of them share the IDENTICAL value
0.588 across unrelated marques, which is the fingerprint of one pipeline step
rather than 64 bad sources, so they looked recoverable: fix the step, re-run,
get the cars back.

The owner was offered that and declined. **They are scrapped. Do not reopen it.**
Do not trace the flattening step, do not attempt to re-derive the materials, do
not propose it as a next step in a future session. If those cars are ever wanted
again the answer is to re-source them, not to repair them.

(The diagnosis is kept here only so nobody re-investigates from scratch: the
material NAMES survive intact -- body, glass, chrome, tire_mat3, interior, rims --
while every baseColorFactor is one flat value. 23 at 0.588, 7 at 0.8, 20 with the
factor absent entirely. bmw-x1-v1 is the clean example, and its poster shows a
glossy blue glazed car because the render worker rebuilds one from the names.)

## OWNER RULING CONFIRMED 2026-08-11: opaque glazing is a SCRAP, even when the poster is perfect

Put to the owner explicitly, with the 119 affected cars rendered and numbered, and
confirmed: **scrap.** Not a borderline call to be relitigated next wave.

The 119 were the hard case ON PURPOSE. They are properly built cars -- real paint,
black tyres, chrome, headlamp internals -- and their studio posters look flawless.
They fail only because the glazing is OPAQUE in the shipped glTF. The owner was
shown exactly that framing (restoring them would have taken the catalogue from
1,014 back to ~1,133) and chose to keep them out.

So the rule for every future wave is unambiguous:
  * glazing verdict comes from the shipped glTF, never the poster or the sheet
  * `verdict == "opaque"` with `certainty == "proven"` is a hard fail
  * `"ambiguous"` is NOT a fail -- route it to the eye (this has saved good cars
    repeatedly: a misspelt `Widnwos`, a `Windiow`, an infotainment TOUCHSCREEN
    matching /screen/, and lamp lenses voting when no glazing is named)
  * a beautiful poster is not a counter-argument. The render worker forges clear
    glass onto any material whose NAME matches its regex, which is the entire
    reason this defect survived every audit before today.

Scale, for calibration on a fresh marque: 119 of 1,154 live cars (10.3%) failed on
this alone -- roughly 80% of all audit failures. Expect a similar share anywhere
the glTF has never been probed.

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

## PartCrafter TESTED on a real car (2026-08-12): parts yes, glazing NO

Ran PartCrafter end to end on a RunPod A5000 against a clean 3/4 render of
golf_mv_polished. It WORKS and it is genuinely part-native -- but it does not
solve the blocker that matters. Measured, with renders, not inferred.

**Result (num_parts=10, rear 3/4 input, 172s inference):**
  * 10 SEPARATE meshes + a combined object.glb. Contrast TRELLIS.2, where one
    part is 99.3% of the car. Largest PartCrafter part = 67.9%, with 7 more
    substantial parts. Part-native generation is real.
  * WHEELS SEPARATE CLEANLY -> this alone solves the tyre defect: assign dark
    rubber to the wheel meshes and the paint can never cover them.
  * **GLAZING DOES NOT SEPARATE.** A per-part colour render shows the entire
    greenhouse -- windscreen, side windows AND roof -- fused into the 67.9% body
    shell, exactly like TRELLIS. Isolating the two parts my classifier hopefully
    labelled "glass" (4.4% each) rendered the FRONT WHEELS.

So PartCrafter fixes tyres, not glass. Glazing is ~80% of all audit failures and
the owner's hard-fail rule, so on this evidence the part-native route does NOT
by itself make a generated car shippable. **[SUPERSEDED by the 16-part correction
below: at num_parts=16 the greenhouse DOES separate. Read that before acting.]**

**Do not run assign_materials on PartCrafter output as-is.** The stage joins and
welds before splitting, which is correct for a fused TRELLIS mesh and DESTROYS
PartCrafter's separation -- the parts touch where they meet, so welding fuses
them back into one shell and the stage then (correctly) refuses. Classify
PartCrafter's parts DIRECTLY from the glTF mesh list; skip the weld entirely.

**CORRECTED 2026-08-12, same day: num_parts=16 OVERTURNS the 10-part conclusion.**
The re-run (front 3/4 input, 374s on A5000, RC=0) emits the GREENHOUSE AS ITS OWN
CLOSED MESH -- part_08, 223,358 verts, 13.6% of the car, containing windscreen, side
glass, rear screen and roof skin as one canopy, verified by isolate renders. The body
shell (part_05, 29.8%) has real window OPENINGS with the interior visible through
them, and the underbody/chassis is separate again (part_09, 27.4%). No 99.3%- or
67.9%-style mega-part exists at 16. So "the greenhouse is treated as body by this
model" was an artefact of asking for too few parts, not a property of PartCrafter.
Two qualifications, measured:
  * The canopy is glass+ROOF fused, not glass alone. Assigning Glass_Tint to the
    whole part would make the roof transparent. But a normals split inside just that
    part is clean: with Y up, 46.4% of its face area is strongly Y-facing (roof
    panel) and the rest sloped/vertical (glazing) -- far more tractable than carving
    glass out of a full body shell.
  * Part indices are not semantic: which part is the canopy varies per run, so the
    classifier must FIND it (mid-band, above body sill, encloses cabin), not assume
    an index.
Evidence: scratchpad pc16_colored.png / pc16_canopy.png / pc16_body.png; results
tarball at car-meshes/partcrafter_run/results16b.tgz.

**RUNPOD POD DEPLOYMENT, two traps that cost ~$0.40 and 80 minutes:**
  1. **A pod whose dockerStartCmd EXITS gets RESTARTED.** Ending the command with
     `sleep 120` then exiting put the pod in a restart loop: re-clone, re-install,
     re-download ~10GB of weights, forever, never finishing. The tell is
     `runtime.uptimeInSeconds` resetting to a small number with GPU at 0%.
     Keep the container alive (`sleep infinity`) and terminate it explicitly.
  2. **Supabase signed upload URLs are ONE-TIME.** First PUT 200, every later PUT
     400 -- verified. So a bootstrap can report exactly once, and a restart loop
     burns that single shot on whichever attempt happens to finish first. Use a
     service key on the pod (accepting the exposure) or mint a fresh URL per
     attempt; do NOT design a heartbeat around a signed URL.
  3. **A `for i in $(seq 1 N)` watcher is a COUNTDOWN, not a monitor.** The v2
     watcher was capped at 45 iterations of `sleep 60`. It expired at 13:07
     having logged 45 identical `results=400 pod=RUNNING` lines, printed
     nothing to distinguish "gave up" from "done", and nothing replaced it.
     The pod then billed unwatched until 13:39. A bounded loop MUST print a
     distinct TIMED_OUT marker on fall-through, and the thing that reads it
     must treat a missing RESULTS_READY as an alarm, not as silence.

**What the watcher polled was the wrong thing, and that is the deeper lesson.**
It asked (a) does the output file exist yet and (b) is `desiredStatus` RUNNING.
`desiredStatus` is what was ASKED FOR, so it reads RUNNING through an infinite
restart loop; and the output file never appears in a loop that never finishes.
Both signals are constant whether the pod is working or thrashing. **Poll
PROGRESS, not desire:** `GET /v1/pods/<id>` -> `runtime.uptimeInSeconds` and
`runtime.gpus[].gpuUtilPercent`. Uptime resetting while the wall clock climbs
IS the restart loop; GPU at 0% means nothing is computing. That single call
would have exposed this at minute 5. It was made at minute 78.

**And do not quote an in-container `timeout` as a bound on a pod's lifetime.**
At the 23-minute mark I told the owner "results land within ~6 more minutes
regardless" because inference was wrapped in `timeout 1500`. That governs a
PROCESS INSIDE the container and resets on every restart; it says nothing about
how long the pod runs or bills. Asserting it without checking is exactly the
failure the NO GUESSING rule above exists to prevent.

Cost of the whole experiment including four failed bootstraps: ~$0.62. The
fail-fast-and-upload-logs design earned that back -- each failure named its own
cause (missing `src` on PYTHONPATH, settings/requirements.txt path, sudo absent,
pyrender importing pyglet/X11 and needing xvfb-run).

## Generator research: the material-structure blocker, and the model that fixes it (2026-08-12)

Owner asked to look at other models to improve the 3D machine. The finding that
matters is that the blocker is NOT geometry quality -- it is mesh STRUCTURE, and no
amount of better surfacing fixes it.

**Measured on real TRELLIS.2 output (car-meshes/trellis/*.glb):** one fused mesh,
one untitled material, OPAQUE. After welding, ONE part holds 99.3% of the vertices
-- body, windows, wheels and interior are a single continuous shell. So:
  * glass_probe -> "opaque" -> automatic scrap under the 2026-08-11 ruling
  * colour_variants -> "no paintMaterialNames" -> cannot bake the 8 colours
  * no distinct rubber -> paint covers the tyres
`pipeline/trellis/assign_materials.py` reproduces the proven 4-material scheme from
golf_mv_polished.glb by welding + loose-part split + geometric classify, and it
WORKS once parts are separable -- but on a fused shell it can only find 0.5% of the
mesh as "glass" (mirror housings, badges), so it refuses to write rather than ship
a file that fools glass_probe. Verified: red respray of that file turned the
WINDOWS red with the body.

**Two cheap fixes are dead, measured not guessed:**
  * geometric segmentation of a fused shell -- impossible, the windows are not
    separate geometry.
  * texture-based glazing selection -- fails on dark cars. The test Golf R's albedo
    has glass, dark paint and dark trim all at the same near-black value (58% of
    texels < 40 luminance). Only works when body colour contrasts with the glass.

**The real fix is a part-native generator (research, 2026-08-12):**
  * **PartCrafter** (arXiv 2506.05573, MIT code / CC-BY data) -- single image ->
    up to 16 SEPARATE semantic meshes in one pass, no pre-segmentation. Glazing
    comes out as its OWN mesh, which is exactly what makes assign_materials able to
    isolate it. Caveats: GEOMETRY ONLY (textures added post-hoc, the paper uses
    Hunyuan3D-2 for that); trained on only ~50k part meshes so complex objects are
    a quality risk; the paper does not showcase cars, so vehicle quality is
    UNVERIFIED and must be tested before committing.
  * **Hunyuan3D 2.1 / 3.5** -- production PBR (base/metallic/roughness/alpha), 3.5
    does up to 8K PBR and is ~2x faster than 2.1. Higher quality ceiling than
    TRELLIS.2, but pricier and STILL likely a fused shell for glass (unverified) --
    better surfacing does not by itself solve the structure blocker.

**Recommended experiment order, cheapest first, each with a hard measurable gate:**
  1. Run PartCrafter on ONE clean car reference; check it emits a glazing mesh >=2%
     of verts and passes assign_materials + glass_probe "clear (proven)". This is
     the whole ballgame -- if PartCrafter cars are mush or one blob, the route is dead.
  2. If geometry passes but is untextured, texture the parts with Hunyuan3D-2 and
     re-run the full gate stack (glass, tyres, 8-colour respray, red-control render).
  3. Only then compare against the licensed-model route on quality.
Do NOT switch the production generator before step 1 clears; the owner shelved
TRELLIS.2 on quality (melted panels, absent shut lines) and a part-native model has
to beat that bar too, not just the structure bar.

## Hunyuan3D-2 TESTED + the HYBRID route (2026-08-12, same day as PartCrafter)

Same input photo through Hunyuan3D-2 on a RunPod A40, ~$0.10 total across three
attempts. The two generators split the problem EXACTLY between them, measured:

  * **Hunyuan3D-2 surfacing is the best of any generator tested** — clean panels,
    formed mirrors, bumper intakes, readable wheel spokes. Still not premium (no
    shut lines, two roof spikes, lamp recesses without internals) but clearly
    above TRELLIS and far above PartCrafter's melt.
  * **Hunyuan3D-2 structure is ONE fused component — 100.0% of verts** (owner-rule
    auto-scrap on its own: opaque glazing, painted tyres). Prediction confirmed.
  * PartCrafter is the mirror image: parts separate, surfacing melt.

**The hybrid (`pipeline/trellis/hybrid_transfer.py`) takes both runs from the SAME
image and transfers PartCrafter's part labels onto Hunyuan's mesh per-face.**
Alignment needs no ICP — both normalize to the same pose (mean NN distance 0.020;
try length/width flips, keep the best). k-NN weighted vote + physical priors +
island absorption; canopy split roof/glass by the shared ROOF_NORMAL_UP. Result on
the test car: glass 10.5% of faces (real-car band 4–12%), glass_probe **clear
(proven)**, red control keeps glazing/tyres/lamps dark. Staged at
car-meshes/staging/hybrid/. Deploy traps from run 1+2, both cost ~$0.02 and
self-diagnosed via the heartbeat design: Hunyuan's requirements.txt BREAKS the
image's torch (reinstall the cu124 pin afterwards and assert `import torch`
works); pymeshlab's postprocess needs libOpenGL.so.0 (libopengl0) or
FloaterRemover dies — export the RAW mesh before postprocess so the crash costs
nothing.

**v1 limit, honest:** label boundaries are only as good as PartCrafter's parts.
The windscreen boundary is ragged and one dashboard-junk blob lands on the front
wing. More smoothing does not fix this — the fix is a better segmentation source
(2D segmentation of multi-view renders projected onto the mesh). Also add a lamp
note: `partcrafter_materials.py` now has a lamp class (nose/tail, offset, lamp
band -> dark gloss Lamp_Lens), which transfers through the hybrid too.

## Hi3DGen TESTED (2026-08-13): the sharpness ceiling IS higher — first mesh with real panel features

Five attended pod runs, ~$0.05 total, each failure self-named in ~90s (import
stack -> sparse attn needs xformers|flash_attn ONLY (full_attn.py:30) -> newest
diffusers + flash-attn registers a torch custom op torch 2.4 cannot parse (pin
diffusers==0.31.0, use xformers 0.0.27.post2) -> BiRefNet weights are a THIRD
repo (ZhengPeng7/BiRefNet, in app.py cache_weights) -> their own requirements
pin timm==0.6.7 while BiRefNet remote code needs timm.layers (>=0.9; use >=1.0)).
Deploy stack that works: image torch 2.4.0+cu121 untouched, spconv-cu121,
xformers 0.0.27.post2 (cu121 index), diffusers==0.31.0, timm>=1.0,
ATTN_BACKEND=xformers, SPCONV_ALGO=native. Driver calls Hi3DGenPipeline directly
(app.py is Gradio-only). Weights: Stable-X/trellis-normal-v0-1 + yoso-normal-v1-8-1
+ ZhengPeng7/BiRefNet. Mesh exports Z-UP (length on Y) — rotate -90 about X.
POD-SIDE FUSE (self-DELETE via the RunPod-injected pod-scoped key at 45 min)
is now the standard ceiling — it survives operator-session death, the 7h lesson.

**VERDICT on the same input photo as every other generator: CLEARLY SHARPER
than Hunyuan3D-2, and the first model to produce shut-line-class features in
the MESH:** separate grille slats, cowl/wiper slots, a visible bonnet crease,
crisp DLO edge with recessed side glass, formed mirrors, thin wheel spokes.
The predicted normal map (saved as evidence, staging/hybrid/hi3dgen_normal.png)
carries door handles, shut lines and lamp internals — the architecture works.
STILL PRESENT: artefact fins on the roof (antenna class), zipper-stitching
along the beltline/bonnet edges, small holes at the cowl, wavy rims. And the
structure is the SAME fused shell as every voxel model: 9 components, largest
99.4% — so the PartCrafter/hybrid material route remains REQUIRED on top.
Mesh staged at car-meshes/staging/hybrid/hi3dgen_hi3dgen_yup.glb, 495k faces.

## Wheel swap + the v4 boundary verdict (2026-08-12, late)

**hybrid_transfer v4 patches VERIFIED**: the positional roof rule fixed the
windscreen (head-on now a full dark screen with cowl); glass 13.5% of faces —
top of the real band, expected from freeing the raked screen centre. Side and
rear boundaries improved but still ragged: that residue is the LABEL SOURCE
(PartCrafter melt), not the cut. Do not tune further — replace the source.
**Tencent Hunyuan3D-Part (P3-SAM + X-Part) is the replacement**: native 3D part
segmentation from the same team as the geometry model, 3.7M-model training set,
open weights (github.com/Tencent-Hunyuan/Hunyuan3D-Part). Segments the Hunyuan
mesh DIRECTLY — no cross-mesh transfer at all. Backups: NVIDIA PartField
(faster); Hi3DGen (sharper geometry, candidate to upgrade the shape stage).

**pipeline/trellis/wheel_swap.py replaces melt wheels with library geometry**
(donor: GR Supra front-left wheel from our own catalogue). Traps its docstring
records, all paid for tonight: the wheel LABEL bbox includes arch-liner spill
(mis-centred and 40%-oversized the first attempt — measure position from
tyre-zone faces below ground+0.30 and depth from the BODY side surface);
deleting original wheel faces holes the shell (recolour them Arch_Cavity
instead); the donor's own material table is untrustworthy (Supra ships its
whole wheel as one pale material — take geometry only, assign our own
Tyre_Rubber/Rim_Alloy split by radius); catalogue donors are mostly
Draco-compressed and neither Blender nor trimesh here can decode — run
`gltf-transform copy` first (npm i -g @gltf-transform/cli).

**Symmetrise was measured a NO-OP on Hunyuan output**: mirror asymmetry mean
0.16% of car length (p95 0.28%). Skip it. Shut-line engraving deferred: the
mesh already carries faint real door creases; synthetic lines without
semantics risk drawing wrong ones — that fix belongs to Hi3DGen / car
fine-tuning, not geometry surgery.

## Night audit 2026-08-12/13: ten failures, three root causes (self-audit, owner-ordered)

The full table lives in the session log; what the next session must inherit:

1. **GUARDS ARE CODE AND MUST PROVE THEMSELVES.** Every safety mechanism built
   tonight failed AS a safety mechanism: a sed corrupted the URL it guarded, an
   import preflight killed a healthy run, a watcher parsed a transient query
   failure as "pod gone", and the night watch DIED AT ITS FIRST TICK because
   **background processes in this container do not survive session idle** — a
   pod then billed unwatched for 7h10m ($3.15, the "mystery" balance drop,
   which the audit resolved to the penny: 7.1h x ($0.44+$0.058)). Never claim
   protection from a watchdog that has not been observed to fire once. For
   overnight pods the ONLY trustworthy ceiling lives outside this container
   (pod-side timeout in the bootstrap itself: `sleep MAX && self-terminate`).
2. **Do not report intentions as facts.** "You are protected" / "agents are
   working" / "results in ~6 min" were designs, narrated as running realities.
   State what has been OBSERVED, or say "unverified".
3. **Delegation must be verified like any other output.** Six subagents were
   spawned overnight; ZERO returned reports; two files they wrote were never
   run by anyone. Treat "no report" as failure at the NEXT check, not hours
   later — and never respond to silent agent failure by spawning more agents.
   Control group: everything done by hand that evening shipped (six tools, 12
   commits); everything delegated returned nothing.
4. The balance endpoint is fine; MY accounting was wrong. Reconstruct spend
   from pod lifetimes x rate, and a rented pod with `runtime: null` BILLS.

## P3-SAM (Hunyuan3D-Part) deployment: eight runs of traps, all recorded (2026-08-12)

Native 3D part segmentation, the intended replacement for the PartCrafter->Hunyuan
label transfer (it segments the Hunyuan mesh DIRECTLY, so there is no cross-mesh
alignment step and no ragged transferred boundary). Repo:
github.com/Tencent-Hunyuan/Hunyuan3D-Part. Weights auto-download from HF
(`tencent/Hunyuan3D-Part`, file `p3sam/p3sam.safetensors`) when ckpt_path is None.

**THE DEMO SCRIPT SAVES NOTHING. This is the big one.** `P3-SAM/demo/auto_mask.py`
computes `(aabb, face_ids, mesh)` and RETURNS them, and the block that would write
them is COMMENTED OUT under "You can save the returned result by the following
code". `--save_mid_res 1` only dumps intermediate debug visualisations. A run can
exit RC=0, log every stage with timings, and leave an empty output directory.
FIX: call the API directly (`from auto_mask import AutoMask; am.predict_aabb(...)`)
and save `face_ids.npy` + the RETURNED MESH yourself. Saving their mesh matters:
`clean_mesh=1` re-meshes the input, so face ids need not match the mesh you sent —
exporting the returned mesh makes indices align by construction rather than by a
nearest-centroid approximation.

**Environment, verified working (do not re-derive):**
  * image `runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04` — its torch is
    already what P3-SAM is tested on. Do NOT reinstall torch.
  * `pip install spconv-cu121 torch-scatter(-f pyg wheel index) huggingface_hub timm
    viser fpsample trimesh numba addict einops scikit-learn omegaconf pymeshlab
    safetensors scikit-image tqdm gradio`, then Sonata `python setup.py install`.
  * flash-attn from the prebuilt release wheel, never source (a source build costs
    30+ minutes); Sonata runs without it via enable_flash=False.
  * Deps install in ~90 seconds on a warm host. Whole cycle boot->deps->infer is
    about 3 minutes.

**Two undocumented dependency facts, found by reading code not READMEs:**
  * the script is at `P3-SAM/demo/auto_mask.py`, NOT `P3-SAM/auto_mask.py` as the
    README's command implies — the first run died on the README's own path.
  * `model.py` reaches sideways into the XPart half of the repo
    (`sys.path.append(.../XPart/partgen)`), which needs `omegaconf` and friends that
    the P3-SAM instructions never mention. Scan the whole import graph locally
    (regex every `import` across the files it touches, try importing each) rather
    than discovering them one pod at a time.
  * `auto_mask.py` does `sys.path.append('..')` before `import model`. Any import
    preflight MUST replicate that or it fails on a healthy install (mine did).

**OOM: the defaults do not fit a real generated car.** A 626k-face mesh at the
default `--prompt_bs 32 --point_num 100000` exhausted a **44GB** A40 (tried to
allocate 3.05GiB with 44.33GiB in use). Working settings: `--prompt_bs 8
--point_num 50000` plus `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`.
prompt_bs is the direct lever on the transformer's peak tensor.

**TWO OF THE EIGHT FAILURES WERE MY OWN TOOLING, and both were silent:**
  * `sed 's/ps_boot/ps2_boot/g'` also rewrote the substring inside the filename
    `ps_bootstrap2.sh` -> `ps2_bootstrap2.sh`, a URL that 400s. The pod's start
    command is `curl -fsSL ... && bash`, so curl failed, `&&` short-circuited, and
    the bootstrap NEVER RAN — no heartbeat, no logs, nothing to diagnose. I
    misdiagnosed it as slow image pulls for two runs. **Never build a URL with a
    global sed; edit the JSON with python, and PREFLIGHT the bootstrap URL for 200
    before renting a GPU.** That preflight is now standard.
  * my import preflight ran `python3 -c "import model"` without the `sys.path`
    append the real script does, so it aborted a healthy run.
A safety check that is itself wrong costs exactly as much as no safety check.
Assert on ARTEFACTS too: the bootstrap now fails with `FAIL_NO_FACE_IDS` if the
output file is absent, so a silent no-output run can never read as success.

**P3-SAM CANNOT SEPARATE GLAZING, AND THIS IS BY DESIGN — settled, do not retry.**
Two runs on our Hunyuan car (626k faces), face ids perfectly ALIGNED both times:
  default (prompt_num 400, threshold 0.95) -> 9 parts, largest 74.5%
  fine    (prompt_num 1000, threshold 0.85) -> 7 parts, largest 75.4%
More prompts and a lower merge threshold produced FEWER parts, not finer ones.
The colour-coded render is unambiguous: wheels, mirror, wipers and side skirt cut
cleanly, and the whole body INCLUDING every window is one part.
The reason is principled: **P3-SAM segments PHYSICAL PARTS — things that are
separate objects. Glazing on a fused shell is a REGION of one continuous surface,
not a part.** PartCrafter separates the greenhouse because it GENERATES it as its
own mesh, not because it segments one. No amount of parameter tuning changes this,
so do not spend another run on it.
**What P3-SAM IS good for: wheels and trim.** Its wheel cuts are visibly cleaner
than the PartCrafter transfer's ragged arch spill. Best architecture on current
evidence: Hunyuan geometry + PartCrafter canopy for glazing + P3-SAM for
wheels/mirrors/wipers.

**OWNER VERDICT 2026-08-12, verbatim: "It fukin look shit."** Said of the finished
hybrid car AFTER every material gate passed. This is the honest state of the
generation route and must not be softened in a future session:
  * SOLVED: the material layer. Glass reads as glass, tyres stay black, lamps hold
    their colour, body resprays cleanly, glass_probe clear (proven), red control
    holds. The structural blocker that scrapped 119 live cars is genuinely fixed.
  * NOT SOLVED, and untouched by any of it: SURFACING. Soft mushy panels, no shut
    lines, blobby lamp recesses, melted front end. The owner flagged this early
    ("the lights got paint over plus look soft"); the lamps were fixed and the
    softness was not. Fitting crisp catalogue wheels to a soft body arguably made
    the mismatch MORE obvious.
Every open generator tested (TRELLIS.2, PartCrafter, Hunyuan3D-2) shares this
ceiling. Hunyuan is the best of them and is still nowhere near the premium bar.
Untested levers remaining: Hi3DGen (sharper geometry by design) and a fine-tune on
our own catalogue. **If Hi3DGen also comes back soft, the correct conclusion is
that image-to-3D cannot currently produce a premium car, and the money belongs in
sourcing or licensed heroes, not here.** Do not reopen the material work — it is
finished and it was never the thing that made the car look bad.

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

**Seed selection and the Blender correction stage were then also measured (same car):**
seeds 1-3 at identical settings each produce DIFFERENT defects (seed 1 uniquely gets real
headlamp internals and door shut lines, but grows two aerial spikes and a smeared
tailgate; seed 3 warps the whole rear). Seed choice relocates defects, it does not remove
them. process_candidate.py (symmetrise/corrective smooth/weighted normals, no component
library, no panel refs) is visually a NO-OP on the melt. Every documented lever is now
tried: input prep, view count, resolution, seed, correction. The melt survived all five.

**SHELVED by owner decision 2026-08-09.** Nothing from this experiment ships. The seed-1
mesh was the only candidate to produce headlamp internals and a door shut line, and it was
still rejected: it would not survive the audit applied to sourced cars, and publishing it
would undercut the standard the 100+ catalogue cars were held to. Do NOT reopen this by
turning knobs -- all five documented levers are measured below. Reopen only for a materially
different backend (camera-aware / labelled multi-view) or a real Blender component library,
and re-measure against these sheets rather than against hope.

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
