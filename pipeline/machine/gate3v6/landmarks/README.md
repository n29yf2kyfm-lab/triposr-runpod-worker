# gate3v6/landmarks — reference photograph → numeric fascia landmark spec

Turns the two GATE 3 v6 reference photographs into `LANDMARK_SPEC.json` / `.md`, plus an
annotated `LANDMARK_OVERLAY.png` a human can check by eye in one glance.

Vehicle (ASSUMPTION, owner-authorised): VW Golf Mk8 pre-facelift, MY2020, **Style**, UK RHD,
five-door. Published width 1789 mm.

## The one thing to read before reusing any of this

**A number-plate homography is a good LOCAL metric anchor and a bad LONG-RANGE one.**

The plate is the only object of known metric size in either photograph, so it is the scale anchor.
It works: the pre-registered validation (rectified plate characters vs BS AU 145d — 79 mm height,
438 mm block, 41 mm margins) passed on every criterion, on pixels the homography never saw.

But the projective term of a homography fitted to a 520 × 111 mm target is **noise-dominated**, and
three independent attempts to pin the camera all failed:

* single-homography focal recovery → `f²` **negative**;
* LSD + RANSAC 3-VP on REF_FRONT → three inconsistent focals (10120 / 19168 / 21441 px), because
  the image is a Photoshop crop so the principal point is not the image centre;
* vanishing point from the car's own lateral lines → pairwise VPs spanning −8 830 to −50 812 px.

The measurable consequence: the REF_PRESS homography's implied local scale runs the **wrong way**
across the image (falling 8% toward the *far* side). So anything more than ~300 mm from the plate
is reported UNRELIABLE, not estimated. Both references put the headlamp outer tip *beyond the car's
own half-width*; that is reported as a failure, not smoothed over.

## What does survive, and why it is trustworthy

Two techniques that need no camera model:

1. **Cross-validation between references whose cameras are on OPPOSITE sides.** REF_FRONT is a
   front-LEFT three-quarter, REF_PRESS a front-RIGHT three-quarter, so depth parallax pushes their
   errors in opposite directions. Their vertical stack agrees to 1.5–5 mm; that agreement is
   evidence, not a shared bias.
2. **The symmetric-pair midpoint.** For a left/right pair at equal depth, the midpoint of the two
   rectified positions in ONE image *is* that image's parallax offset at that depth, so half the
   separation is parallax-free. This is what makes the headlamp inner-corner half-span usable
   (448.0 mm from REF_FRONT, 465.4 mm from REF_PRESS) when the absolute positions are not.

Also: horizontal extents rectify cleanly, vertical extents of a **raked** surface do not. The VW
badge measures 151.1 / 146.9 mm horizontally across the two references (2.8% apart) and
123.7 / 138.0 mm vertically (12% apart). Use the horizontal extent for a circular badge's diameter.

## Files

| file | job |
|---|---|
| `edgefit.py` | sub-pixel straight-edge tracer (steepest-gradient definition, IRLS line fit), used for the plate corners |
| `trace_edges.py` | sub-pixel boundary tracer by 50%-of-step crossing; returns `None` on a weak step so contaminated columns drop out instead of returning a wrong answer |
| `homog.py` | plate-plane homography, plus the focal/pose recovery that **failed** — kept with its failure recorded so it is not rebuilt |
| `measure.py` | loads both references, builds both homographies, `rect()` maps pixels → plate-plane mm |
| `scan.py` | quick per-column / per-row edge scans used to seed the tracers |
| `crop.py` | gridded zoom crops (grid labels are ORIGINAL pixel coordinates) — the workhorse for reading landmarks by eye |
| `final_calc.py` | rectifies every traced curve and picked point, re-datums to the bonnet leading edge, writes `raw_measures.json` |
| `write_spec.py` | writes `LANDMARK_SPEC.json` |
| `overlay.py` | writes `LANDMARK_OVERLAY.png` |
| `platefit.py`, `vps.py` | superseded / failed approaches, kept as evidence |

`measure.py` and `overlay.py` read the references from the session scratchpad
(`gates/g3v6/ref/`) and the `*.npy` traces from the working directory; point them at a new `ref/`
to run on another car.

## Calibration status

Every constant here was calibrated on ONE car from TWO photographs. Budget the first run on a new
vehicle as calibration, not production — and re-run the pre-registered plate-character validation
before trusting a single output number.
