# What did verifying the reviewers' numbers change?

**Date:** 2026-08-26 · Chained Pixal van2. Both reviewers were pushed to check
whether my claim was **too harsh** as well as too generous. Three of my numbers
were wrong, and two of theirs were.

## MY numbers that were wrong

**1. `holes_beyond_outline: 0` was a CLAMP, not a measurement.**
`glass_topo` computes `max(0, loops - comps)`. With 143 components and 74 loops
that is `max(0, -69)` = 0. I quoted a zero that measured nothing. **Never quote
a clamped statistic as a result.**

**2. "143 fragments averaging ~22 faces" was mean-dragged.** Measured per
component: **median 2 faces, 90% under 20 faces, max 935.** The honest picture is
ONE substantial pane plus ~140 specks of debris, not 143 comparable fragments.
Report the median when a distribution is this skewed.

**3. "51% too wide" was a RATIO with the axis unattributed** — and my own stated
mechanism (a low, head-on shot foreshortening LENGTH) implied the van might be
too SHORT instead. Resolved with an in-mesh absolute ruler, the tyre
(per-corner 0.135-0.1376, very consistent):

        L 4.621 m vs 4.972   -7.1%
        H 2.156 m vs 1.929  +11.8%
        W 2.793 m vs 1.986  +40.6%

**And the attribution is robust to the tyre-size assumption**: rescaling so any
one axis is exactly right still leaves width the outlier (anchor L -> W +51.3%;
anchor H -> W +25.8%; anchor W -> L -33.9%). Only the absolute metres depend on
the 215/65R16 guess. So "too wide" survives, with a much better number.

## THEIR inferences that were wrong

**1. "~69 glass components are closed bubbles."** A reasonable reading of the
inconsistent arithmetic, and false: measured **2 closed, 143 open**. The
loops<components gap comes from the Blender loop-walk merging boundaries that
touch at a vertex, not from sealed shells.

**2. "The textured-rim decision was not applied."** Checked the glTF:
`Rim_Alloy` is `textured=True` with no flat baseColorFactor — **the textured
path WAS used.** The pale grey rims are the studio rig on a pale texture, not
the recorded RIM_FLAT regression.

## THEIR criticism that stands and needs acting on

**The matID was rendered through the LIT OPTIX studio.** Pale magenta under a
glossy clearcoat and a white key desaturates toward grey, so a lit render is not
a label measurement. `pipeline/carglb/bl_label_render.py` exists precisely for
this (flat emission, AA off, 1 Cycles sample) and was adopted after the
PartCrafter bench for that stated reason. **Until the matID is re-rendered
through it, "22-32% of visible bodywork unpainted" stays an unhardened proxy**
(it also has no defence against specular overcount at glancing angles - the
recorded Clio blown-highlight trap). Report the failure qualitatively -
bumpers, grille, sills, arches and part of the rear doors take no paint - and
not as a percentage.

## Standing lesson

Asking a reviewer to check whether a claim is TOO HARSH is as productive as
asking whether it is too generous: it surfaced a clamped zero, a mean-dragged
average and an unattributed ratio in my own reporting. And checking the
reviewer back caught two wrong inferences in theirs. Neither side should be
taken at face value.
