# Build backlog — vehicles in the index with no 3D model yet

Source: `vehicle_index.json` rows where `has_3d = false` (110 as of 2026-07-23).
Each build = source a CC-BY GLB (or AI gap-fill) → asset audit → body-paint
recolour → GB plates → recolour gate → publish. Ranked by UK registration volume
so real-world lookup hit-rate rises fastest. Ship only what passes the quality
bar — truth over volume.

## Cars (35)

### Tier 1 — highest UK volume, build first (15)
| Make | Model | Years | Fuel |
|---|---|---|---|
| Ford | Puma | 2019– | petrol, hybrid |
| Ford | Kuga | 2019– | petrol, diesel, hybrid |
| Hyundai | Tucson | 2021– | petrol, diesel, hybrid |
| Vauxhall | Grandland | 2017– | petrol, diesel, hybrid |
| Vauxhall | Crossland | 2017–2024 | petrol, diesel |
| Volkswagen | Polo | 2017– | petrol |
| Volkswagen | ID.3 | 2020– | electric |
| Kia | Niro | 2022– | petrol, hybrid, electric |
| Toyota | Aygo X | 2022– | petrol |
| Dacia | Jogger | 2022– | petrol, hybrid |
| Fiat | Panda | 2015– | petrol, hybrid |
| MG | MG3 | 2018– | petrol, hybrid |
| MG | HS | 2019– | petrol, hybrid |
| Land Rover | Defender | 2020– | petrol, diesel, hybrid |
| Peugeot | 5008 | 2017–2024 | petrol, diesel |

### Tier 2 — solid volume (12)
| Make | Model | Years | Fuel |
|---|---|---|---|
| Land Rover | Discovery Sport | 2015– | petrol, diesel, hybrid |
| Jaguar | F-Pace | 2016– | petrol, diesel, hybrid |
| Jaguar | E-Pace | 2017– | petrol, diesel, hybrid |
| Citroen | C5 Aircross | 2018– | petrol, diesel, hybrid |
| Mazda | Mazda2 | 2015– | petrol, hybrid |
| Mazda | Mazda3 | 2019– | petrol |
| MG | MG5 | 2020– | electric |
| Audi | Q2 | 2016– | petrol, diesel |
| Ford | Mustang Mach-E | 2020– | electric |
| Mercedes-Benz | EQA | 2021– | electric |
| Volvo | EX30 | 2024– | electric |
| Dacia | Spring | 2024– | electric |

### Tier 3 — lower volume / discontinued / niche (8)
| Make | Model | Years | Fuel |
|---|---|---|---|
| Audi | Q8 e-tron | 2019– | electric |
| Mazda | MX-30 | 2020– | electric |
| Mercedes-Benz | EQC | 2019–2024 | electric |
| Honda | e | 2020–2024 | electric |
| Mini | Electric | 2020–2024 | electric |
| Citroen | Ami | 2022– | electric (quadricycle) |
| Polestar | 3 | 2024– | electric |
| Polestar | 4 | 2024– | electric |

## Vans (16) — commercial category
Build only if light-commercials are in product scope. High UK volume first:
Ford Transit Custom, Renault Trafic, Peugeot Partner, VW Crafter, Vauxhall
Movano, Mercedes-Benz Citan, Citroen Dispatch/Relay, Fiat Scudo, Ford Transit
Connect, Nissan Primastar/Townstar, Iveco Daily, Maxus Deliver 9/eDeliver 3/T90 EV.

## Motorbikes (59) — entire category absent
Zero coverage: no bike models exist in the library. This is a **scope decision**,
not a backlog — decide whether the product covers motorbikes at all before
committing to ~59 builds. Full list in `vehicle_index.json` (class = motorbike).

## Notes
- Land Rover Defender is a rebuild: the sourced Defender was quarantined this
  batch (textured body / quality). Needs a genuinely better source.
- Range Rover Evoque / Velar / Sport, Hyundai Ioniq 5 / Santa Fe, Tesla Model 3,
  BMW 2/3/5 Series are **already covered** — they only looked missing before the
  make-normalisation join fix (commit 1539dc2).
