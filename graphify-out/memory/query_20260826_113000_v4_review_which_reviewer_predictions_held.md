# van2 v4 review — which reviewer predictions held when checked?

**Date:** 2026-08-26 · Both reviewers FAIL the claim as worded. Three of their
concrete predictions were checkable; the results split.

## HELD

**Denominator shopping (both reviewers, independently).** I quoted glass as
**5.07% of NON-INTERIOR area** and called it "essentially on the catalogue
median (5.75%)". The band was calibrated on **% of TOTAL area**. On that basis
this van is **1.42%** — inside the band but near the FLOOR, next to the Polo's
1.12. The repo already records that the exterior-seen denominator was "a
different wrong denominator" and I used it anyway. The eviction claim stands;
the median gloss does not.

**"Proportions correct" is by construction.** fit_spec scales the bbox ONTO the
spec, so "within 1%" measures that the operation ran. Per-slice taper is
unmeasured. Correct wording: "bounding-box extents now match sourced V710
L1 H1 dimensions."

**A dark jagged band at the windscreen HEADER** (ox). Real, visible at 3x on
az215 in both neutral and blue — the sliver-fragment boundary.

## DID NOT HOLD

**"The roof still isn't painted" (ox).** At 3x the az215 roof is plainly BLUE.
The dark patch ox saw is the windscreen HEADER, not the roof. Roof-zone 0.0%
holds.

**"No shipped-file glazing evidence; KHR may have been stripped by the trimesh
round-trip" (Fable 5).** Measured on the shipped v4: `alphaMode=BLEND`,
`baseColorFactor` alpha **0.3529**, byte-identical to pre-fix, and
`extensionsUsed: None` — there were never any KHR extensions to lose. The
concern was reasonable and the answer is clean.

**"The verbatim-normals defect line is contradictory" (Fable 5) — HALF right,
and the resolution is useful.** normals_fix DOES cure the bulk: median
|stored . recomputed| = **1.0000** for both carpaint and glass, so the defect
line is stale for most of the mesh. But glass has a bad TAIL — mean **0.6396**
against carpaint's 0.9318 — because isolated slivers make an area-weighted
normal average degenerate. **That tail IS the sliver artefact**, so the two
observations are the same defect seen from different ends.

## INCONCLUSIVE — and said so rather than guessed

**Wheel ellipse (Fable 5).** Predicted the x/y anisotropy 5.502/4.593 = 1.198
would leave 20% elliptical wheels. Two measurement attempts were both
CONTAMINATED — the Tyre_Rubber node gained 30k annulus faces in v4, so quadrant
clustering no longer isolates one wheel (one "wheel" measured 13.7:1). On the
two wheels that read cleanly: 1.178 -> 1.303 and 1.20 -> 1.157, against ~1.43
if uncorrected. **Neither confirmed nor refuted.** `wheel_metrology` is the
right instrument and was not run.

## Standing lesson

A reviewer's prediction is a hypothesis, not a finding. Five were checked here:
three held, two did not, one could not be settled with the instrument to hand —
and saying which is which matters more than the verdict.
