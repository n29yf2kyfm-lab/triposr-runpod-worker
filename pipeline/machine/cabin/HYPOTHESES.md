# Written BEFORE building any probe (CLAUDE.md: a probe that can only confirm its author proves nothing)

## H1 — the aperture blotches are small DISCONNECTED Body_Shell components inside the DLO footprint

WOULD BE PROVEN WRONG BY:
* the blotch faces belonging to the MAIN 163,590-face component (then component-level
  deletion is the wrong instrument and would hole the shell);
* a body-only re-render at the SAME camera as `BISECT_window_blotches.png` still showing
  blotches in the aperture after my deletion;
* the deletion changing the car's outer silhouette at any azimuth (= I deleted real skin).

DECISIVE TEST: matched-camera body-only bisection render, before vs after, plus a
multi-angle ray test that counts rays which previously hit body and now hit nothing.

NEGATIVE CONTROL REQUIRED: the fragment selector must be shown to REFUSE to select
(a) the main shell, (b) a deliberately injected legitimate patch placed inside the
aperture footprint but connected to the main shell, (c) the pillars.

## H2 — the interior reads as "torn dark holes" because the Interior node is a bare offset shell

WOULD BE PROVEN WRONG BY: the label pass showing that what reads through the glazing is
NOT the Interior node (e.g. it is background, or the far flank of Body_Shell). In that
case building cabin furniture behind the glass would not change what the viewer sees.

DECISIVE TEST: label render with glass hidden — classify every pixel that lies inside a
glazing footprint by which node it actually shows.

## H3 — cabin furniture placed at measured seat/dash heights will be VISIBLE through the glazing

WOULD BE PROVEN WRONG BY: the after-measurement showing no rise in the cabin-class pixel
share, or the after-render showing the furniture hidden behind the Interior shell.
Note the Interior shell is INBOARD of the glass; furniture must sit inboard of the glass
but OUTBOARD of nothing — if the Interior shell's inner surface is closer to the camera
than the seats, the seats never show. THIS IS THE MOST LIKELY WAY THIS TASK FAILS.

MITIGATION TO TEST FIRST: measure the Interior shell's inner clearance in the cabin band
before choosing seat widths.

## FINDING 1 (2026-08-21) — H3's failure mode is REAL and it is worse than expected

Measured, per x-slice, at window height (y 1.05-1.30):

    x-slice        LEFT glass z(p50)   LEFT Interior z(p50 / p2)
    [+0.20,+0.50]      -0.637              -0.597 / -0.668
    [-0.40,-0.10]      -0.580              -0.525 / -0.586
    [+0.50,+0.80]      -0.627              -0.587 / -0.669

The `Interior` shell is NOT a distant backdrop: it is a skin sitting **40 mm**
inboard of the glazing, and in places OUTBOARD of it. It is the inner offset of
the outer skin and it does not carry the window holes the outer skin has.

CONSEQUENCE: adding furniture in the cabin volume alone would be INVISIBLE —
the inner skin occludes it 40 mm behind the glass. The job therefore needs THREE
operations, not one:
  1. delete the body-shell fragments hanging in the apertures
  2. OPEN the Interior shell across the apertures (deletion — moves nothing)
  3. build cabin furniture in the volume that opening exposes

This also corrects my reading of the brief: the windows are not "torn dark holes
onto nothing", they are "a dark skin pressed against the glass". The VIF
measurement agrees — 58.4% of Glass_Side_L's pixels at az090 already read
`Interior`, so the aperture is not empty, it is BLOCKED.

## CORRECTION — negative control C was wrongly placed, the finder was not (yet) wrong

Control C put a free patch at z=-0.30, i.e. 300 mm inboard of the left glazing
and well BEHIND the Interior skin at z=-0.60. It is genuinely not visible, so
"not selected" was the correct answer and my control was the thing at fault.
Rebuilt: controls are now placed from MEASURED local depths, and the finder's
aperture test is depth-based rather than label-based (the label-based PROTECTED
clause let a fragment in an UNGLAZED opening protect itself, which is a real
bug that the mis-placed control happened to expose).

## CORRECTION 2 (2026-08-21) — I read the pitch off the BELTLINE and that was wrong

The coordinator flagged that car_rebound is pitched nose-UP. My first check used the
BELTLINE slope and appeared to contradict it:

    car_rebound  beltline slope  +0.68 deg (Side_L) / +1.50 deg (Side_R)  -> "level"
    car_merged   beltline slope  +4.77 deg          / +5.36 deg           -> "wedge"

On that evidence I was about to conclude the merged file had tilted a level body.
IT IS THE OTHER WAY ROUND. The beltline is a STYLED line — this car's designed
beltline falls toward the nose by about 4 deg, which cancels the pitch and makes a
pitched car look level. A styled feature cannot measure attitude.

THE TEST THAT WORKS is the wheel in its own arch — on a level car all four hub
centres are at the same height, and the arch moves with the body:

    car_rebound  hub y: FL 0.504  FR 0.517  RL 0.306  RR 0.318   (front 200 mm high)
                 arch top y: 0.930 / 0.942 front vs 0.682 / 0.702 rear (248 mm)
                 predicted from a 4.73 deg pitch over the 2.474 m wheelbase: 203 mm
    car_merged   hub y: 0.316 0.318 0.314 0.312   (equal, +-3 mm)
                 crown gaps 99.5 / 108.3 / 39.2 / 52.7 mm — wheels still in their arches

So the WHOLE car (body and wheels together) is pitched nose-up 4.730 deg in
car_rebound, and car_merged corrects it. I withdraw the beltline reading.

BASE SWITCHED to `car_merged.glb`. Verified before switching, not assumed:
  * sha256 matches the manifest, 28,703,236 bytes, reassembled from 2 parts
  * ALL 30 nodes carry IDENTICAL face arrays -> my face-index masks transfer exactly
  * Body_Shell / Interior / all glazing / bumpers are ONE rigid rotation of 4.730 deg,
    max residual 0.12 um — so the aperture-fragment selection, which depends only on
    internal geometry and face indexing, is invariant under it (re-run anyway to check)
  * it is NOT a single rigid transform of the whole file (global residual max 689 mm) —
    the wheels were re-fitted separately. That is expected, but it means "rigid" must
    be claimed per node, not globally.
