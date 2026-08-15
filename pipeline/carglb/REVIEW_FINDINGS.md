# carglb code review — findings, 2026-08-15

Independent review of the day's new code. Recorded here so the findings are
not lost between sessions. Nothing in this pipeline ships without owner
sign-off, so these are correctness debts, not live incidents — but several
would produce a WRONG VERDICT, which is the failure class this project
keeps paying for.

Status key: [ ] open · [x] fixed · [~] partially addressed

**2026-08-15 (same day): all 12 confirmed findings fixed and integration-tested; commits c7f84a9, fb497ba, 055286c. The OUT_AXIS sign regression introduced while fixing finding 1 was itself caught by a mirror-check render — the render remains the arbiter. Plausibles remain open except wheel centres.**

## Confirmed — would produce a wrong result

- [x] **1. photo_project bakes the texture MIRRORED.** With length on X, nose
  +X and Y up (right-handed), `right = forward x up = X x Y = +Z`. `group_of`
  labels +Z faces "left" and feeds them `left.png`, so every side photo lands
  on the opposite flank and both end photos are mirrored too. Number plates
  read backwards, badges and fuel flap on the wrong side. Worse, the single
  `nose_positive_x` flag controls TWO degrees of freedom (which end is the
  nose, and handedness), so no value of it is correct for a nose=+X mesh —
  and `carglb.py` never passes the flag at all.
- [x] **2. The glass CLAMP paints over the headlamps.** `CLAMP["front"]=0.53`
  reassigns every front-group face above 53% of car height to flat paint. A
  Golf's lamps span ~0.52-0.62; on an SUV the whole lamp is above it. The
  module exists to supply lamp graphics and erases the top half of them —
  the owner's recorded 2026-08-12 complaint ("the lights got paint over").
- [x] **3. silhouette_iou's end views cannot see a bad front end.** The
  silhouette cache is keyed on the projection plane, so front.png and
  rear.png score against ONE mask, and an ortho projection along length is
  the union of all cross-sections. Measured on a synthetic car with the nose
  collapsed to 0.45x: END IoU 1.0000 (identical), SIDE IoU 0.8849. The gate
  reports 2 real measurements as 4, and its docstring's headline claim is
  false.
- [x] **4. `axes_of` mislabels height/width on tall vehicles.** It calls the
  SMALLER of the two non-length extents "height". Measured on VW-Crafter
  proportions [5.14, 1.99, 1.90] it returns width-as-height. Consequences:
  dim_gate compares height against the width spec and fails a correct van
  twice; silhouette side/end views swap; fit_panes lays the car on its side.
  Three copies of this function share the defect. Disambiguate by gravity /
  wheel position, not by min extent.
- [x] **5. The primary path never runs glass_probe or EXPECTED_MATS.** Only
  the fused-shell fallback and the standalone `gates` subcommand do.
  fit_panes' docstring claims glazing is "clear/proven by construction";
  nothing verifies the written file. The owner's hard-fail rule (opaque
  glazing) is the one gate the main path skips.
- [x] **6. A glazing GATE FAIL is indistinguishable from "not applicable".**
  fit_panes exits 1 for the hollow-cabin refusal, for no-apertures AND for
  an out-of-band glass share; run_local reads any non-zero as "refused" and
  silently reroutes a QUALITY FAILURE into the fused-shell chain. Needs
  distinct exit codes (2 = inapplicable, 1 = fail). It also leaves the
  `.paned.glb` (whose own message says do NOT ship it) on disk.
- [x] **7. The hero variant is ungated but gets a provenance manifest.**
  Gates run on the flat build only; `write_manifest` runs on both. A hash
  that reads as approved for a file that passed zero geometry gates.
- [x] **8. `qc()` swallows every failure.** Blender return codes unchecked,
  output PNGs never verified, `forensics.txt` written regardless, and it
  prints "QC written" unconditionally. Also an IndexError on single-line
  forensics output.
- [x] **9. The fused-shell fallback can never pass dim_gate.** fit_panes
  rescales to real metres; `build_car.build()` takes no length and does not
  scale, so branch B is gated at generator-normalised scale (~130% length
  error) and the message blames the mesh.
- [x] **10. `paint_colour` silently falls back to an END photo.** Only
  front/rear are REQUIRED by the capture gate, so a 2-view capture samples
  "door skin" from the grille/lamp strip and paints the whole car that
  colour — the exact two-tone defect the function was written to prevent.
- [x] **11. Nothing verifies the nose direction.** `orient_catalogue` reads
  no geometry — it stamps a fixed quaternion. `fit_panes.remap` guarantees
  length-on-X but never which END. If a mesh arrives nose-−X the catalogue
  rotation puts the nose at +Z, 180 deg from convention, and every studio
  azimuth is the wrong tile — the failure that module exists to prevent.
  The silhouette gate deliberately mirror-maxes, so it cannot catch it.
- [x] **12. `mat_for`'s default is BODY PAINT.** Any geometry whose names
  match no pattern is written as paint. A rename of `lib_tyre_*` upstream
  ships painted tyres — an owner hard-fail. The default should be
  Arch_Cavity, or a raise.

## Plausible — worth checking before they bite

- [ ] fit_panes assumes the mesh is symmetric about W=0 (`np.abs(C[:,W])`);
  nothing centres it or asserts it. An off-centre source puts panes ~1.5m
  outside the body, and the face-count glass gate would not notice.
- [ ] The `top` aperture path has no dominant-region filter while the rake
  path does, on identical exposure — spurious roof/bonnet glass, and
  possible double-paning of the windscreen (coplanar duplicate glass).
- [ ] The wheels/trims split is inert: both are written with paint and
  differ only in mesh name; wheel_swap reads neither.
- [x] Wheel centres were a quadrant MEAN of the lowest 22% (floor pan and
  sills included), pulling each centre inboard. FIXED 2026-08-15 by
  `_contact_centres` with guards + fail-open.
- [ ] `body` and `wheel` meshes are both written with the FULL shell vertex
  buffer and complementary face subsets — the buffer is serialised twice and
  the wheel mesh's POSITION min/max spans the whole car.
- [ ] `orient_catalogue` refuses a root `matrix` but silently accepts
  `translation`/`scale`; glTF applies T·R·S, so a root translation is not
  rotated and the car spins about the world origin.
- [ ] photo_project reads `scene.geometry[...].vertices` and drops node
  transforms; safe only while wheel_swap bakes them into vertices.
- [ ] A background-removed photo with genuinely transparent glazing has
  alpha~0 over the windows, punching a hole the mesh mask lacks — a
  systematic IoU depression on exactly the GOOD cars. Also `score()` skips
  missing photos silently, so one photo can produce a "PASS".
- [ ] `check_captures(strict=)` only controls printing; warnings are never
  enforced despite the name.
- [ ] The 3x2 atlas has a 1-texel inset against LINEAR_MIPMAP_LINEAR; at
  mip>=1 neighbouring cells bleed. Wants a >=4 texel gutter or mip clamp.

## Cheapest high-value order (reviewer's, endorsed)

1. Measure the nose ONCE in fit_panes, stamp it into the GLB or a sidecar,
   and have photo_project and orient_catalogue read it — closes 1 and 11
   together and correctly sets the flag.
2. Raise/replace `CLAMP["front"]` so it stops eating the lamps (2).
3. Distinct exit codes from fit_panes + call `gates` at the end of
   run_local (5, 6).
4. Disambiguate `axes_of` by gravity/wheel position (4).
