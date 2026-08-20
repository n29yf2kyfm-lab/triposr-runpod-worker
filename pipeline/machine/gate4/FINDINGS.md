# GATE 4 — REAR REBUILD: running checkpoint

## HARD CORRECTION vs the brief (verified twice, independently)
**The tail is at +X on this file; the nose is at -X.** The brief and
`pipeline/machine/rear_lamps4.py` / `rear_kit.py` all assume nose-at-+X and
build the rear at XMIN. Running them unmodified here puts tail lamps on the
bonnet.
Evidence 1 (render): `base/base_shaded_az270.png` (camera at glTF -X) shows
grille, headlamps, wipers, front plate, mirrors. `base/base_shaded_az090.png`
shows a tailgate, rear screen, tail-lamp smears, roof antenna.
Evidence 2 (geometry): `glass` reaches x=+2.035, only 105mm from the +X end —
impossible for a windscreen, correct for a hatch rear screen. Windscreen base
sits at x=-1.178, 964mm from the -X end. Correct.
Evidence 3: `canon_dims.py`'s own nose rule scores high_x=1.0312 vs
low_x=0.5174, i.e. it BELIEVES the windscreen is at high x. **That is wrong on
this car.** It does not flip (needs lo>1.3*hi) so it silently leaves a
nose-at--X car in the frame every downstream stage assumes is nose-at-+X.

## AZIMUTH MAPPING for THIS file (camera formula read from rear_diag2.py)
az 090 = STRAIGHT REAR. az 035 / az 125 = the two REAR 3/4s.
az 270 = straight front. az 215 = a FRONT 3/4 on this file, NOT a rear 3/4.

## Measured baseline
- frame L=4.2825 H=1.4554 halfW=0.8786, tail x=+2.140, grounded, z-centred
- rear-face width at lamp height (y .78-.94) = **1.4487 m**
- **No tail-lamp label exists.** `Lamp_Lens` (270 f) is entirely at the NOSE;
  0 of 46,170 rear-visible z-buffer cells are Lamp_Lens. Tail lamps are dark
  TEXELS in carpaint's 4096^2 bake -> painted-on, not components.
- lamp landmark from the bake: lum<45 in the tail zone = 1,414 faces, 0.117 m2,
  y 0.788..0.922 (0.541..0.633 H)
- baseline painted band (measured in pixels of the straight rear render):
  coverage 63.8% of silhouette, centre gap 36.2%
- rear-view z-buffer composition: carpaint 60.9%, **interior 26.1%**, glass
  12.6% -> Gate 5's "names do not delimit the body" confirmed on my zone
- +z half-width in the lamp band is 0.65-0.70; -z reaches 0.83-0.89. The car is
  ASYMMETRIC -> build one side, mirror (rear_lamps4's rule).

## WITHDRAWN mid-run (recorded per the method rule)
1. Voxel flood-fill exterior test: UNSOUND here. 99.2% of free space is one
   component (the melt shell is not closed), so it cannot separate inside from
   outside. Reported 61 m2 of "exterior" on a car with ~20 m2. Discarded.
2. First lamp-landmark threshold (p22 luminance = 68.3) selected RED PAINT, not
   lamps — the body texels sit at lum~68. Corrected to lum<45.
3. "The outer lens only reaches |z|=0.694 against a 0.849 corner" — WRONG. The
   0.849 figure mixed both sides over the whole rear zone. The +z corner in the
   lamp band is 0.666-0.698; the lens reaches it correctly.

## Built so far
- `g4_lamps.py` -> lamps.npz: 4 lens solids + 4 housings, ALL WATERTIGHT.
  ro 1316f 772cm3, rh 644f 392cm3, lo/lh mirrored. Shut gap 15mm.
  Lens proud of the body by +10..+25mm (verified against an independently
  measured surface profile — this check caught a bad p95 estimator).
- `g4_assemble.py` -> rear_v1.glb (65.3MB), 20 named meshes, NORMAL verified
  on every primitive. No body vertex moved (face re-grouping only).
