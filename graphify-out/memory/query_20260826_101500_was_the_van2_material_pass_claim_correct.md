# Was the van2 "material half passes" claim correct?

**Date:** 2026-08-26 · **NO. Both reviewers failed it and both were right.**
Three defects were found that my own gates passed, and the decisive evidence was
a matID render I had not run.

## What I claimed, and what was actually true

I claimed transparent glazing **correctly placed**, on the strength of
`glass_where` rear-third = 3.16% (threshold 15%, no flag). Measured afterwards:

    glass area STRONGLY UP-FACING (|ny| > 0.7):  64.52%
    glass area in the ROOF ZONE (top 15% height): 29.61%

**The machine glazed the ROOF and the upper cargo flank of a panel van.**
Confirmed two independent ways: the geometry above, and a matID render
(interior=magenta, glass=blue) showing blue across the roof and upper rear-left
flank at az125.

## THE GATE HAD A HOLE EXACTLY WHERE THE DEFECT LIVES

`glass_where` flagged only the REAR THIRD. A van's cargo box spans MID and rear,
so a glazed cargo flank scores 3.16% at the rear and passes in silence. Fixed:
the tool now reports `behind_cabin_pct` AND, more importantly, a **roof share**,
which needs no body-style judgement at all — no production vehicle has a glass
roof bar a panoramic one, so up-facing glazing high on the car is wrong for ANY
input. The old rear-third heuristic needed to know whether the car was a panel
van or a Tourneo; the roof test does not.

## MY "NOT THE INTERIOR BUG" ARGUMENT WAS UNSOUND

I argued the 82.5% interior FACE share was genuine cargo-bay interior and not the
recorded "unseen defaults to interior" bug, because the beauty render showed no
dark blotching. **That reasoning is invalid**, and the reviewer's counter was
exact: absence of blotching only rules out mislabels that are VISIBLE, and this
build does not paint interior dark, so invisible mislabels produce zero
blotching by construction. It also noted 17.5% of faces seen against the 18.6%
that CONVICTED the Golf — my exculpatory number was one point from the guilty one.

The matID render settled it: **interior label sits on EXTERIOR bumpers, lower
valances, sills and arch lips** — the grazing-angle surfaces that are the
recorded signature. It also explains the grey unpainted bumper patch visible in
the blue control: those faces take no paint under a respray.

**Rule: reason about label correctness from a matID render, never from the
absence of an artefact in a beauty render.**

## Other confirmed defects

* **Lamp label collapsed**: `Lamp_Lens` 0.17% -> 0.02% of area, DINO returned
  ZERO lamp boxes in several views. No green anywhere in the matID. Consequence
  visible in the blue control: **the headlamps take body paint.**
* **The blue control was ONE view** (az215), so the rear and off-side were never
  observed. "Held under the control" was asserted over surfaces the control did
  not see.
* Livery mirrored and backwards on the off-side flank (caught earlier).

## One place the reviewer's NUMBER was too strong, checked rather than accepted

It attributed the whole 27.21% mid-third to the cargo flank. Deciles say the
0.3-0.4 band (18.32%) is plausibly cab-door glass, so genuine behind-cabin
glazing is ~12.04%, not 27%. **The direction was right and the magnitude was
not** — worth checking, because this project's rule is not to take an agent
report at face value.

## THE PANE-INTEGRITY CLAIM DIED TOO — ox killed it, and it was right

I reported **1.62 loops/component, "best measured on a generated car"**. ox
pointed out that figure was computed over the SAME CONTAMINATED LABEL SET, i.e.
with the roof panels in it — so it is not the topology of actual glazing.
Measured by stripping up-facing and roof-zone faces and re-running the identical
Blender path:

    labelled "glass"      52 components,  84 loops, 32 holes   -> 1.62 loops/comp
    74.3% of that AREA is roof / up-facing
    ACTUAL glazing       143 components,  74 loops,  0 holes   -> 3,182 faces

**143 disconnected fragments averaging ~22 faces, for what should be four or
five panes.** The real glazing is fragment soup; the flattering number came from
large, topologically simple roof panels dragging the average down. A metric
computed over a label set is only as good as the label set — and nothing had
checked the label set.

## What actually survives

**Tyres, and only tyres.** `baseColorFactor` 0.047 from the file, dark in the
control, dark in every view. Every other material claim on this asset was a
label-statistic artefact.
