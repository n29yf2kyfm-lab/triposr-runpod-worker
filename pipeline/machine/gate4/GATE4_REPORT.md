# GATE 4 — COMPLETE REAR REBUILD (production brief Phase 6)

**VERDICT: CONDITIONALLY ACCEPTED.**

The seven acceptance criteria are met — six clean, one split — and every one is
backed by a diagnostic render plus a number. Four real tail-lamp components now
exist where the source had only dark texels painted on the body; they wrap the
corners, hold their own colour through a body respray, and the rear is split
into named, structurally separate components with no body vertex moved.

It is **not PRODUCTION-READY**, and the reason is not the lamps. Three things
sit outside what Gate 4 can reach, and all three need reconstruction rather than
local repair:

1. **The rear half of this car is sheared sideways by up to 150 mm.**
2. **The hatch and bumper SURFACES were not rebuilt** — they are the original
   generator melt, re-grouped into named components.
3. **The vehicle identity is unresolved** (see §6).

Delivered file: `car-meshes/staging/gate4_rear/glb/rear_v3.glb.part_*`
(3 parts + `MANIFEST_rear_v3.glb.txt`; 65.3 MB reassembled).

---

## 0. TWO CORRECTIONS THE OWNER SHOULD SEE FIRST

### 0a. THE TAIL OF THIS CAR IS AT +X, NOT −X

My brief stated "canon frame is length-on-X, y-up, z-centred, grounded, **NOSE
AT +X** — so the tail is at −X". **That is wrong for this file**, and it matters
far beyond Gate 4: `pipeline/machine/rear_lamps4.py` and `rear_kit.py` both build
the rear at `XMIN`. Run unmodified on this car they put tail lamps on the bonnet.

Three independent lines of evidence:

| evidence | result |
|---|---|
| Render at az 270 (camera at glTF −X) | grille, headlamps, wipers, front plate, mirrors — the FRONT |
| Render at az 090 (camera at glTF +X) | tailgate, rear screen, tail-lamp smears, roof antenna — the REAR |
| Geometry | `glass` reaches x=+2.035, **105 mm** from the +X end (impossible for a windscreen, correct for a hatch backlight). The windscreen base sits at x=−1.178, 964 mm from the −X end. |

**`canon_dims.py`'s own nose rule gets this car wrong.** Run verbatim on this
mesh it scores `high_x = 1.0312` vs `low_x = 0.5174` — i.e. it believes the
windscreen is the high-x cluster. Because it only flips when `lo > 1.3 × hi`, it
does not flip and does not warn; it simply leaves a nose-at-−X car sitting in the
frame every downstream stage assumes is nose-at-+X. That is exactly the silent
failure its own docstring says it exists to prevent. **Recommend a hard refusal
in canon_dims when the two scores are within a factor of ~2, instead of
silently proceeding.**

### 0b. AZIMUTH MAPPING FOR THIS FILE

Because the car is reversed, the azimuths in my brief do not point where it says:

| azimuth | this file |
|---|---|
| **az 090** | **straight rear** |
| **az 035 / az 125** | **the two rear 3/4s** |
| az 270 | straight front |
| az 215 | a **FRONT** 3/4 — *not* a rear 3/4 |

All Gate 4 diagnostics are rendered at az 090 / 035 / 125 and are labelled on
the sheet so nobody re-derives this. The camera convention itself was read out
of `rear_diag2.py`'s camera formula, not assumed.

---

## 1. CRITERIA TABLE

