# Forensic bug register — 2026-07-27

Every finding below is the same shape:

> **A value is written, a patch is applied, or a filter is declared — and nothing
> ever reads back the thing that would prove it took effect.**

Each entry is tagged with how it was established:

- **[MEASURED]** — reproduced directly, on this repo or on the live pod, today.
- **[UPSTREAM]** — verified against microsoft/TRELLIS.2 @ `75fbf01` (the commit
  `trellis/Dockerfile:21` pins) by an independent audit; mechanism inspected here
  but the upstream run was not repeated by me.

---

## CRITICAL

### C1. The learning rate was decorative — every fine-tune ran at stock 1e-4 [MEASURED]
`trainer.args.learning_rate` is not read by anything. The optimizer reads
`trainer.args.optimizer.args.lr`. Every script set only the former.

| Run | Claimed | Actual |
|---|---|---|
| Stage C v0 | 1e-5 | 1e-4 (10×) |
| Stage D | 8e-6 | 1e-4 (12×) |
| Stage C v1 (first attempt) | 5e-6 | 1e-4 (20×) |

Caught by reading the trainer's own banner on the pod: `Learning rate: 0.0001`
while the config said 5e-6. After the fix the same banner reads `5e-06`.

**Consequence:** the v0 post-mortem — "fine-tuning made quality worse, damage grows
with steps" — was measured on a run whose step size was 10× the intended value.
That conclusion is void, not confirmed. Fixed in all three scripts.

### C2. `|| { status FATAL; }` around `train.py` is dead code [UPSTREAM + MEASURED]
Upstream `train.py` wraps `main()` in `for rty in range(cfg.auto_retry)` with a
bare `except Exception` and no re-raise; default `auto_retry` is 3. The process
prints three tracebacks and **exits 0**, so the shell's `||` guard never fires
and the pod prints `DONE` having trained nothing.

Observed live twice today: once on a missing `metadata.csv`, once on the gated
conditioner. Affects `stage_b_pod.sh`, `stage_c_pod.sh`, `stage_d_pod.sh`.
Only `stage_c_v1_pod.sh` has the "no checkpoints → the exit code lied" backstop.

### C3. Gated DINOv3 401 → silent no-op [MEASURED]
`facebook/dinov3-vitl16-pretrain-lvd1689m` is a gated repo. With no valid
`HF_TOKEN` the trainer 401s, retries 3×, exits 0 — while the log's last line
stays `Starting training...` and the pod bills at $1.49/hr. Three trainer
initialisations in one run log gave it away. `launch_pod.py` forwards the token
only `if hf:` — a missing token launches the pod anyway.
Fixed: preflight aborts unless the gated config returns HTTP 200.

### C4. The per-shape cull is enforced only by accident [UPSTREAM + MEASURED]
`stage_c_v1_pod.sh` writes a private `metadata.csv` restricted to the kept
shapes. But upstream `components.py` reads `metadata.csv` from **every** data
root and `combine_first`-**unions** the indices — `render_cond`, `shape_latent`
and `ss_latent` still describe all 964.

The live run's own Dataset block shows the mechanism exactly:

```
- Total: 964
- With latent: 963
- Aesthetic score >= 0.0: 296     <- the cull happens HERE, by NaN
- Total instances: 296
```

The culled shapes are excluded because they carry `NaN` in `aesthetic_score`,
and `NaN >= 0.0` is `False`. **Add an `aesthetic_score` column to any one of the
other three roots and the culled shapes silently return to training.**

**Status of the live run: correct — 296 instances confirmed.** But it is correct
by luck, not by construction. Nothing asserts the instance count, even though
the trainer prints it.

---

## HIGH

### H1. Augmentation can no-op while every gate reports green [UPSTREAM]
`augment_cond_pod.sh` copies the **original** on any exception. The downstream
preflight compares only **file counts**, and the "confirmed: training on
AUGMENTED views" check tests only that a **path string** contains
`renders_cond_aug`. An audit reproduced this: byte-identical copies pass both
gates. The before/after samples that would disprove it are written to container
disk and destroyed when the pod is deleted.

**Did it happen to us? No — [MEASURED].** Our run reported
`10,030 augmented | 5,394 clean | 0 errors` of 15,424 images = 0.65, exactly the
target fraction. `n_aug` is only incremented on the success path, so a silent
no-op would have shown 0.00. The augmentation is real; the *gate* is still blind.

