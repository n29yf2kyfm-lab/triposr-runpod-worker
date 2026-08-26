# Did a cleaner source photo actually improve the van?

**Date:** 2026-08-26 · **Answer: YES for surface damage, NO for proportions.**
Controlled: same vehicle (Ford Transit Custom panel van), same Pixal3D 1536,
same machine chain, two different input photographs.

| | van1 — red, kerbside/car-park | van2 — white, IAA 2024 stand |
|---|---|---|
| faces | 985,165 | 953,753 |
| sharp_share (>45°) | 0.0170 | **0.0456** (2.7x) |
| flanks | **gouged, streaky, a hole punched through the cargo panel** | **clean, smooth, proper shoulder crease** |
| rear | rippled smear | real doors, tail-lamp housings, bumper, plate recess |
| H/L vs real 0.388 | 0.414 (+6.6%) | **0.467 (+20.5%)** |
| W/L vs real 0.399 | 0.471 (+17.8%) | **0.605 (+51.4%)** |

## The correction against my own earlier reasoning

I argued the van1 tears were single-view hallucination on the UNPHOTOGRAPHED
side, and warned that a cleaner source "should not be expected to fix the rear."
**The rear IS fixed, and so is the near flank.** The owner's call that the source
photo was the problem was right and my caution was too pessimistic. Input
quality drives surface damage more than I credited.

## What got WORSE, and why

Proportions. van2 is **+51.4% too wide** and **+20.5% too tall** — visibly
stubby, reading like a Transit Connect rather than a Custom, and the eye agrees
with the numbers so it is not an OBB artefact.

Mechanism: the IAA shot is a LOW, near-head-on 3/4, which foreshortens length
while showing the full width. Pixal3D's known width bias (+33% recorded on the
Golf) compounds with the viewpoint. **So "clean backdrop" and "good for
proportions" are different properties of an input photo, and a stand shot
optimised for the first can be worse at the second.** Prefer a clean source shot
from a HIGHER, more oblique 3/4 that shows length honestly.

## The in-stack fix, not applied

`pipeline/machine/fit_spec.py` — diagonal-only scale onto published dimensions,
no OBB and no rotation, so seg labels stay valid. It needs a
`specs/ford_transit_custom.json` which does not exist (only Golf and Yaris do),
and writing one means asserting published dimensions. Under the project's
accuracy rule those get VERIFIED, not typed from memory, so the spec file is
left unwritten and the proportion error is reported instead.

Note `--max-mirror-frac` (default 0.02) will likely REFUSE on a van, whose
mirrors genuinely stand proud of the door line — that guard exists so an
excl.-mirrors published width is not fitted to a Z extent that includes mirrors.

## Also baked in

The "Ford Productivity PRO Electrified" livery decal on the donor's flank came
through as **illegible smeared blue text** — worse than absent. Flagged before
the run as a known risk of that photo; confirmed. Prefer an unliveried donor.
