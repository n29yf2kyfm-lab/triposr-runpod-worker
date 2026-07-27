# Catalogue coverage gaps — 2026-07-27

What a customer's registration lookup currently cannot show, measured against
`platform/catalogue/vehicle_index.json` (401 car-class rows) and
`platform/catalogue/catalogue.v2.json` (366 approved entries).

Matching honours the resolver's real behaviour — `model`, `modelFamily` **and**
`modelAliases` — which is why the honest gap count is **29**, not the ~50 a naive
make+model join reports.

---

## CORRECTION — `ford-kuga-v1` is genuinely broken, not merely rotated

**My first read of this asset was wrong and is retracted.**

I inferred from the poster (`chrome-blue-metallic.jpg`) that the car was a premium
model lying on its side — a transform bug worth a free recovery. Then I rendered
the actual GLB through the render endpoint. It is a **collapsed shell**: the body
is flattened to a slab, the wheels are detached and floating, and the plate is a
separate sliver beside the car.

Measured on the mesh (which decodes in trimesh, 186k verts, so these numbers are
real): `L 2.96 × W 1.78 × H 0.37`, i.e. ratios `1 : 0.60 : 0.125`. A Ford Kuga is
`1 : 0.41 : 0.36`. It is 147% too wide and 35% of the height it should be, and
**no rotation changes a ratio**. All four colour variants are identically
collapsed.

The poster was rendered from an earlier, healthy state of this asset; the
finishing pipeline flattened it afterwards. `technicalStatus: "failed"` was
accurate — nobody wrote the reason down, which is why it looked recoverable.

**A poster is not evidence about the GLB it is named after.** Cost of learning
that: two render jobs, about a penny.

Recovering the Kuga means re-processing from the CC-BY source
(`sketchfab.com/3d-models/c1605bbcdf2e4aafb1c66fc8aacf6f19`, "Ford Kuga ST-Line"),
not editing the finished file — and first finding what in the finishing pipeline
flattens a model, since that bug produced this.

## Do NOT trust trimesh extents on this library

I then swept all 366 approved assets measuring bounding-box proportions, and got
"331 of 366 squashed". **That result is invalid.** 267 of them reported extents of
exactly zero, which is not a flat car — it is trimesh failing to decode the file.

Every asset checked is **Draco-compressed**. `CLAUDE.md` line 207 already says so:

> Draco GLBs render BLANK in the local model-viewer harness unless
> dracoDecoderLocation points at the local decoder. A blank render or trimesh
> score of a _uc.glb proves nothing about the model.

The warning was already written down and I walked into it anyway. Some Draco files
partially decode and return plausible-looking wrong numbers, which is worse than
failing outright — `porsche-911-carrera-4s-v1` returned `1 : 0.199 : 0.186`, and
that number means nothing.

**The correct instrument is the render path**, which uses Blender and decodes Draco
properly — i.e. the contact-sheet review that already exists
(`pipeline/qc/review_sheets.py`, reusing existing posters at zero render cost),
with the owner calling the numbers, exactly as `CLAUDE.md` requires. Any
catalogue-health claim must come from that, not from a local mesh library.

## Gaps that already have an asset (7)

Six were scrapped by the owner on 2026-07-23 for being below the premium bar.
Those judgements stand — they are listed so nobody re-sources them by accident
and so it is clear the asset exists but was rejected.

| Model | assetId | Status |
|---|---|---|
| Ford Kuga | `ford-kuga-v1` | **no reason recorded — rotated, fixable** |
| Fiat Panda | `fiat-panda-v1` | opaque black windows. Also note: source is the **classic** Panda, while the index wants 2015-2026 — fixing the glass would still not fill this gap |
| VW Polo | `volkswagen-polo-2016-v1` | owner-scrapped, below premium bar |
| Kia Niro | `kia-niro-2021-v1` | owner-scrapped, below premium bar |
| Hyundai Tucson | `hyundai-tucson-2014-v1` | owner-scrapped, below premium bar |
| Honda e | `honda-e-v1` | owner-scrapped, below premium bar |
| Land Rover Defender | `land-rover-defender-x-undated-v1` | owner-scrapped, below premium bar |

## Gaps with no asset at all — must be sourced (22)

Ordered roughly by UK relevance, not alphabetically.

**High-volume, would be hit often**
- Ford Puma · Vauxhall Grandland · Vauxhall Crossland · Peugeot 5008
- Land Rover Discovery Sport · Jaguar F-Pace · Jaguar E-Pace · MG HS
- Audi Q2 · Toyota Aygo X · Dacia Jogger

**EV/newer, growing share**
- Ford Mustang Mach-E · Mercedes EQA · Mercedes EQC · Volvo EX30
- Mazda MX-30 · Mini Electric · Dacia Spring · Polestar 3 · Polestar 4
- Citroen C5 Aircross · Citroen Ami

---

## Why this list is worth more than the fine-tune

Each row is a real registration lookup that returns nothing to a paying customer.
Filling one costs a few pennies on the existing scale-to-zero render endpoint,
against ~$16 for a geometry training run whose output cannot even be recoloured
(`docs/alam3d-forensic-report.md` F3: one fused shell, baked texture, no
body-paint material).

## Order of work

1. **Rotate and re-publish the Kuga.** One asset, no sourcing, top-10 seller.
2. **Re-check the other six quarantines against the sheets** — but only the owner
   calls those numbers (`CLAUDE.md`: "A human eyeballs fidelity and calls out the
   numbers to cull").
3. **Source the 22**, high-volume first, CC-BY/CC0 only with provenance recorded,
   contact-sheet review before anything is published.

## Method note

Counts here come from the committed catalogue and index files, not from memory.
The script that produced them normalises make/model, expands family and alias
fields, and restricts the index to `class == "car"` (excluding its 59 motorbike
and 34 van rows).
