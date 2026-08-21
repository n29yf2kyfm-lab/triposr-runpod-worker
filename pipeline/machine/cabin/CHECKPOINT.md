# CHECKPOINT — Gate: CABIN — COMPLETE

## DELIVERABLE (bucket-backed, round-trip verified)
`car-meshes/staging/cabin/glb/` : car_cabin.glb.part000 (22,020,096 B) +
car_cabin.glb.part001 (2,530,632 B) + MANIFEST.txt
sha256 796c7d47290adbc606343fc40634265bf4f8ec25d1faa1b932b2e288a61b62d6
24,550,728 bytes · 58 nodes · 846,601 faces
`car-meshes/staging/cabin/mobile/` : car_cabin_mobile.glb (Draco, 3,154,588 B)
`car-meshes/staging/cabin/evidence/` and `.../tools/`

## BASE: car_merged.glb (grounded, de-pitched) — SWITCHED mid-run, verified first
All 30 nodes carry identical face arrays; body+glazing+bumpers are ONE rigid
4.730 deg rotation of car_rebound (max residual 0.12 um). Wheel-in-arch test
settled the attitude question: car_rebound hub y 0.504/0.517/0.306/0.318 vs
car_merged 0.316/0.318/0.314/0.312. The BELTLINE mis-reads attitude on this car
because its designed beltline rakes ~4 deg — see HYPOTHESES.md CORRECTION 2.

## RESULTS
visible-interior fraction (8 frozen cameras): 10.75% -> 11.57%
glazed pixels reading as cabin:               69.7%  -> 75.6%
what the glazing shows: `Interior` blocking skin 69.9% -> 8.0%, replaced by
bench back 17.3%, parcel shelf 11.5%, door cards 16.5%, seats, dash, wheel.

aperture fragments (detached, hanging in the glazed cabin): 3,582 px -> 70 px
                                                             (98.0% removed)
attached-to-main-shell slivers: 2,389 px, UNCHANGED — out of scope by design.

holes, 15 directions: LOST outside apertures 222 px of 1,885,171 (0.0118%),
attributable to Body_Shell 5 px; GAINED 85 px (0.0045%). Negative control
(4,000 extra body faces deleted) moves DEEPER 10,713 -> 22,316: TEST FIRES.

glass_probe clear/proven · validator 0 errors 0 warnings · mobile 3.155 MB
(baseline 3.653 MB, -13.6%) · respray: carpaint moves 94.0, glass 11.9,
tyres 2.7, rims 5.6, lamps 3.2-8.8; zero Cabin_* primitives bound to carpaint.

## KNOWN RESIDUALS (measured, not hidden)
1. 2,389 px (1.30% of through-glass pixels) of body slivers still hang in the
   apertures, CONNECTED to the main shell. Component-level deletion cannot
   touch them and control B proves it does not. `pipeline/machine/
   aperture_clean.py` is the existing face-level tool for these; it needs its
   own hole proof before use.
2. The glazing panes are PARTIAL — Glass_Windscreen carries verts only at
   x in [-1.211,-1.132] on the driver's side, so much of the DLO is unglazed.
   That is a glazing-gate issue, not a cabin one, but it is why "outside the
   glazing panes" is not the same as "outside an opening" in every number here.
3. The steering wheel sits 173 mm above the H-point instead of ~300 mm: the
   windscreen plane (y = 0.3424x - 0.0215z + 1.2495, rms 11.9 mm) does not
   allow more without penetrating the screen. Measured constraint, not taste.
