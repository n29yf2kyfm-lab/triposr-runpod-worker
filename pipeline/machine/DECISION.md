# The generation route: kill test first, then repair. Joint plan, 2026-08-25

Written after running a fresh Pixal3D Golf end to end through the machine and
putting the resulting plan to a second model (`stealth/ox-alpha`) for review,
with the renders attached. This file is the merged plan. It exists in the repo
because the container has now rolled back twelve times and anything worth
acting on twice has to survive that.

## The one-line position

**The plan I had written was four workstreams of material surgery on a car that
has already failed on SHAPE, with the shape test scheduled last.** The order is
now inverted: three cheap experiments decide whether the route lives, and the
repair work only happens if it survives them.

## What is actually established

Measured today on the fresh Golf (998,730 faces), not inferred:

| | |
|---|---|
| proportions | +8% too tall, **+33% too wide**, and NO tumblehome (width flat floor to 80% height) |
| exterior seen, 10 downward views | 18.6% of faces — everything else painted flat dark |
| exterior seen, +8 views at elev −6 | 25.2%; body +39%, wheels +59%, glass flat |
| glazing material | `clear / proven`, alpha 0.35 BLEND — passes |
| glazing structure | **124 components, 313 boundary loops, 189 holes** |
| wheels | still read as torn; label is 2.53% of faces, spoke gaps go dark |
| surfacing | soft: no shut lines, blobby lamp recesses, mushy nose and tail |

Established across four generators (TRELLIS.2, PartCrafter, Hunyuan3D-2,
Pixal3D) and every documented lever: **surfacing softness is invariant.** The
one previous car that passed every material gate was rejected by the owner
verbatim: "It fukin look shit."

## The missing quadrant

The trilemma this project has been working inside is:

* fused mesh + decent surfacing, no parts (Hunyuan, Pixal)
* part-native, parts separate, surfacing melts (PartCrafter)
* native 3D part segmentation cannot cut glazing out of a fused shell (P3-SAM,
  settled 2026-08-12 — glazing is a REGION of one surface, not a part)

The quadrant nobody has tried: **structure by construction.** The product starts
from a UK registration, so the vehicle identity is known BEFORE any geometry
exists. Pane layout, wheel geometry, published dimensions and proportion vector
are all knowable a priori for a Mk8. The pipeline currently hallucinates them
and then spends its entire effort scraping them back out of the hallucination.

## STAGE 1 — the kill test (do this before any more repair work)

Three experiments. Any one of them can end the route, and they are cheap.

**1.1 Feature-size audit — hours, analytic, no GPU.**
Measure the mesh's edge/voxel length in millimetres against the feature sizes
the premium bar requires: a shut line is ~4-5 mm, a lamp recess ~30 mm. If the
generator's feature size cannot represent a shut line, no amount of labelling,
smoothing or detail transfer will produce one, and that is an analytic answer
rather than another render to argue about. **This is the cheapest kill test
available and it has never been run.**

**1.2 Positive control — days.**
Put ONE known-good car (licensed, or the best sourced catalogue Golf) through
our own viewer and our own gate stack. We have never done this. Without it,
every threshold in the machine is a guess, we do not know what the bar looks
like inside our own pipeline, and we cannot tell a generator defect from a
viewer or material-stack defect. This also independently validates the material
and viewer stack.

**1.3 One detail-transfer prototype.**
Align a reference model of the KNOWN car to the generated shell and transfer
shut lines, lamp recesses and creases as normal/displacement detail. This is
the only mechanism identified that can put panel gaps into a generated shell,
because no generator on the list will ever carve them. If 1.1 kills it
analytically and 1.3 fails visually, kill the route here.

Almost nothing is wasted either way: the machine's tooling (tyre/rim splits,
glass materials, interior tubs, proportion fitting) is exactly what SOURCED
assets also need. That is its afterlife if generation dies.

## STAGE 2 — repair, only if Stage 1 survives

Order matters; several of these are dependencies, not preferences.

**2.0 `fit_spec` becomes step one of the chain, always with a car spec.**
Not item three of a recovery plan. Masks, priors, pane fitting and wheel
placement all assume real proportions, and the +33% width would otherwise ship
silently. Honest limits: per-axis scaling fixes L/W/H and **cannot fix
tumblehome** (it preserves the greenhouse-to-door width ratio). And ANGLE-based
thresholds must be re-checked after it — normals, the roof rule, dihedral crease
density all move under a 0.75x width squash. Fraction-based thresholds (height
bands, end zones) do not move and do not need re-baselining.

