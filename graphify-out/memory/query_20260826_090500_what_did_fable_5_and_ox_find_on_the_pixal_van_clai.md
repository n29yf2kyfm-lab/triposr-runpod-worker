# What did Fable 5 and ox find on the Pixal van claim?

**Date:** 2026-08-26 · **Both reviewers: FAIL.** `claim_status: NOT DONE`.
Record: `car-meshes/staging/pixal_van/review_van.json`.

## Three real defects the reviewers found that I had missed

1. **PANE INTEGRITY FAILS — and I had not run the check at all.** Fable 5 named
   `glass_topo` as mandatory after the repo's three documented `glass_probe`
   blind spots. Run afterwards:

       Pixal van   32 components  123 loops  91 holes  -> 3.84 loops/component
       Kia Sportage (ACCEPTED control)  84 / 94 / 14   -> 1.12
       generated Golf (previously called "fragment soup") -> 2.52

   **3.84 is worse than the mesh this project already called perforated soup.**
   Material + area + placement all passed; integrity did not.

2. **THE BADGE IS A BLANK OVAL.** At 4x the Ford oval has the right shape and
   position but **no legible script**. I had written "Ford badge present" from a
   thumbnail — the exact failure the "golf.png is a Yaris" lesson exists to
   prevent. Correct wording: "a Ford-shaped oval in the right place, script not
   legible."

3. **RED RESIDUE SURVIVES THE RESPRAY.** Under the blue control a clear red band
   remains under and around the headlamp: faces carrying a non-carpaint label
   (Lamp_Lens keeps its texture) hold the source body red. **Every colour
   variant of this van would smear red there.**

## The methodological correction that matters most

**The blue control CANNOT prove transparency.** `render/handler.py` forces
`transmission=1.0` onto any material whose NAME matches its glass regex, so
every render including the control manufactured its own glazing. The control
proves only NON-LEAK (no paint on glass or tyres) — which it does prove.

Fixed by renaming `glass` -> `Zx_Pane_Clear` (glTF JSON edit, BIN chunk verified
byte-identical) so the override cannot fire. The glazing still reads as dark
glass rather than body paint, so the transparency is the file's own BLEND
alpha 0.353.

## A probe I built, discarded, and must not rebuild

Delete-the-interior-and-diff-the-pixels: **40.29% of the frame changed, bounding
box spanning the whole image including the exterior panels and the floor.**
Removing the interior changed GLOBAL ILLUMINATION, so it could not isolate a
sightline. Discarded rather than reported — a probe that cannot separate the
rival theory is not evidence.

**What worked instead — render-free and lighting-free**, and it is what ox asked
for: cast rays inward from glass face centroids and see what they hit first.

    97.8% of rays hit something behind the pane
    70.7% terminate on INTERIOR geometry, 29.3% on carpaint (far flank/roof)

## The overclaim both reviewers caught independently

`rear_third = 0.00%` measures **DINO's behaviour on this flank's texture**, not
that the chain handles vans. The SAME chain glazed the TRELLIS van's solid cargo
wall at 23.57% in the same evidence file. One pass and one fail, same subject,
same chain — so the chain is NOT exonerated by the Pixal result.

## Standing lesson

Both reviewers rejected a claim I believed was carefully scoped, and all three
defects were real. The pair earns its cost. Run it BEFORE writing a verdict, not
after.