| # | criterion | verdict | measurement |
|---|---|---|---|
| 1 | Four separate closed lamp solids (L/R outer, L/R hatch), each with lens thickness and a housing behind | **PASS** | 4 lenses + 4 housings, **all 8 watertight in the shipped file**. Faces/volume: LO 1316f/1041 cm³, RO 1316f/776 cm³, LH 644f/392 cm³, RH 644f/392 cm³. Mean lens thickness **13.8–15.8 mm**. All four lens units pairwise bbox-disjoint. |
| 2 | Lamps wrap the corner, correct in BOTH straight rear and rear 3/4 | **PASS** | RO spans x 1.601→1.970, reaching **539 mm forward of the tail**, with **75%** of its vertices >250 mm forward (i.e. on the quarter panel). LO 534 mm / **57%**. Visible lamp area: az035 **2.06%** of the car silhouette, az125 **3.17%**. |
| 3 | Hatch, bumper and lamps structurally separate named components; no crack or hole in the body | **PASS** | **22 named meshes** (was 6). Max distance from any post-split paint vertex to a source `carpaint` vertex = **0.000 micron** — the split is a face RE-GROUPING, so a crack is impossible by construction. |
| 4 | Rear lamp band is the correct WIDTH, ratio stated | **PASS on width / FAIL on left-right symmetry** | Total lens coverage **0.641** of the car's own rear-face width (1.4487 m), centre gap **0.370**. The source's painted band measures **0.638 / 0.362** by the identical method — so the rebuilt band matches the manufacturer's own landmark and is **not too wide**. **But R = 0.266 and L = 0.375: the two lamps differ by 41%.** See §2. |
| 5 | Rear screen reads as real glass (probe on the FILE + production-style tile) | **PASS** | `Rear_Glass` is its own node, 11,019 faces, own material, `alphaMode BLEND`, baseColorFactor alpha **0.353** (factor transparency, no name trick needed). `pipeline/ingest/glass_probe.py` run verbatim on the file: **verdict clear / certainty proven**, `flat_shell` False, `alpha_shell` False. Production-style tile (transmission forced onto glass-named materials exactly as `render/handler.py` does) shows the screen as dark transmissive glass with the cabin behind it. |
| 6 | Lamps hold their own colour through a body respray | **PASS** | Name-targeted respray of the material `carpaint` → blue. Lens mean RGB **[158.2, 64.4, 69.2] (red body) → [156.4, 65.3, 72.7] (blue body)** — unmoved, **max channel delta 3.5/255**. Hatch **[207.5, 72.0, 74.0] → [85.5, 112.7, 206.4]** (R−B flips +133.4 → −120.9); bumper [183.7, 68.5, 70.6] → [76.3, 102.7, 191.4]. Both tiles verified unclipped first — see §4.6. |
| 7 | NORMAL accessors on every primitive (read from the WRITTEN file) + `gltf-transform validate` 0 errors | **PASS** | NORMAL present on **22/22** meshes, asserted by re-parsing the exported GLB. `gltf-transform validate rear_v3.glb`: **0 errors, 0 warnings** (HINTs only: `BUFFER_VIEW_TARGET_MISSING`). The source `car.glb` **fails** this — it carries `ACCESSOR_VECTOR3_NON_UNIT` errors on mesh 0. Fixed here: 596 zero-length vertex normals repaired, 23 degenerate faces dropped, UVs and the baked texture preserved. |

Component inventory delivered: `Rear_Hatch`, `Rear_Quarter_L`, `Rear_Quarter_R`,
`Rear_Bumper`, `Rear_Valance`, `Rear_Glass`, `Tail_Lens_LO/RO/LH/RH`,
`Tail_Housing_LO/RO/LH/RH`, `Rear_Plate`, `Rear_Plate_Recess`.
All five paint nodes share **one** `carpaint` material; all four lenses share
**one** `Tail_Lens_Red` material — so a respray paints the whole body and cannot
reach the lamps.

---

## 2. THE BIGGEST FINDING: THE REAR OF THIS CAR IS SHEARED 150 mm

Measured on carpaint+interior face centres, p99 of |z| per x-slice, both sides:

| x (m) | +z half-width | −z half-width | difference |
|---|---|---|---|
| 0.00 (mid-car) | — | — | **+0.030** |
| 0.60 | — | — | **+0.074** |
| 1.20 | — | — | **+0.136** |
| 1.60 | 0.675 | 0.830 | **+0.155** |
| 1.90 (near tail) | 0.570 | 0.681 | **+0.152** |

It holds at **every** height sampled, including y 0.85–0.96 which is above the
tyre top (0.830), so it is not an arch-lip artefact — and the rear-view render
silhouette is asymmetric by ~0.15 m, which agrees independently. **The rear half
of the car is sheared toward −z, growing monotonically from the middle to the
tail.** That is 3.15% of car length; CLAUDE.md records mirror asymmetry on
Hunyuan output as a 0.16%-of-length no-op, so this is **twenty times** that.

**Consequences, all real:**

* `rear_lamps4.py`'s rule "build one side and **MIRROR** it — symmetry by
  construction" **fails on this car**. My v1 followed it and the mirrored lenses
  were buried: **L outer 98% of vertices inside the body (median −104 mm)**,
  L hatch 72% (median −10 mm). Only the R outer was proud. The matID at az090
  showed one orange sliver and one small magenta patch and nothing else.
* The fix is the `wheel_stage` pattern, not a mirror: **ONE design, seated per
  side against that side's own measured surface.** Both sides are built in the
  same mirrored-to-+z parameter space with identical topology (1316/644 faces
  both sides), identical angular span, identical height band (108.0 mm vs
  108.0 mm, delta 0.00 mm) and identical thickness. Only the seating radius
  differs. After the fix: **0% of vertices buried on all four units**, p05
  clearance ≥ +4 mm.
