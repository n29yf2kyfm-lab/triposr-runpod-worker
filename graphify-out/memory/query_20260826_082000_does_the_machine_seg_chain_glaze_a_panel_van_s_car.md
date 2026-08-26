# Does the machine seg chain glaze a panel van's cargo box?

**Date:** 2026-08-26
**Answer: YES — measured on the TRELLIS.2 Transit Custom control, and it is a
LABELLING error, not source geometry.**

## The measurement

`pipeline/machine/glass_where.py` on `staging/van_slice/van_machine.glb`
(nose established from the `Lamp_Lens` centroid at length-frac 0.941, so the
orientation is not derived from the glazing under test):

    front third 35.88%   mid 40.56%   REAR THIRD 23.57%

23.6% of the glazing AREA sits in the rear third of a **panel van**, which has
no windows there at all.

## It is the labels, not the mesh

The RAW TRELLIS output rendered through the OPTIX worker shows a correct panel
van — **solid white cargo flanks**, glazing only in the cabin. The machine chain
is label-only and preserves geometry, so the glass was invented downstream.

The chain log locates it at the **2D mask stage**, not in projection or
boundary: GroundingDINO returned **4 "car window" boxes and ~47k glass px per
view** on a van whose only glazing is the cabin, and
`glass as % of EXTERIOR(seen) faces: 22.08`. A van's flat cargo flank with a
character line reads as a window to DINO.

## Why nothing caught it

All three existing glazing instruments PASS this van:

| instrument | asks | verdict on the van |
|---|---|---|
| `glass_probe` | is the glazing MATERIAL transparent? | clear (BLEND alpha 0.353) |
| band gate | how much AREA? | PASS at 12.5% (band 1.0–13.0%) |
| `glass_topo` | is each pane one clean piece? | panes intact |

**Material, area and integrity are each necessary and none asks WHERE.**
That is the fourth question, and `glass_where.py` now asks it.

## Trap paid for building the tool

The nose-first decile reversal was inverted, so a **27.4% WINDSCREEN decile
printed as "rear third" — and the flag still fired**. A real-car pass/fail could
never have caught it; only checking the biggest decile against the expected
windscreen did. Fenced by `_selftest()`, 5/5, which pins the decile ORDER at
both nose directions plus the ambiguous-lamps refusal.

## RESOLVED SAME DAY: it is NOT a general van bug

Measured on the Pixal3D 1536 van through the **same seg chain**: the glass mask
covers **only the cabin side window and windscreen**. The cargo flank is not
glazed. `view_00` glass **17,668 px on Pixal against 47,674 px on TRELLIS**, and
3 DINO boxes against 4.

So the defect tracks the INPUT MESH's surface quality, not the body style:

* the TRELLIS cargo flank is a soft, bright, featureless slab — DINO reads it as
  a window;
* the Pixal cargo flank carries visible panel structure and character lines —
  DINO reads it as bodywork.

**Correction to the framing above:** the earlier expectation that Pixal would
show the same thing was wrong, and it was worth measuring rather than assuming.
The general lesson survives — a 2D window prompt can swallow a flat painted
panel — but the trigger is a featureless surface, not a van.

This also means `SEG_PAINT_REJECT` is not needed for the Pixal route and should
stay off; it would additionally be operating near its fail-open floor on the red
van, whose body luminance is low.
