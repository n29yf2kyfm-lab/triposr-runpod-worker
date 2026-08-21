# `pipeline/machine/mobile/` — the mobile-performance gate

Decides whether an asset can actually be served to a customer on a phone, and
proves it with measurements rather than arithmetic.

```
mobile_metrics.py   what the file weighs and what it will cost a device   (no browser)
load_probe.py       how long it takes to become a picture, over an emulated link
fidelity.py         did the reduction change what the customer SEES, and
                    did it silently delete a component
mobile_gate.py      orchestrator: build the ladder, gate every rung, run the
                    negative controls, emit PASS / FAIL / BLOCKED
```

Nothing here is specific to one car. Cameras, close-up zones, critical materials
and the node list are derived from whatever master you hand it.

```bash
python3 pipeline/machine/mobile/mobile_gate.py CAR.glb --out-dir OUT
python3 pipeline/machine/mobile/mobile_gate.py CAR.glb --out-dir OUT \
        --ladder draco,dec50,dec30 --skip-load          # faster iteration
python3 pipeline/machine/mobile/mobile_metrics.py CAR.glb           # metrics only
python3 pipeline/machine/mobile/load_probe.py CAR.glb --repeats 5   # timing only
python3 pipeline/machine/mobile/fidelity.py MASTER.glb CAND.glb --out-dir /tmp/f
```

Requires `gltf-transform` (present at `/opt/node22/bin`), `gltf-validator`
(global npm install), and Chromium under `PLAYWRIGHT_BROWSERS_PATH`. It never
runs `playwright install`. `model-viewer` and the meshopt/Draco decoders are
looked up through `viewer_check.py`'s vendoring paths; if none are present the
browser stages return **NOT_TESTED** instead of a number.

---

## Why this exists as its own thing

`mobile_export.py` is a good tool aimed at a different file. It was written and
calibrated against a **texture-majority** master (37.35 MB of PNG against
27.77 MB of geometry) and its whole strategy — resize, WebP, dedup image
bufferViews — follows from that one fact.

`car_rebound.glb` is the inverse: **0 images, 0 textures, 100.0 % geometry.**
Every texture stage in `mobile_export` is a no-op on it, and the +12.70 MB Draco
image-duplication trap that dominates its docstring *cannot fire* — there are no
images to un-share. The strategy flips between cars, so the payload split is the
first thing `mobile_metrics` prints.

`mobile_export` also gates on **silhouette IoU**, and that is the specific thing
this gate exists to replace. Measured on this programme: a control that deleted
**96 % of all triangles still scored min IoU 0.991.** A car's outline is smooth
and low-frequency; alpha coverage barely moves while the surface is destroyed.
PSNR caught that same case at 26.93 dB against a healthy 37.81 dB.

And nothing in the repo measured **time**. `viewer_check.py` says so in its own
docstring — "says NOTHING about device frame rate or load time". Every load-time
claim on this programme before now was arithmetic on a file size, which misses
the half that codec choice actually moves: a 3.65 MB Draco file is 7.9× smaller
than its source and *not* 7.9× faster to first frame, because the Draco decode
is CPU work the uncompressed file never does.

---

## The budget, and why each number is what it is

Set in `mobile_metrics.DEFAULT_BUDGET`; override with `--budget-json`. These are
four **independent** constraints — passing one says nothing about the others.

| axis | limit | where the number comes from |
|---|---|---|
| download bytes | **5 000 000** | The project's own standing spec. CLAUDE.md, "THE PRODUCTION BRIEF — standing spec for the machine (owner-relayed, 2026-08-18)", phase 10: *"target ~5MB mobile GLB, ZERO validator errors"*. An owner-relayed number beats anything invented here. |
| triangles | **350 000** | Justified on **memory and decode time, both measured**, and explicitly **not** on frame rate — no phone is attached to this container. 350 k tri ≈ 250 k vert ≈ 10 MB of resident buffers, against 28.7 MB at 985 k. Decode time is measured per rung by `load_probe` and scales with it. |
| draw calls | **60** | 30 primitives is already trivial for any WebGL renderer. On this programme it is also a **floor**: the viewer toggles components by node, so primitives may not be merged away to reduce it. |
| GPU buffer bytes | **24 000 000** | Computed exactly from the decoded accessors — the number the download size hides. Codec choice does not change it: a 3.65 MB Draco file still uploads ~28 MB. Measured `performance.memory` delta on load is ≈1.2× this, because three.js retains the CPU-side typed arrays. **This limit is a judgement call**, not a measurement: the per-tab memory ceiling of a real phone browser was not measured. |
| texture VRAM | **64 000 000** | RGBA8 + mips from the summed texel budget. Zero on a texture-free car; the axis is kept because the next car will have textures. |
| NORMAL coverage | **1.0** | Not negotiable. trimesh submesh exports drop NORMAL accessors and the studio clearcoat renders that as crumpled foil — a lesson this project has now paid for three separate times, twice *after* writing it down. Asserted on the **re-read written file**, every time. |

