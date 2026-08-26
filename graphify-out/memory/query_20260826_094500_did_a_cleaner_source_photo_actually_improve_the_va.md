# Did a cleaner source photo actually improve the van?

**Date:** 2026-08-26 · **Answer: surface GEOMETRY improved, proportions got
worse — but the cause is NOT isolated and this must not be read as a controlled
result.**

## CORRECTION, forced by BOTH reviewers independently (Fable 5 and ox)

The first version of this entry called it "Controlled: ... ONLY the input photo
differs." **That is misleading and both reviewers rejected it.** The photo
differs in at least THREE ways at once:

1. **cleanliness** — studio stand vs kerbside/car park;
2. **camera geometry** — the IAA shot is LOW and near-head-on, the red one is a
   normal kerbside 3/4. My own stated mechanism for the width error blames the
   VIEWPOINT, i.e. a different variable from the one the conclusion credits;
3. **manual repair** — I inpainted an info kiosk out of the near flank, so part
   of the "clean input" is my hand, not sourcing.

n=1 vehicle, three variables moved, two effects observed. The direction is
credible; the ATTRIBUTION is not established. Do not turn this into a sourcing
policy without decoupling it — one more ~$0.30 run from a clean photo at proper
oblique 3/4 geometry answers it.

**And `sharp_share` (0.0170 -> 0.0456) cannot carry the surface claim**, per this
project's own noise-sphere control: a high crease/sharpness number is close to
uninformative because noise fills it. The renders carry the claim; the number is
corroboration at best.

| | van1 — red, kerbside/car-park | van2 — white, IAA 2024 stand |
|---|---|---|
| faces | 985,165 | 953,753 |
| sharp_share (>45°) | 0.0170 | **0.0456** (2.7x) |
| flanks | **gouged, streaky, a hole punched through the cargo panel** | **clean, smooth, proper shoulder crease** |
| rear GEOMETRY | rippled smear | real door shut lines, hinge hardware, bumper, plate recess |
| rear TEXTURE | smear | **still a grey bare-metal smear** — "clean panels" was overstated |
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

## Also baked in — and worse than first reported

The "Ford Productivity PRO Electrified" livery decal came through as **illegible
smeared blue text**, flagged before the run. What I MISSED, and Fable 5 caught:
**it is MIRRORED onto the never-photographed flank and reads BACKWARDS** at
az215 and az125. Verified by 2x crop. Backwards lettering on a shipped asset is
instantly wrong to a customer — a worse identity defect than an illegible smear.
**Prefer an unliveried donor**, and check the off-side of any single-image
generation for mirrored text.

## Other defects on the raw mesh, from the two reviews

spike/rod artefacts at the rear roofline (antenna class); a hallucinated ribbed
vent strip down the right rear door; glazing tone bleeding onto the A-pillar and
roof leading edge; a ragged gap under the rear bumper and a dark blob under the
floor (measure ground contact from TYRE-region minima, never the whole-model
bbox); the grille badge is an illegible lump and both plates are illegible — so
"badge and plate present" must not be booked as identity from a thumbnail, which
is the same correction Fable 5 made on the previous van.
