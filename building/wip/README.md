# Work in progress — not wired in, not shipped

Nothing is parked here at the moment.

## What this directory is for

A module whose job is to refuse unless it is certain must not ship
unverified. `handler.py` maps each mode to a module of the same name, so
simply creating `building/<mode>.py` makes that mode LIVE. Parking a module
here with a `.wip` extension keeps `_pipeline_available()` returning False,
so the mode reports `not_implemented` honestly instead of answering badly.

## register.py — parked, then fixed and unparked

Registration sat here because end-to-end alignment left a ~13mm median
residual and an inlier ratio of 0.26 against a 0.35 floor, so `verify()`
correctly refused its own output on a synthetic room it ought to have
aligned perfectly.

**The diagnosis written in this file at the time was wrong on every point.**
It read *"the yaw is right; the translation or the correspondence set is
not"* and prescribed point-to-plane ICP as the next step. The yaw was not
right — it had the wrong sign. Point-to-plane ICP would have fixed neither
fault. And the entry blaming the fixture — *"a regular lattice is an
unrealistic worst case… nothing finds a neighbour"* — was wrong too:
applying the exact inverse transform to that same fixture scores an inlier
ratio of 1.0 at 0.0mm RMSE, so a perfect answer was always available and the
algorithm simply was not finding it.

Three real faults, all found by instrumenting the code rather than reading
it:

1. **The source was thinned with an even stride.** A scanner sweeping a room
   writes wall points in interleaved pairs — `(i, 0)` then `(i, depth)` — so
   an even stride keeps one member of every pair forever and **deleted two
   of the four walls**:

       full   {x=0: 2758, x=5: 2758, y=0: 3518, y=4: 3276}
       [::6]  {x=0:  896, x=5:   24, y=0: 1132, y=4:    0}

   Half a room has a different centroid from a whole one — 0.72m different,
   five times the widest polish radius — so the centroid start landed
   somewhere ICP could never walk back from. The comment two lines below the
   call had always warned about this exact hazard, and applied the lesson
   only to the target.

2. **The global yaw estimate had its sign inverted.** It computed
   `principal_yaw(target) - principal_yaw(source)` for a transform that maps
   source onto target, so the true yaw was never in the four-quarter
   candidate set. The Manhattan prior itself was sound — it was reported as
   recovering 12° as 11.97°, which was the right magnitude and the wrong
   sign, and the sign is what nobody checked.

3. **The centroid was computed from the thinned subset.** Sampling noise on
   3000 of 18000 points offsets it by roughly 14mm, and the
   accept-only-improving rule then held the fit exactly there. Both the
   centroid and the principal yaw are single O(n) passes over the cloud, so
   there was never anything to save by taking them from a subset.

Two tests helped it stay broken. *"A cloud aligns to itself"* asserted RMSE
alone and never the inlier ratio — and RMSE is measured over the points that
FOUND a match, so a source thinned to two walls scored a tidy RMSE on those
two walls while saying nothing about the two that were missing. And the yaw
assertion compared against a value reported in `[0, 360)`, so a correct −12°
came back as 348 and read as a failure.

After the fixes, across yaw 0°, +3°, −8°, +12°, +33° and −45° with
translations up to 2m: **yaw recovered to 0.000°, RMSE 0.00mm, inlier ratio
1.000, verdict "good"** in every case.

### What was learned along the way, all of it still true

- **Point-to-point ICP slides on flat surfaces**, and a room is mostly flat
  surfaces. Left unchecked it walks away from a good global alignment into a
  worse one that still reduces its own local objective.
- **Converge on the step, not the error.** RMSE plateaus while the transform
  is still sliding.
- **Never thin the target.** Only the source costs time; a denser target
  strictly improves every correspondence.
- **Never thin ANYTHING with a stride.** This is the same lesson as above and
  the module knew it, wrote it down, and then applied it to one cloud out of
  two. A seeded shuffle cannot correlate with write order however the cloud
  was written, and stays reproducible.
- **A bare rectangular room is 180°-symmetric**, so a flipped alignment fits
  it exactly as well as the right one. Real rooms have a chimney breast, a
  bay or a door; a test fixture needs one too or it is genuinely ambiguous.
- **A test that measures error only over the points that matched cannot see
  the points that did not.** Assert the ratio as well, always.
