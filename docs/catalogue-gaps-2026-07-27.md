# Catalogue coverage gaps — 2026-07-27

What a customer's registration lookup currently cannot show, measured against
`platform/catalogue/vehicle_index.json` (401 car-class rows) and
`platform/catalogue/catalogue.v2.json` (366 approved entries).

Matching honours the resolver's real behaviour — `model`, `modelFamily` **and**
`modelAliases` — which is why the honest gap count is **29**, not the ~50 a naive
make+model join reports.

---

## The cheap win: `ford-kuga-v1` is not a quality failure, it is rotated 90°

Quarantined with `quarantineReason: None` — no justification was ever recorded.
Its poster (`finished/ford/ford-kuga-v1/chrome-blue-metallic.jpg`) shows the car
**lying on its side**, with the number plate consequently mirrored.

Everything the premium bar actually asks for is already there: deep metallic
paint with clean reflections, transparent glass with a visible interior, correct
proportions, sharp shut lines, real badges. **This is a transform defect, not a
model defect**, and the Kuga is a top-10 UK seller.

Fix: correct the root rotation, re-bake the GB plate, re-render, un-quarantine.
No sourcing, no licence work, no new asset. Highest value-per-pound on this list.

---

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