`loadSecondsMax_typical4G` (4.0 s) is reported alongside but is **a stated
product judgement, not a measurement** — say so whenever it is quoted.

---

## The four must-not-break properties

Checked on every written output, by `mobile_gate.gate_one`.

**G1 glazing** — `glass_probe` must return `clear/proven`. Opaque glazing is a
hard SCRAP under the owner's confirmed 2026-08-11 ruling; 119 live cars (10.3 %
of the catalogue) were culled on it alone. The probe's own rules are reused
verbatim by redirecting `glass_probe.gltf_json` at a local file — they are **not
reimplemented**, because "a retro check that reimplements them drifts from the
wave check, and then the two disagree about the same car."

> **`glass_probe` alone is not sufficient here, and this gate proves it.** The
> probe reads the *material table*. A decimator that collapses a window pane
> leaves the `glass` material and its `transmissionFactor` untouched, so the
> probe still returns `clear/proven` on a car with no glass in it. G1 is
> therefore `glass_probe` **and** `fidelity.geometry_retention` on glazing
> **area**. Negative control **NC2** exists to demonstrate exactly this blind
> spot, and it does.

**G2 tyres** — the tyre material must read as black rubber in the shipped glTF.
Honest scope: CLAUDE.md 2026-08-11 records that a glTF tyre probe was validated
at **recall 0/8** against 131 ground-truthed cars and cannot see the per-corner
render artefact. G2 rules out body-paint-over-rubber and the flat shell, and
detects a reduction that changed the rubber. It is an invariance check, not a
verdict on the car.

**G3 respray** — a name-targeted respray of `carpaint` must move the body and
must **not** move glazing, tyres, rims or lamps. Run through the live
`<model-viewer>` material API — the same path the product uses — with a flat
emissive **material-ID pass** to attribute every changed pixel to a material.
Gated in **both** directions: a respray that moves nothing ships eight identical
files (`corolla-cross` at dist 0.004); a respray that moves everything is the
`toyota-auris` cov 1.000 retirement. CLAUDE.md 2026-08-15: every automated gate
passed a car whose separation was fake and only the respray control caught it —
*"the control is not a formality, it is the verdict."*

**G4 validator** — official Khronos `gltf-validator`, **zero errors**.

---

## Negative controls — every run builds its own

> *"A metric that has never returned a failure is not a metric."* Two checks on
> this programme were found to have never once fired: a `WRONG_CLASS` regex
> ending in a literal `\b`, and a wheel gate that was empty by construction.

Every run of `mobile_gate` constructs three controls and **requires them to
fail**:

| control | how it is built | what it must prove |
|---|---|---|
| **NC1** over-decimated | `simplify --ratio 0.02 --error 1 --lock-border false` | the fidelity metric FAILS it — and IoU is expected to survive, reproducing the documented trap in the same run |
| **NC2** glazing gutted | `gut_material_geometry(..., "glass", keep_every=40)` — deletes the glass *geometry*, leaves the *material table* untouched | `glass_probe` still PASSES (the blind spot, demonstrated) and `geometry_retention` FAILS (the blind spot, covered) |
| **NC3** paint on rubber | `rebind_material(..., "Tyre_Rubber" → "carpaint")` | the respray control FAILS, i.e. it can actually see leakage — this is the control *for* the control |

**If any control does not fire, the gate reports `BLOCKED`, never `PASS`.** A run
whose instruments cannot be shown to work has measured nothing.

