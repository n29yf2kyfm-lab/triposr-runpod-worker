# fit_spec + label_fix on the Pixal van2 — what worked and what did not

**Date:** 2026-08-26 · Owner-directed: source dimensions, fit_spec diagonal-only,
fix roof-glass and tyre-annulus labels. No DONE claim.

## THE DIMENSIONS WERE THE WRONG GENERATION ALL ALONG

Every proportion number earlier in this session compared a **2024 E-Transit
Custom (V710, SECOND generation)** against **FIRST-generation** figures recalled
from memory (L 4973 / W 1986 / H 1925-2000). Sourcing them properly:

| | gen-2 V710 L1 H1 | source |
|---|---|---|
| length | **5,050 mm** | Parkers AND Vansdirect, independently |
| height H1 | **1,966-1,968 mm** | Parkers; Vansdirect 1968 |
| width excl. mirrors | **2,032 mm** | Parkers only — SINGLE-SOURCED, flagged |
| width incl. mirrors | 2,275 mm | Parkers AND Vansdirect |
| wheelbase L1 | 3,100 mm | Parkers; Wikipedia range 3100-3500 consistent |

**Van Reviewer's "current generation" page is actually GEN 1** — its own text
says "launched in 2012", and its 4973/1986 are exactly the numbers I had been
using. A URL saying 2024 is not evidence of the generation; read the page's own
provenance. Written up as `specs/ford_transit_custom_v710_l1h1.json` with the
single-sourced width flagged in the file.

Corrected errors: **L -8.5%, H +9.6%, W +37.5%** (was -7.1 / +11.8 / +40.6
against the wrong car). Direction unchanged: width is the outlier.

## fit_spec WORKED — and has a real bug

Diagonal-only fit succeeded: **5.050 x 1.967 x 2.032, all within 1%, 953,753
faces with order preserved so seg labels stay valid.** The mirror guard PASSED
(mirror band 0.604 vs door line 0.604 — mirrors sit flush on this mesh, as they
did on the Golf).

**BUG: it preserves NORMALS VERBATIM under a NON-UNIFORM scale.** The applied
scale was x5.502 y4.593 z3.663 and the file says "BIN chunk verbatim, geometry
and normals untouched". A non-uniform scale requires the INVERSE TRANSPOSE on
normals (reciprocal scales plus renormalise) — the lesson this repo already
records from the wheel operator. Every shaded normal is therefore tilted.

## label_fix — the tyre half works, the roof half is unresolved

**TYRE ANNULUS: fixed, cleanly.** Lower annulus went `interior` 85.1% ->
**0%**, `Tyre_Rubber` 5.9% -> **91.0%**. The tyres now carry the tyre material
rather than merely rendering dark because interior is dark.

**ROOF GLASS: the criterion matters and my first one was wrong.**
* `up-facing |ny|>0.7` evicts 80.1% of glazing area and **destroys the
  windscreen** — 93.7% of this car's glazing sits in the CABIN third and 73.2%
  of that is up-facing, because a noisy generated screen has near-horizontal
  normals. ox warned that up-facing conflates roof with raked screen; it was
  right and I checked its warning the wrong way round first (I looked for the
  windscreen at the tail end — the same decile-orientation slip the glass_where
  selftest exists to prevent).
* `roof zone yf>0.85` evicts 29.9% and preserves the windscreen. Now the
  DEFAULT; up-facing is opt-in with a warning in `--help`.

## TWO BUGS I INTRODUCED, BOTH CAUGHT BY THE RENDER

1. **Stale TextureVisuals dropped every material binding** and the whole van
   rendered grey. Reassigning `gd.visual` onto a mesh with more vertices leaves
   a uv array shorter than the vertex array and the exporter silently drops the
   binding. **This is a trap already recorded in CLAUDE.md in these words**
   ("evicted roof faces rendered default-white") and I walked into it anyway.
2. **The first fix addressed the wrong half.** The glass node is UNTEXTURED, so
   there were no UVs to carry into the textured carpaint node — the re-run came
   back byte-identical. Fixed by SYNTHESISING UVs by nearest destination vertex.

## THE TORN WINDSCREEN IS NOT label_fix's DOING — isolated by render

`fit_spec` output ALONE, with no label_fix, already shows it. Most likely
reading: the glazing was always **143 components with a median of 2 faces**, and
a 5.5x non-uniform scale opens the gaps between those slivers so the soup
becomes visible. **fit_spec did not break the glass; it revealed how broken the
glass already was.** The normals bug above compounds it.

## Standing lesson

Three renders were needed to find two bugs of my own, and each one was caught by
LOOKING, not by a number — every intermediate passed its own assertions (face
count preserved, NORMAL present on all primitives, dimensions within 1%).
