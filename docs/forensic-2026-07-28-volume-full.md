# Forensic review — 2026-07-28: why the eval could not run

Method: the root-cause discipline saved in `CLAUDE.md`. Every figure below is
measured, not recalled; the source of each is named.

---

## PROBLEM

Six hours after a training run that was supposed to leave this project ready to
evaluate, the evaluation could not start. It aborted at boot with
`OSError: Errno 122 Disk quota exceeded` on the `alam3d-data` network volume.

---

## WHY #1 — Why did the eval fail?
Its boot-time volume write probe could not create a file. The guard worked as
designed and the pod tore itself down in ~10 minutes for about $0.25.

## WHY #2 — Why could it not write?
The volume is **236 GB used of 250 GB** (measured by `volume_diag_pod.sh`,
2026-07-28 08:47Z). ~14 GB free, and the pipeline needs headroom to stage
outputs.

## WHY #3 — What is consuming it?

| Directory | Size | Status |
|---|---|---|
| `alam3d_stage_c_v1` | 88 GB | last night's run — the only checkpoints with forward value |
| `alamcars` | 67 GB | the dataset (renders, latents, PBR dumps) |
| `alam3d_stage_c` | 34 GB | **v0 — trained at 1e-4, measured to make quality worse** |
| `alam3d_stage_d` | 30 GB | **wrong LR, step-4000 already corrupted by the last full-volume event** |
| `hf_cache` | 17 GB | re-downloadable |

**152 GB — 61% of the volume — is training checkpoints, and 64 GB of that is
from runs already known to be void.**

## WHY #4 — Why do three runs' checkpoints coexist when two are void?
Nothing deletes a superseded run. Each training script creates its own `$OUT`
and writes into it. No script has a retention policy; no step asks whether the
*previous* run is still worth keeping.

Compounding it: each saved step writes three files — `denoiser_ema` (~5.2 GB),
`denoiser` (~5.2 GB) and `misc` (~10.3 GB of optimiser state). At `i_save 250`
over 1250 steps that is five sets. **Only the EMA files are needed to evaluate,
and only the newest `misc` is needed to resume.** The rest is dead weight the
moment the next checkpoint lands.

## WHY #5 — Why is there no retention policy?
Because every script in this pipeline is written as a one-shot experiment that
assumes an empty world. They create, they never reconcile. The same assumption
produced three other bugs found in the last 24 hours:

- the eval script hardcoding v0's directory (M5)
- `publish_weights_pod.sh` hardcoding v0's directory (H2)
- `stage_c_v1_pod.sh` writing to a fresh `$OUT` with no thought for the old one

## WHY #6 — Why has that pattern survived repeated incidents?
**Because the cost never lands on the run that causes it.** A run that fills the
volume still finishes and still reports success. The bill is paid by whatever
runs next — a different job, often days later, usually mid-flight. There is no
feedback loop from the damage back to the cause.

This is the second full-volume incident. The first one silently truncated Stage
D's step-4000 checkpoint from 5.2 GB to 1.1 GB, and nobody noticed until the
evaluation failed to load it.

---

## ROOT CAUSE

**No component of this pipeline owns the volume's lifecycle.** Storage is
treated as infinite by every writer, and the cost is externalised onto the next
job. The volume is not full because 250 GB is too small for the work — it is
full because 64 GB of provably void checkpoints and ~50 GB of redundant
optimiser state were never anybody's job to remove.

**Confidence: 90%.**

**Evidence for**
- 152 GB of 236 GB used is checkpoints; 64 GB of that is from runs whose
  learning rate is now known to have been wrong, making them void as experiments
- Second occurrence of the same failure, with a known prior casualty
- Not one script in `pipeline/finetune/` deletes anything it did not create in
  that same run
- Account-wide, the same pattern: **600 GB of network volumes**, including a
  **200 GB `hunyuan3d-models` volume for an engine abandoned on licence grounds**
  (its licence excludes the UK), plus 2,120 GB of stopped-pod disk

**Evidence against**
- 250 GB is genuinely tight for a 4B model: one saved step is ~20.7 GB, so a
  single 5-checkpoint run consumes ~40% of the volume even with nothing else on it
- Someone did reclaim ~98 GB previously — so cleanup happens, just reactively,
  after a failure, by hand

**Alternative root causes considered**
1. *The volume is undersized.* Partly true, and it would be the whole story if
   the 152 GB were all live. It is not — 64 GB is void.
2. *Checkpoint frequency too high.* `i_save 250` was chosen deliberately so an
   early stop always left something usable. Sound reasoning, but it multiplied
   the `misc` files by five with no offsetting cleanup.
3. *`misc_*` optimiser state retained for every step.* ~10.3 GB × 5 ≈ 51 GB to
   preserve a resume capability that only ever needs the newest one. This is the
   single largest avoidable consumer and is a real contributing cause, not an
   alternative to the root cause.

---

## ACTIONS