`gut_material_geometry` and `rebind_material` are control generators only. They
are never production stages and must never be used as ones.

---

## Things measured the hard way, kept so nobody re-pays

* **Close-up cameras must target ONE node.** The first draft matched
  `wheel_f[lr]_(rim|tyre)` and unioned both front wheels, so the "close-up" bbox
  spanned the full track and framed the whole car. `lamp_[lr]` matched head *and*
  tail lamps, spanning the car's length, and framed it at 11 m. Both were caught
  only by **looking at the render**.
* **…and the radius must be banded.** An unclamped node-diagonal radius put the
  lamp camera *inside the nose* and rendered the cabin floor. Radius is clipped
  to 35–55 % of the car's own diagonal: always outside the body, always about
  twice as close as the full-car view.
* **Quote WORLD extents, never raw.** Node transforms matter. On
  `car_rebound.glb` the raw union of vertex bounds reads 4.2825 × **1.7798** ×
  1.7887 while the true world bounds are 4.2825 × **1.4554** × 1.7887 — the raw
  height is 22 % too tall and is not a dimension of anything.
* **A whole-model bbox min-Y is not a grounding check.** It passes as long as any
  single vertex touches the floor. On `car_rebound.glb` the model bbox min-Y is
  +0.3 mm — and the two FRONT tyres are 183 mm and 190 mm *in the air*, a 4.07°
  nose-up pitch. `tyreNodeMinY` reports per tyre for exactly this reason.
* **The master render is cached across ladder rungs.** An uncompressed 28.7 MB
  GLB takes ~2 minutes to load under SwiftShader and produces byte-identical
  frames every time; re-rendering it per rung dominated the run. The cache key
  includes the master's size+mtime *and* the camera signature, so a changed
  master or camera set cannot silently reuse stale reference frames.
* **`gltf-transform dedup` must not be allowed to merge MATERIALS.** Recorded in
  `mobile_export.DEDUP_FLAGS` and still true: on a texture-free car
  `Rim_Alloy` and `carpaint` differ, but on the textured Golf master they became
  byte-identical once their images deduped, and a default `dedup` merged them —
  a respray of the body would then paint the wheels.
* **Decode before reading accessors.** trimesh and this module's own reader are
  both blind to Draco/meshopt; trimesh returns an all-zero vertex array and
  prints a "placeholder zeros" line that is easy to miss. `copy` decodes,
  and `dequantize` is *additionally* required after meshopt.

---

## Measured on the first subject (`car_rebound.glb`, Golf Mk8 test bed)

Kept here as the calibration this tool's thresholds were set against, and as the
answer to "how far can a car like this be decimated": **barely at all.**

| ratio | triangles | MB (draco) | PSNR min | IoU min |
|---|---|---|---|---|
| 1.00 | 985,204 | 3.654 | **39.81** | 0.99762 |
| 0.95 | 935,906 | 3.543 | 35.96 | 0.99571 |
| 0.90 | 886,412 | 3.434 | 34.10 | 0.97594 |
| 0.80 | 788,049 | 3.206 | 33.87 | 0.97433 |
| 0.65 | 639,508 | 2.839 | 33.21 | 0.98985 |
| 0.50 | 492,018 | 2.446 | 29.92 | 0.96576 |
| 0.30 | 294,133 | 1.792 | 24.57 | 0.97683 |
| 0.20 | 196,193 | 1.286 | 21.73 | 0.94617 |
| NC1 | 76,029 | — | 15.45 | 0.87926 |

**The first 5% of triangles costs 3.85 dB.** The loss is not the silhouette — it
is the clearcoat specular highlight breaking up across large smooth panels
(64% of large-delta pixels land on painted body against a 31% base rate). A car
whose look is a mirror finish on big panels is far more decimation-sensitive
than its triangle count suggests.

**And this table settles the IoU argument in our own data rather than by
citation: the column is NOT MONOTONIC IN DAMAGE.** Ratio 0.30 scores min IoU
**0.97683** — *higher* than ratio 0.90's 0.97594 — at two thirds fewer triangles
and 9.5 dB worse appearance. An IoU gate would prefer the worse file. Use PSNR.