* **The residue is criterion 4's split verdict.** Same inner edge on both sides
  + each lamp reaching its own corner ⇒ the L outer unit is physically longer
  (z-extent 0.321 vs 0.179). There is no way to have all three of (a) lamps
  seated on the surface, (b) identical world-space lamps, (c) both lamps at
  their corners, while the body is 150 mm crooked. I chose (a) + (c) and report
  (b) as broken. **Fixing this properly means de-shearing the body**, which is
  Gate 5 / `canon_dims` territory and requires moving body geometry — which I
  must not do (25,369 carpaint vertices are coincident with interior vertices).

---

## 3. WHAT THE SOURCE ACTUALLY HAD, AND WHERE THE LAMP POSITIONS CAME FROM

**There is no tail-lamp label and no tail-lamp geometry in the source.**
`Lamp_Lens` (270 faces) is entirely at the **nose** — 0 of 46,170 rear-visible
z-buffer cells are `Lamp_Lens`. The matID of the source at az090 is one flat body
colour across the whole tail, while the shaded render shows two dark lamp
smears. **The tail lamps existed only as dark texels in `carpaint`'s 4096²
baked texture** — i.e. painted on, precisely what the brief forbids.

So the landmark had to come from the bake, which is the manufacturer's own
evidence: tail-zone faces with texel luminance < 45 = **1,414 faces, 0.117 m²,
y 0.788–0.922 (0.541–0.633 of car height)**, in two clusters out at |z| 0.5–0.85.
The rebuilt band was then checked back against the painted band in pixels
(0.641 vs 0.638 coverage) so the reconstruction sits where the original design
put it.

Gate 5's warning that **material names do not delimit the body** is confirmed
independently on my zone by a z-buffer from +X: the straight-rear view is
**carpaint 60.9%, `interior` 26.1%, glass 12.6%**. The rear bumper's lower half
and valance are in the material called `interior`; they are now the named
`Rear_Valance` and keep their dark material, which is physically right for an
unpainted lower valance.

**The tailgate cut is measured, not assumed.** The tail surface x_p97 steps back
**44 mm between y 0.54 and y 0.56** (n = 1439 → 595 faces) — that step is the
bumper top shut line. `rear_separate.py`'s default 0.33H would have put the cut
at 0.481, 74 mm below the real seam, and the number plate would have straddled
two components. The tailgate's lateral edge is taken from the lamps themselves
(hatch units end at |z| 0.520, outer units start at 0.535 → edge at the midpoint
0.5275), which is how a real hatchback is built and which comes out symmetric
even though the body is not.

---

## 4. WHAT I WITHDREW OR CORRECTED MID-RUN

Recorded because withdrawing a finding is worth more than defending it.

1. **Voxel flood-fill exterior test — UNSOUND, discarded.** I built an occupancy
   grid and flood-filled from the border to classify exterior faces. 99.2% of
   free space came back as ONE component: this melt shell is not closed, so the
   method cannot separate inside from outside. It reported ~61 m² of "exterior"
   on a car with ~20 m² of skin. Replaced with a z-buffer from the camera
   direction, which answers the question that actually matters.
2. **First lamp landmark threshold selected PAINT, not lamps.** I used the 22nd
   percentile of texel luminance; the red body texels sit at luminance ≈68 and
   the threshold landed at 68.3. The probe's own rival-theory check (is this one
   continuous band or two clusters?) is what exposed it. Corrected to lum < 45,
   which gives a clean single height band and two lateral clusters.
3. **"The outer lens only reaches |z| 0.694 against a 0.849 corner" — WRONG.**
   The 0.849 figure mixed both sides over the whole rear zone and picked up the
   car's widest point near mid-body. The **+z** corner in the lamp band is
   0.666–0.698; the lens was riding it correctly.
4. **"R hatch 76% buried" — a metric artefact, not a defect.** My first clearance
   probe compared radii about a corner pivot, which is the wrong
   parameterisation for an inboard tail-face unit. Measured along +x at matched
   (y,z) the same unit is **0% buried at +28 mm median**. Each unit is now
   measured in the parameterisation it was built in.
