# Estimating rates ledger — the numbers quantities.py runs on

Learned from live sources 2026-08-14. Every constant in `quantities.py`
traces to a line here; change the code and this file together.

## Masonry

Sources: imperialbricks.co.uk bricks-per-m2 guide;
tradecalculator.co.uk mortar + wall-ties calculators; ancon.co.uk tie
spacing (AD A / PD 6697); squote.app brickwork quantities.

- 60 bricks/m² — UK standard 215×65×102.5 brick, 10 mm joints,
  stretcher bond half-brick leaf. (Flemish ~89/m² for the same face —
  headers eat bricks; another reason it costs more.)
- 9.9 blocks/m² — 440×215 aircrete, 10 mm joints.
- Mortar ≈ 0.55 m³ laid per 1000 bricks; blockwork ≈ 0.012 m³/m².
- Mix 1:4 cement:building sand (M6-ish): ~400 kg cement + ~1,800 kg
  sand per m³ of mortar.
- Wall ties 2.5/m² (900×450 staggered, AD A) + ~10% uplift for the
  extra rows at reveals, verges and movement joints.
- Sanity anchor: 3-bed detached = 7,000–10,000 facing bricks. Our
  3-bed demo computes 7,969. That agreement is the point of the anchor.

## Roofing

Sources: marley.co.uk tiles-per-m2; tradecalculator.co.uk roof-tile
coverage + batten gauge; wienerberger plain-tile datasheet.

- Concrete interlocking (420×330, 75 lap): 10.5/m² at 345 mm gauge →
  2.9 m batten/m².
- Plain tile (265×165, double lap): 60/m² at 100 mm gauge → 10 m/m².
- Natural slate 500×250 (~100 lap): ~20/m² at 205 mm gauge → 4.9 m/m².
- Membrane: sloped area × 1.15 for laps. Ridge: bedded units at 450 mm.
- Waste: tiles 5%, slate 8% (grading + breakage).

## Finishes

Sources: materialcalculator.co.uk plaster calculator;
tradecalculator.co.uk paint coverage; sleeplesstradesman.com.

- Plasterboard 2400×1200 = 2.88 m²/sheet; 10% cut waste. Board walls
  AND ceilings; skim everything boarded.
- Emulsion 12 m²/L per coat on finished surfaces; new skim takes a
  mist coat — modelled as ×1.4 on two coats.
- Skirting: room perimeter less ~0.9 m per door opening.

## Doors (the "average door diameter" answer, properly)

Sources: jbkind.com standard door sizes; doorsuperstore.co.uk chart;
residencecollection.co.uk.

- England/Wales standard internal leaf: **1981 × 762 × 35 mm** (2'6").
- Accessible/M4(2) width: **838 mm** leaf (2'9") — gives ~775+ clear.
- Also stocked: 610, 686, 726 (Scotland's metric 726×2040 set), 813.
- External doors: 1981×838×44 typical; fire doors FD30 44 mm.
- Structural opening ≈ leaf + 75–100 mm (frame + tolerance).

## Services estimating rules

Sources: electricians' forums consensus figures cross-checked against
checkatrade rewiring guides (per-point norms); plumbing merchant
guidance on 15/22 mm sizing.

- 2.5 mm² T&E ≈ 8 m per socket outlet on ring finals (two legs).
- 1.5 mm² T&E ≈ 6 m per lighting point; ~1.25 points per room.
- 15 mm copper ≈ 7 m per radiator (flow + return tails, averaged
  two-storey); 22 mm primaries ≈ 0.6 × (plan length + width) × 2.
- These are ESTIMATING rules for a bill, not routed lengths — first-fix
  drawings govern. Flagged as such in the module output.

## UK climate for design (heating side)

Sources: CIBSE Guide A Table 2.5 lineage via elmhurst/MCS heat-loss
calculators; metoffice.gov.uk regional climates; wikipedia UK climate.

- Winter design external temperatures (typical CIBSE-derived, °C):
  London −2, Birmingham −3 (heatloss.py uses −3.0), Manchester −2.5,
  Newcastle/Edinburgh −4, Glasgow −4, Aberdeen/Highlands −5 and below.
- Altitude: −0.6 °C per 100 m above the reference station.
- Warmest winters: SW England, Channel coast (Gulf Stream); coldest:
  Scottish Highlands/Grampians (record −27.2 °C Braemar); east is
  drier/sunnier, west wetter/windier (prevailing SW).
- Consequence: the same house needs ~8–15% more emitter in Aberdeen
  than Birmingham; `heatloss.DESIGN_EXTERNAL_C` should become a
  location lookup when the address pipeline lands.

## Waste allowances (explicit, never hidden in rates)

bricks/blocks/tiles 5% · slate 8% · board 10% · timber 7.5% ·
cable/pipe 10%.
