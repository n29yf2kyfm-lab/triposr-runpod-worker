# UK target list — what to model, in what order

Built from the rawest public source there is: DfT **VEH0120 (UK)**, every
licensed vehicle at the end of the quarter by body type, make, generic model
and model. Downloaded 2026-10-15 (2026 Q2 figures):

    https://assets.publishing.service.gov.uk/media/6aad4b12086ce7c57b8186f3/df_VEH0120_UK.csv

The 41 MB CSV is not committed; `join.py` expects it as `df_VEH0120_UK.csv`
in this directory (one step: rank it with the snippet at the top of `join.py`'s
history — see `ranked_by_body.json`, which is the ranked result, top 1,500 per
body type, kept in git).

## What the data says (licensed, UK, 2026 Q2)

| body type | vehicles | generic models | models for 90% | 95% | 99% |
|---|---|---|---|---|---|
| Cars | 34.9 m | 2,386 | 226 | 326 | 598 |
| Light goods (vans, pickups) | 4.96 m | 1,604 | 36 | 55 | 125 |
| Motorcycles | 1.49 m | 3,109 | 327 | 526 | 1,081 |
| Heavy goods (trucks) | 0.54 m | 679 | 43 | 71 | 180 |
| Buses and coaches | 0.14 m | 400 | 27 | 40 | 77 |

"Generic model" is DfT's grouping (FORD FIESTA spans every Fiesta); a 3D
catalogue entry is one model-generation, so the final asset count is roughly
2–3× the generic-model count for cars.

## `targets.csv` — the list

1,335 targets: cars to 99 % of the parc (598), vans 99 % (125), trucks 95 % (71),
motorbikes 95 % (526), buses 80 % (15). Columns: class, rank, make, genModel,
licensed count, cumulative %, matching approved catalogue assets, rig-survey
result of the best match (`ok` / `partial` / `refused` / `none`), and whether at
least one match is licence-clean for commercial use (not CC NonCommercial).

Join result on the day it was built:

| class | targets | have a model | opens today | licence-clean |
|---|---|---|---|---|
| car | 598 | 299 | 231 (183 before rigger 1.1.0) | 287 |
| van | 125 | 32 | 17 | 29 |
| truck | 71 | 7 | 4 | 6 |
| motorbike | 526 | 0 | 0 | 0 |
| bus | 15 | 7 | 2 | 6 |

990 targets have no model at all. `source.py` searches Sketchfab anonymously
(commercial-OK licences only: CC-BY, CC-BY-SA, CC0) for every target and writes
`candidates.jsonl`; downloading and surveying a candidate needs
`SKETCHFAB_TOKENS` and Blender, which `source.py` deliberately does not use.