6. **My first production tiles were CLIPPED on 42.58% of car pixels** (70.5% of
   the body's red channel), which is the AgX/white-tyre trap: a clipped render
   is not evidence. Re-exposed and re-measured like-for-like — whole-car
   clipping is now **0.82%** (production) and **0.07%** (blue control), the clay
   is **0.00%** clipped at mean luminance 129.8. The criterion-6 numbers in the
   table are the re-exposed ones. The original verdict survived because the
   LENS pixels were only 0.6% clipped either way, but I should have checked
   before writing the first numbers down, not after.
5. A **p95** per-cell surface estimator was pulled short by the melt's dense
   interior points and seated the lens up to 150 mm inside the body. Caught by
   verifying the built lens against an independently measured surface profile
   **before** rendering. Replaced with an outer-extreme estimator plus a
   single-point spike guard.

---

## 5. HONEST DEFECTS IN WHAT I DELIVERED

* **Left and right lamps are different sizes** (z-extent 0.321 vs 0.179). Body
  shear, §2. Visible in the straight rear view.
* **The lenses are lens + housing shells, not modelled lamp units.** Constant
  ~15 mm thickness riding the panel, with a dark housing solid behind. There is
  no reflector, no LED graphic, no internal structure. At 2× the inner tips end
  in a blunt tab where the taper stops.
* **On a red car the red lens is low-contrast** against red paint. It *is* a
  separate component (the blue control proves it numerically) but the straight
  rear view does not read it strongly. On any other body colour it reads cleanly.
* **The plate frame corners are not mitred** — four bars overlapping, which read
  as small dark blocks at the corners.
* **The plate surround's lower half sits against grey melt**, because the
  valance below the bumper is torn source geometry.
* **The rear screen's boundary is ragged** — the matID shows grey body patches
  inside the screen and a body band across its top. That is the source
  segmentation, inherited, not created here.

## 6. NOT REACHABLE BY LOCAL REPAIR — needs reconstruction

This is the distinction the owner is buying, stated plainly.

| defect | why local repair cannot fix it |
|---|---|
| **150 mm rear shear** | A rigid or per-slice correction must MOVE body vertices. 25,369 carpaint vertices are exactly coincident with interior vertices, so moving one geometry alone opens a crack in 25,369 places; the correction has to be applied across the coincident set, which is a canon/`canon_dims` operation, not a rear-zone one. |
| **Hatch and bumper SURFACES** | They are generator melt: soft, wavy, no shut lines. I re-grouped them into named components but did **not** rebuild them, so Phase 6's "replace it with clean reconstructed geometry" is **not** satisfied for the hatch and bumper skins. This is the single largest remaining gap in Gate 4. |
| **Ragged rear-screen boundary** | The glass label is wrong at the edges in the source. Re-labelling is the seg chain's job, not the rear kit's. |
| **Roof spike (antenna artefact) at the tailgate top** | Pre-existing generator artefact, outside the rear component set. |
| **Vehicle identity** | CLAUDE.md records that the "golf" files in `car-meshes` are a **Toyota Yaris XP130** that was canonicalised with `--spec vw_golf_mk8` and thereby stretched ~10% to Golf length (4.282 m against a true 3.89 m). This test bed measures **L = 4.2825 m**, i.e. it carries that stretch. Any proportion judgement on this rear is against the wrong car. I did not attempt to re-identify it and no lamp dimension here should be treated as a spec-correct Golf or Yaris lamp. |

---

## 7. EVIDENCE (all bucket-backed)

Prefix: `car-meshes/staging/gate4_rear/`

| path | what |
|---|---|
| `GATE4_SHEET.jpg` | 8-tile evidence sheet, captioned, with the azimuth correction printed on it |
| `glb/rear_v3.glb.part_00..02` + `glb/MANIFEST_rear_v3.glb.txt` | the delivered car (65.3 MB, reassemble with `cat`) |
| `evidence/base_shaded_az270.png` | proof the nose is at −X (grille + headlamps) |
| `evidence/base_shaded_az090.png`, `evidence/BASE_lampband_2x.png` | the source rear; painted-on lamp texels at 2× |
| `evidence/base_matid_az090.png` | source matID — no lamp material anywhere in the rear |
| `evidence/v3_matid_az090/035/125.png` | material-ID in the owner's colours (L MAGENTA, R ORANGE, hatch CYAN, bumper YELLOW, rear glass DARK BLUE, body grey) |
| `evidence/v3_prod_az090/035/125.png` | production-style tiles, glass transmission forced as the worker does |
| `evidence/v3_blue_az090/035.png` | the respray control |
| `evidence/v3_clay_az090/035.png` | clay pass (surface truth) |
| `measurements/*.json` | every number in this report |
| `tools/*.py` | every stage, also committed to `pipeline/machine/gate4/` on `claude/lovable-connection-ki7jch` |

**Nothing was published and nothing customer-visible was changed.** The source
`car.glb` was copied, never modified in place.

---

## 8. RECOMMENDED NEXT STEPS

1. **Fix `canon_dims`' nose rule to refuse rather than guess** when the two
   glazing scores are within ~2×. This car passes through it silently reversed,
   and every kit stage in `pipeline/machine/` builds off that assumption.
2. **De-shear the rear** as a canon operation across the coincident vertex set.
   Until then no rear component can be left-right symmetric on this car.
3. **Reconstruct the hatch and bumper skins.** That is the remaining half of
   Phase 6 and it is construction, not cleanup.
4. **Re-identify the vehicle before any further spec work** — this mesh is a
   Yaris stretched to Golf length.