**Immediate (unblocks the eval today)**
- Delete `hf_cache` — 17 GB, zero data risk, re-downloads on demand. Enough to run.
- Or delete `alam3d_stage_c` (v0, 34 GB): void weights whose published checkpoint
  is already backed up to `Alamj/alam-3d-v0`. Frees twice as much and keeps the
  cache, so every later pod boots faster. **Owner's call — both are deletions.**

**Medium-term**
- Prune `misc_*` to the newest step only: ~40 GB back with no loss of resume.
- Retire `alam3d_stage_d` (30 GB) — wrong LR and already partly corrupt.
- Archive `alam3d_stage_c_v1`'s EMA checkpoints to a private HF repo before any
  volume operation. **Right now the only correctly-trained weights this project
  has exist in exactly one place.**
- Decide on the 200 GB `hunyuan3d-models` volume for an engine that cannot be
  used in the UK.

**Long-term prevention**
- Every training script asserts free space at boot *against its own projected
  output* (`steps/i_save × 20.7 GB`) and refuses to start if the volume cannot
  hold it. Fail before the run, not during the next one.
- A retention rule in the trainer: keep all EMA, keep only the newest `misc`.
- One `$OUT` naming convention with an explicit supersede step, so a new run
  states what it replaces.

---

## RISKS IF IGNORED

- **Silent corruption, not clean failure.** The previous full volume produced a
  5.2 GB checkpoint that read back as 1.1 GB of garbage. A full volume does not
  reliably raise an error — it can accept the write and lose the blocks.
- **The only good weights are unbacked.** A volume incident now costs the entire
  correctly-configured run, not an experiment.
- **Cost.** 600 GB of volumes plus 2,120 GB of stopped-pod disk, currently
  $0.55/hr ≈ **$396/year**, for storage that is mostly void or abandoned.

## KPIs TO MONITOR
- Free space on `alam3d-data` before and after every run
- GB per training run (~20.7 GB per saved step)
- Count of run directories on the volume (should be ≤ 2: current + previous)
- Account-wide network-volume GB, reviewed when any workstream is abandoned

## EARLY-WARNING INDICATORS
- Free space below ~60 GB — one run's worth
- More than two `alam3d_stage_*` directories
- Any log line reporting a checkpoint size that differs from its siblings
- A volume attached to a workstream nobody has touched in 30 days

## COST OF DOING NOTHING
One truncated checkpoint already. The next incident lands on the only
correctly-trained weights this project has produced — 11 GPU-hours and roughly
$25, plus the day of audit work that selected the 296 shapes behind them.

## HIGHEST-ROI SOLUTION
**The boot-time free-space assertion.** One check, in every training script,
comparing projected output against actual free space. It converts a silent
mid-run corruption into a refusal to start, and it would have prevented both
incidents. Everything else on this list is cleanup; this is the thing that stops
it recurring.

---

## CHALLENGE — what assumptions could still be wrong?

**"The 34 GB of v0 is void."** It is void *as a fine-tune*, because the learning
rate was wrong. It is not void as a *record* — it is the only evidence of what
1e-4 does to this model, and steps 1000–3000 are backed up nowhere. If anyone
ever needs to prove why v0 failed, deleting it destroys that.

**"88 GB is last night's run and therefore precious."** I have not listed that
directory file by file. If it also holds v1's earlier aborted attempts, some of
that 88 GB is junk too, and I would be proposing deletions elsewhere while
leaving the biggest consumer unexamined.

**"The volume is the constraint."** RunPod bills the volume whether it is full
or empty. The real question is not "how do we fit" but "why does this project
own 600 GB across five volumes, 200 GB of it for an engine it legally cannot
use in the UK". Freeing 17 GB answers today's blocker and none of that.

**"i_save 250 was right."** It was chosen so an early stop always left something
usable — sound when the balance was $19 and the run might be killed for money.
With the run now complete, that reasoning has expired and the cost of it, ~51 GB
of optimiser state, is still being paid.

### Other lenses

- **Financial:** the storage bill is ~$396/year against a balance of $16.76. The
  storage costs more per year than every GPU-hour this project has ever spent.
- **Engineering:** every fix today changed a *mechanism* rather than adding a
  warning — the env allowlist became prefix-based, the LR became a read-back
  assertion. The free-space check belongs in that same category. Warnings have a
  measured failure rate here: the launcher's own comment warned that a missing
  env name is silently dropped, and it was silently dropped three times anyway.
- **Operational:** the watchdog that should have stopped an idle pod died with a
  sandbox wipe and cost $7.60. Same shape as this: a safeguard that depends on
  something outside the thing it guards. The pod should terminate itself; the
  trainer should refuse to start. Guards belong *inside* the boundary.
- **Customer:** none of this reaches a customer. The catalogue serves 366 cars
  and is untouched by every incident here. That is worth stating plainly — this
  is a research-tier problem, and the shipping tier has been stable throughout.
