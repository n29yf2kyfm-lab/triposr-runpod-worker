# Dwelling sizes — what UK houses actually measure

Learned from live sources 2026-08-14 (gov.uk NDSS table; dwh.co.uk
average-house-sizes; squaremeterstosquarefeet.com UK size datasets;
new-builds.co.uk space standards; homebuilding.co.uk + chartgarages
garage guides; middevon.gov.uk garage widths note). The first-pass
3-bed-with-garage demo measured 184 m² — a 4/5-bed executive footprint
wearing a 3-bed name. These are the honest numbers to design to.

## Whole-dwelling GIA (gross internal area, garage EXCLUDED)

NDSS minimums (2-storey): 2b4p 79 · **3b5p 93** · 4b6p 106 ·
3b4p 84 m². The volume-builder target for a 3-bed is exactly the
93 m² minimum, give or take a couple of m².

Market averages: terraced 88 · semi 97 · all-detached 149 (skewed by
4/5-beds) · **3-bed averages ~94 m²**, 4-bed ~138 m². A 3-bed detached
with integral garage and ensuite runs ~105–125 m²; past 130 m² it is a
4-bed that hasn't admitted it.

Late-80s/90s developer 3-bed semis: 70–82 m² — smaller than today's
minimums; relevant when matching extensions to existing stock.

## Room sizes (modern new-build norms)

- Living room ≈ 17 m² (1970s peak was 24.9 — don't draw 1970s rooms
  into 2020s houses).
- Master bedroom ≈ 13.4 m²; NDSS double ≥ 11.5 m², principal ≥ 2.75 m
  wide, other doubles ≥ 2.55 m; single ≥ 7.5 m², ≥ 2.15 m wide.
- Kitchen or kitchen/diner ≈ 12–18 m²; family bathroom ≈ 4–6 m²;
  ensuite ≈ 3–4.5 m²; ground WC ≈ 1.8–2.5 m².
- Built-in storage: 2.5 m² for a 3-bed (NDSS), ≥ 1.5 m ceiling counted.
- Floor-to-ceiling 2.4 m typical (NDSS asks 2.3 m over 75% in London).

## Garages

- Single garage internal: commonly **2.4–3.0 wide × 4.9–6.0 deep**;
  2.4 wide is legacy-tight for modern cars — 2.9–3.0 × 5.6–6.0 is the
  usable modern single; genuinely useful = 3.6 × 6.5.
- Double: ~5.5–6.0 × 6.0. Garage door: 2.134 (7') legacy, **2.286 m
  (7'6") standard**, up-and-over or sectional.
- Eaves ~2.1–2.4 m. Integral garages sit a step (150 mm) below dwelling
  floor with a fire door (FD30) into the house.

## Footprints and plots

- A 93–110 m² two-storey 3-bed = **46–55 m² per floor** → footprints
  like 7.0×7.0 to 9.5×6.5; add a 3.0 m garage bay for integral types.
- Detached frontage: plot ~10–13 m wide for a 3-bed detached with
  drive; standard suburban plot ~250–400 m²; rear gardens 9–11 m deep
  on volume estates.

## Consequence for the pipeline

1. The demo redrawn to: footprint 9.4 × 7.2 (house 6.5 + garage bay
   2.9), dwelling GIA ≈ 119 m², garage 16.2 m², rooms at modern norms.
2. planning.py / regs NDSS pack should WARN when a "3-bed" exceeds
   ~135 m² (mislabelled) as well as when below 93 (substandard).
3. quantities/pricing sanity anchors keyed to per-floor area bands.