**2.1 Stop treating "unseen" as "interior".** This manufactured the sill and
bumper blotching. A pure volume test is the wrong instrument on a mesh with 189
holes in the glazing alone — ray parity will lie. Use the compound rule:

> skin ⇔ seen in ≥1 view, OR within ε of the visual-hull surface
> interior ⇔ unseen AND ≥δ deep inside the hull (generalised winding number,
> which is hole-robust; not ray counting)

The hull term rescues sills and bumpers no camera sees; the visibility term
rescues concavities (wheel wells, mirror pockets) a naive hull test would bury.

**Before relabelling, DECOMPOSE the 74.8%.** Some of "unseen" is duplicate or
interior marching-cubes shell that should be DELETED, not painted. Nobody has
established the split between shell junk, genuinely occluded surface, and
underbody.

**2.2 Rebuild wheels rather than label them — in parallel with 2.1, and AFTER
2.0.** Generated wheels have never survived an audit. `wheel_swap.py` already
fits library geometry. Two additions: mask wheels out of the generator input so
it stops making them at all; and if the donor ships as a pre-assembled tyre+rim
asset, the fragile radius split dies with the generated wheel. **Dependency: the
swap must come after `fit_spec` or the anisotropic 0.75x width scale gives
elliptical tyres.**

**2.3 Construct glazing panes.** The aperture is the hard part, not the pane —
rasterising a grid inside a loop is trivial; extracting clean aperture loops
from a shell with 313 boundary loops is the actual work. And note the ceiling:
with zero tumblehome the constructed panes will be vertical slabs that read
wrong even when watertight. If identity is known, lifting the known glass
polygons into car space beats rediscovering them from a deformed shell.

**2.4 An interior strategy, which the current plan lacks.** Alpha-0.35 glass
means the customer looks INTO the car. Flat dark matte behind a clean pane is a
clean view of nothing. Needs at minimum a cabin tub plus tint, or the
premium-glass rule just relocates the embarrassment.

## STAGE 3 — gates that should have existed already

* **Identity gate.** "Correct vehicle" is a hard owner rule with NO measurement
  behind it. Render from the input photo's viewpoint, score silhouette IoU. The
  +33% width was found by accident, which means the gate was missing.
* **Proportion vector**, not just L/W/H: tumblehome index, wheelbase/track,
  wheel diameter over body height, overhangs, greenhouse ratio.
* **Pane integrity in the standard stack.** `glass_probe` passes perforated
  glass — three separate blind spots now, same root cause. Pair every probe
  verdict with `glass_topo`.
* **matID render in the standard stack.** A beauty render says "damaged"; the
  material-ID render says WHICH label did it. It is what found the sill defect.
* **Camera contract.** Ten views all at +18/+40 elevation was a self-inflicted
  wound. Audit from the hemisphere the customer actually uses.
* **Edge sharpness**: dihedral-angle histogram against a known-good asset, so
  "soft" becomes a measurement rather than a vibe.
* **Baked-lighting contamination**: the single baked texture on `carpaint`
  carries AO and shadow that fight viewer lighting. This alone can produce
  "looks shit" with perfect materials. Never measured.
* **Poly/draw-call budget**: ~1M faces, and there is NO retopo or LOD stage
  anywhere in the chain (verified by search).
* **Generalisation**: every prior is being tuned on one Golf. An estate's glass
  share is not a coupe's.

## Corrections recorded, so they are not re-litigated

Three claims in the review were checked and do NOT hold:

1. *"glass 3.28% is meaningless, diluted ~4:1 by the interior dump."* The band
   gate is AREA share of the whole mesh (`seg_project.py:211-217`), calibrated
   on ten real catalogue cars which carry their own interiors, so the dilution
   is present in the calibration too. `seg_refine` separately prints the
   exterior-only share (14.06%).
2. *"the 23,000 cabin faces got body labels because projection sees through
   glazing; fix with glass-as-opaque-occluder."* Glass is ALREADY an opaque
   occluder — the Pixal output is a single opaque material, so the depth pass
   records the window surface. That fix is likely a no-op and the real cause is
   still unidentified.
3. *"re-baseline every threshold after fit_spec."* Only the angle-based ones.
   See 2.0.

And one correction against MY OWN reporting: the 23,000-face "cabin leak"
metric did not exclude the ROOF, which is body, inboard, and inside the same
height band. **That figure is an upper bound and may be mostly roof.** Re-measure
with an up-facing-normal exclusion before treating it as a defect at all.
