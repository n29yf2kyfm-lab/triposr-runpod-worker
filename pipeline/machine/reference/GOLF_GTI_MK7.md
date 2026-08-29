# Reference car: `volkswagen-golf-mk7-v1` — "Volkswagen Golf GTI Mk7"

Live, approved catalogue asset. Measured 2026-08-29 at the owner's
suggestion — "we've got a GTI in the library, why don't you take the whole
measurements?" — after a day of thresholds set by guesswork. This is the
POSITIVE CONTROL the repo's own standing rule asks for: *a threshold with
no positive control behind it is a guess.*

Frame: catalogue convention, **length on Z, nose at −Z, Y up**.

## Measured

| quantity | GTI | our generated cars |
|---|---|---|
| L × W × H | 4.500 × 2.111 × 1.434 | 4.258 (fitted to spec) |
| W/L | 0.4691 | — |
| H/L | 0.3186 | — |
| **glass, outer, % of total area** | **5.33%** | 6.49% – 9.25% |
| paint, % of total area | 26.95% | — |
| DLO band (beltline→rail) | 422 mm | 383 – 392 mm |
| tyre contact vs model floor | **0.0 mm** | 150 mm out before `level_car` |
| total faces | **~97,000** | 1,460,000 – 1,490,000 |
| file size | 1.05 MB | 18 – 22 MB draco |

## What this changes

1. **Our glass band is too generous.** The real car is 5.33% of area; ours
   run 6.49–9.25%. The 1.0–13.0% band was calibrated across ten mixed
   catalogue cars and is wide enough to pass a car with a fifth too much
   glazing. Against this reference our labels are 20–75% over.
2. **Tyres sit EXACTLY on the model floor** — 0.0 mm. A real asset is
   grounded on its contact patches, which is what `level_car` now enforces
   and what nothing enforced before.
3. **The glazing is DOUBLE-SKINNED**: `Glass_*` outer plus `GlassInside_*`
   inner, four material families (Window, WindowDark, GlassClear,
   GlassRed). Our chain builds a single skin. That is very likely why real
   glass reads as glass and ours reads as a membrane.
4. **97k faces against our 1.5M.** A shipped catalogue car is fifteen times
   lighter than what we generate. Relevant to the mobile serving gap.
5. Material scheme worth copying: paint / Window / WindowDark / GlassClear
   / GlassRed / tyre / wheel_rim / Light / Interior / InteriorA /
   InteriorTilling / Grille1 / Badge / plate_front / plate_rear, plus
   per-corner Rim + Rotor + Tire and separate calipers.

## What it CANNOT calibrate

**B-pillar width.** The asset carries 817 door-glazing faces against our
130,000, so a vertex-density read of the glazing gaps returns the
tessellation, not the pillar — the "gaps" come out quantised at 19.7 mm
steps. The structural breaks are visible (276 mm, 158 mm, 138 mm) but they
cannot be attributed to a specific pillar at that resolution. Measure
pillar width from a photograph or a denser asset, not from this one.