### H2. `publish_weights_pod.sh` would ship v0 weights with a false training record [MEASURED]
Hardcodes `/workspace/alam3d_stage_c` (v0's directory) in four places, so running
it after v1 or Stage D publishes **v0's measured-damaged weights**. The model
card hardcodes `LR 1e-5` — which C1 proves was actually 1e-4. Provenance CSV is
built from the shared volume metadata, listing assets the model never saw.
This file is described as being for a licensing conversation.

### H3. `models.denoiser.args.resolution` is another dead config key [UPSTREAM]
`stage_d_pod.sh` sets `resolution = 64` and prints `denoiser resolution 64`. In
upstream `structured_latent_flow.py` the parameter is assigned to `self` and
never read. Stage D is the 1024 refiner only because `ALAM3D_INIT_FROM` loads
those weights. Same class as C1, still live.

### H4. `ALAM3D_NO_SNAPSHOT` patches 1 of 3 snapshot methods [MEASURED]
The patch regex is `def snapshot\(self` — it cannot match `snapshot_dataset(`,
because the `(` is literal. Upstream calls `snapshot_dataset()` **unconditionally**
at the top of `run()`, right after printing `Starting training...`: it decodes
100 latents and renders them.

**This is a live alternative explanation for "80 minutes at 100% GPU printing
nothing"** — and it means a pod I killed for being silent may have been doing
exactly this. Also: `print(f"patched snapshot x{n}")` prints even when `n == 0`.

### H5. `prepare_dataset.py` silently drops assets and can never fail [UPSTREAM]
Assets under `--min-kb` are counted as `failed`, printed as a `SKIP` line, and
gate nothing; the script always exits 0. Against the live catalogue: 366 approved
assets, exactly **one** under 150 KB (`audi-a2`, 145.2 KB).

**This explains the 365 that has appeared everywhere for weeks** — the plan says
366, the scripts say 365, and nobody knew why. If 300 downloads had failed, Stage
A would have proceeded on 66 cars with the same exit code.

### H6. A pod reboot silently changes what training initialises from [UPSTREAM]
The HF-init guard is `if _init and cfg.load_ckpt is None`. `$OUT` lives on the
persistent network volume and upstream `find_ckpt` populates `load_ckpt` from
`$OUT/ckpts/`. Any reboot after a partial run resumes from that checkpoint
instead of Microsoft's weights — the exact thing the patch says it prevents —
and simultaneously satisfies the "did we produce checkpoints" gate with the
*previous* run's files. Nothing greps for the marker the patch prints.

---

## MEDIUM

### M1. `launch_pod.py` catches only `HTTPError` [MEASURED]
A `URLError` or timeout escapes `api()`, so `delete_pod` dies on the first
attempt: the retry loop and the `POD_DELETE_FAILED … STILL BILLING` warning never
run. The docstring's "ALWAYS delete the pod on any terminal state" is false for
precisely the network failure it exists for.

### M2. `curl -sSL` without `-f`, piped to `bash` [MEASURED]
`launch_pod.py:75` and `stage_a_pod.sh:20-21`. A missing bucket object returns
HTTP 400 with a JSON error body and **curl exits 0** — the body is executed, then
`sleep infinity`. A typo'd `--script` costs 6 hours of A100 before poll timeout.

### M3. `HF_REPO` can never reach the pod [MEASURED]
`publish_weights_pod.sh` reads `os.environ.get("HF_REPO", …)`, but `HF_REPO` is
absent from `launch_pod.py`'s forwarding allowlist — whose own comment says "A
knob missing from this list is silently dropped". Publishing always targets the
default repo.

### M4. `min_aesthetic_score = 0.0` is not "no filter" [UPSTREAM + MEASURED]
Upstream filters `aesthetic_score >= 0.0`, and `NaN >= 0.0` is `False`. The
`if "aesthetic_score" not in m.columns` default fires only when the column is
**wholly absent**, so a union-merge that introduces rows leaves it
present-but-NaN and those rows vanish. `stage_d_pod.sh` and `stage_c_v1_pod.sh`
fixed this with `fillna(6.0)`; `stage_b_pod.sh` and `stage_c_pod.sh` did not.
This is the same mechanism as C4.

### M5. `stage_c_eval_pod.sh` can report success having generated nothing [UPSTREAM]
Hardcodes v0's directory (evaluating v1 silently evaluates v0); drops cases with
no inputs silently; an empty case list runs zero generations, prints
`EVAL_GENERATION_COMPLETE`, and an unmatched glob uploads a literal `*.glb`
before `status DONE`. Also permits up to 20 parameter tensors to fail to load —
the correct threshold is 0.

### M6. Reported counts are not the trained counts [MEASURED]
- `stage_c_pod.sh` prints `"bs 1/gpu"` on the line after setting
  `batch_size_per_gpu: 4`. **The log lies about the config.**
- `stage_c_v1_pod.sh` printed "save every 500 (4 checkpoints)" while setting
  `i_save: 250` (8 checkpoints) — fixed today.
- `cond_rendered` is counted with `fillna(False).sum()` (True only) while
  upstream filters on `.notna()` (True **or** False).

### M7. Reports masquerading as gates [MEASURED]
Several checks print a scary word and then continue to `status DONE`: the
checkpoint-corruption check (the one that would have caught the truncated Stage D
save), the augmentation `missing=` report, `CONTRACT-MISSING`,
`HF_WEIGHTS_PROBE_FAILED`, and the resume probe, which never asserts it actually
resumed.

### M8. `build-data-roots` drops required roots silently [UPSTREAM]
`{k: v for k, v in roots.items() if v}` — a missing glob yields JSON without
`shape_latent`. The `data roots:` line looks fine; the failure surfaces later as
a `KeyError` inside `__getitem__`, which upstream catches and retries at a random
index, then dies in a DataLoader worker → exception → exit 0 (see C2).

### M9. `launch_pod.py` hardcodes `/stage_b.log` [MEASURED]
`stage_a_pod.sh` writes `stage_a.log` and creates no symlink, so the log tail is
always empty and `if tail:` hides that fact.

### M10. `stage_a_pod.sh` discards both output and exit code of `build_metadata.py` [UPSTREAM]
`… >/dev/null 2>&1 || true`. That program materialises the per-directory flags the
trainer depends on. **This is the mechanism behind both per-directory-vs-root
incidents** — Stage D training on 365 of 543 shapes, and the PBR texture pipeline
producing nothing.

### M11. `stage_b_pod.sh` fixes a bug that does not exist [UPSTREAM]
The comment claims `0 % n == 0` burns a snapshot at step 0; upstream's check sits
*after* `self.step += 1`, so step is never 0 there. The genuine step-0 cost is
`snapshot_dataset()` + `snapshot(suffix='init')`, untouched. Every Stage B run
paid for those snapshots twice.

### M12. `recolour_audit.py` treats a failed render as SKIP, not FAIL [MEASURED]
Exit 3 on `render-failed`. Any consumer treating "not FAIL" as "fine" scores a
broken render as acceptable. Consistent with the standing rule in `CLAUDE.md`
that an automated PASS is not a model-quality gate.

---

## Checked and clean

- **`objaverse_wave4.py` regexes are healthy after today's fixes.** All 78 `BAD`
  branches and 89 `WRONG_CLASS` branches were decomposed and tested against their
  own literals: zero dead branches. Toyota/scanner/Packard no longer false-hit;
  bus/tractor/fire-truck/tram/excavator all match. **Do not touch the terminators.**
- `publish_weights_pod.sh`'s lexicographic checkpoint sort is correct — upstream
  zero-pads the step number.
- `stage_c_eval_pod.sh`'s `swap()` zip-verifies each checkpoint and aborts rather
  than silently falling back to stock weights.
- `stage_a_condfix.sh`'s WebP→PNG converter is careful and idempotent.
- **`stage_c_v1_pod.sh`'s learning-rate banner gate is the pattern the rest of the
  directory needs**: it reads the config back off disk *and* greps the trainer's
  own banner, and refuses to start otherwise.

---

## The one thing that would have caught most of this

The learning-rate banner was printed in **every training log this project has ever
produced**. The evidence of C1 was sitting in plain text from the first Stage B
run onwards. Nothing read it.

Every fix below is the same discipline — assert on what the *program* reports,
not on what our own script printed:

1. Assert the trainer's `Total instances` equals the intended pool size.
2. Assert augmented images differ byte-wise from their sources, on a sample.
3. Assert the checkpoint directory being published from is the run just trained.
4. Make every `print("…FAILED…")` either exit non-zero or stop being called a gate.
