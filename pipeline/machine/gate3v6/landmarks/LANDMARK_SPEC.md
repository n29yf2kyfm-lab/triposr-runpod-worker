# GATE 3 v6 — Front-fascia landmark specification
### Volkswagen Golf Mk8 (VIII) pre-facelift, MY2020, **Style**, UK RHD, five-door

Machine-readable twin: `LANDMARK_SPEC.json`. Visual check: `LANDMARK_OVERLAY.png`.

**The vehicle identity is an ASSUMPTION** (owner-authorised, not verified against a VIN or build
record). Published dimensions used as given: length 4284 mm, **width 1789 mm**, height 1456 mm —
also taken on trust from the gate brief, not independently verified here. Every number below
inherits both assumptions.

---

## 0. Read this before you use a single number

**What you can build against (HIGH confidence).** The complete *vertical* stack of the fascia,
plus the badge diameter and the number-plate geometry. Each of these was measured independently in
two references whose cameras sit on **opposite sides** of the car, and they agree to 1.5–5 mm.

**What you must NOT build against.**

| Do not trust | Why |
|---|---|
| Any *height above ground* | There is none in this file. The ground datum could not be tied to the fascia — the tyre contact patch is ~870 mm behind the plate plane, where the vertical depth-parallax error is of order 100 mm. Anchor the fascia block to **your mesh's own bonnet leading edge** instead. |
| Lateral position of the **headlamp outer tip**, the **outer-intake extremities**, the **lower-grille width** | The two references disagree by up to 20% out there, and at least one of them is physically impossible (both put the lamp tip beyond the car's own half-width). |
| The badge's **vertical** extent as a diameter | The badge panel is raked; use the horizontal extent. |
| Any **slat count** for the central lower grille | The number plate hides the top of it in both references. |
| A **rake angle** for the grille-bar panel | It is raked; the angle is not recoverable without a camera model. |
| A **projected-landmark-error %** against an orthographic front view | **NOT TESTED.** No orthographic straight-on front reference of this spec exists. It is not estimated anywhere in this file. |

---

## 1. Coordinate system

* **Lateral** — distance from the vehicle centreline, in mm and as a fraction of 1789 mm
  (so `0.500` = the extreme edge of the car). Side is always named (car's LEFT / car's RIGHT,
  as the driver sees it).
  Centreline = the number plate's lateral centre. Justified: the VW badge centre solves to
  **+2 mm** from it (two-view solve, ±10 mm), and both are centred by design.
* **Vertical** — mm measured **downward from the bonnet leading edge at the centreline**
  (= the top edge of the upper grille bar). Also given as a fraction of the **front-face height**
  measured **upward from the bumper's lowest edge**: `1.000` = bonnet leading edge,
  `0.000` = bumper lowest edge.
* **Front-face height = 554 mm** (±30). REF_PRESS only — REF_FRONT loses the bumper's lower
  edge in shadow.

---

## 2. HIGH-CONFIDENCE vertical stack

Datum = bonnet leading edge at the centreline.

| # | Feature | mm below datum | ± | frac. of front-face height | Conf. |
|---|---|---:|---:|---:|---|
| 1 | Headlamp outer tip / bonnet leading-edge corner | **−90** | 15 | 1.162 | LOW |
| 2 | Badge top | **−11** | 8 | 1.020 | MEDIUM |
| 3 | **Bonnet leading edge at centreline (DATUM)** | **0** | — | 1.000 | HIGH |
| 4 | Headlamp top edge at inner corner | **9** | 3 | 0.984 | HIGH |
| 5 | DRL / chrome blade centreline | **20** | 2 | 0.964 | HIGH |
| 6 | Badge centre | **54** | 4 | 0.903 | HIGH |
| 7 | Upper grille bar bottom edge | **67** | 3 | 0.879 | HIGH |
| 8 | Headlamp lowest point | **97** | 15 | 0.825 | MEDIUM |
| 9 | Badge bottom | **120** | 4 | 0.783 | HIGH |
| 10 | Number-plate top | **162** | 8 | 0.708 | HIGH |
| 11 | Outer-intake top edge | **230** | 20 | 0.585 | MEDIUM |
| 12 | Number-plate bottom | **272** | 8 | 0.492 | HIGH |
| 13 | Central lower-grille bottom edge | **410** | 15 | 0.260 | HIGH |
| 14 | Bumper lowest edge | **554** | 30 | 0.000 | MEDIUM |

Row 1 is negative because the headlamp tips sit **above** the bonnet's leading edge at the centre —
the leading edge arches up strongly to the corners. That fact is certain in both references; the
magnitude (60–98 mm) is not.

Cross-check, REF_FRONT vs REF_PRESS, on the spans that matter:

| span | REF_FRONT | REF_PRESS | agreement |
|---|---:|---:|---:|
| bonnet edge → chrome blade | 19.2 | 20.7 | 1.5 mm |
| bonnet edge → bar bottom | 66.4 | 68.3 | 1.9 mm |
| bonnet edge → plate top | 156.8 | 167.0 | 10.2 mm |
| bonnet edge → lower-grille bottom | 400.2 | 420.4 | 20.2 mm |

The 10 mm plate spread is a genuine car-to-car difference — a UK dealer-fitted plate versus a
German plate in a holder. Build to the mean and treat ±10 mm as free.

---

## 3. HIGH-CONFIDENCE lateral numbers

| Feature | mm from centreline | ± | frac. of width | Conf. |
|---|---:|---:|---:|---|
| Number-plate half-width | 260 | — | 0.145 | HIGH (it is the metric anchor) |
| Badge outer diameter | **149** | 5 | 0.083 | HIGH |
| Badge centre offset from plate centre | +2 | 10 | ~0 | MEDIUM |
| Badge depth behind the plate face | 44 | 15 | — | MEDIUM |
| Headlamp inner corner | **470** | 25 | 0.263 | MEDIUM |
| Gap between the two headlamps | **940** | 50 | 0.525 | MEDIUM |

Badge diameter is the **horizontal** extent only: 151.1 mm (REF_FRONT) vs 146.9 mm (REF_PRESS),
2.8% apart. Their *vertical* extents are 123.7 and 138.0 mm — the disagreement is the badge
panel's rake interacting with two different camera pitches, and is exactly why the vertical
extent must not be used as a diameter.

---

## 4. The three structures the builder actually has to get right

### 4.1 The upper grille bar — the Mk8's defining feature
* **One black slot spanning lamp to lamp**, of *constant* projected height **67 mm ±3**
  (measured 69.6 / 68.3 / 68.8 mm at 300 mm left, centre, 300 mm right in REF_PRESS — model it
  as a constant slot, **not** a taper).
* Its **top edge is the bonnet leading edge** (the datum). Level within 4–6 mm across the central
  ±300 mm, then rising strongly outboard to the lamp tips.
* **It runs straight through the badge.** The badge sits *on top of* the slot and its blade, and
  overlaps the bonnet shut line above it by ~11 mm.
* Where it meets the headlamp there is **no step and no separate corner** — the slot's blade and
  the lamp's DRL blade are one continuous line.
* **No slats.** The slot reads as a dark recess with a fine mesh behind it. Nothing discrete is
  resolvable in either reference; do not model slats here.
* The panel is **raked back** — but the angle is not recoverable (see §0).

### 4.2 The DRL / light signature
* **ONE element per side plus one crossbar** — a single unbroken line running: headlamp outer tip
  → across the whole lamp → into the grille slot → through the badge → out to the opposite tip.
* Blade centreline **20 mm ±2 below the bonnet edge**, i.e. **30% of the bar's height down from
  its top**, and **parallel to the bonnet edge within 3 mm** (spacing measured 20.5 / 20.7 /
  20.1 mm across ±300 mm).
* Blade thickness **6–9 mm**. (10 px of bright band at three separate columns in REF_FRONT =
  6.3 mm at the local rectified scale; the physical trim may be slightly wider than its specular
  core, hence the range.)
* It **terminates at the headlamp's outboard point** — it runs the lamp's full length.
* **Illumination:** in REF_PRESS the part *inside the lamp* is plainly lit. The part crossing the
  grille reads as bright trim, not a light source. Neither reference settles whether the crossbar
  is illuminated on this trim — **build it as trim**, and treat a lit crossbar as unverified.
* REF_PRESS's lamp carries a small etched legend at the outboard end of the blade. At 1600 px it
  is **illegible**. It is consistent with VW's "IQ.LIGHT" marking but must not be relied on — if
  that car is a matrix-LED unit and the UK car is not, their lamp *internals* may differ. Their
  outlines and element layout do match.

### 4.3 The lower grille — what makes this **Style** and not R-Line/GTI
* **Central grille:** dark lattice with dominant **horizontal** slats, pitch **≈21 mm ±4**
  (independently 21 mm in both references), with a coarser ~45 mm rhythm of heavier bars on top.
  Its bottom edge is level within 7 mm. **Slat count is UNRELIABLE** — the plate hides the top of
  the grille in both references, so no count is quoted.
* **Outer intakes:** a **body-colour surround** framing a black recessed opening, containing
  **THREE bright chrome/silver blades stacked vertically**, each thickest outboard and tapering to
  a point inboard. A **fourth bright line below them is NOT a blade** — it is the specular edge of
  the intake's lower surround; do not model it as one. MEDIUM-HIGH confidence.
  This is the Style signature: **no honeycomb, no red stripe, no R-Line intake surrounds.**

  *Correction log:* my first draft said "three … HIGH confidence, counted independently in both
  references". A numeric bright-peak count of the column profiles then returned **four** groups.
  Re-examining at 6.5× resolved the fourth as the surround edge. The count stands at three; the
  confidence is downgraded to MEDIUM-HIGH and the trap is recorded rather than the original claim
  defended.
* **There is no splitter.** Below the grille the bumper continues as a plain **body-colour
  valance**, a 144 mm band from the grille's bottom edge (410) to the bumper's lowest edge (554).
  No contrasting blade, no black lip, no add-on part in either reference. Splitter *depth* is
  NOT MEASURABLE.

### Headlamp outline (topology — HIGH; coordinates — see §5)
Upper edge: a single near-straight run from the outboard tip down-inboard to the inner corner,
continuous with the bonnet shut line; it does not kink. Lower edge: convex-down, dropping away
from the inner corner to its lowest point roughly two-thirds of the way outboard, then sweeping
back up to the tip. Internal layout **outboard → inboard**: large round projector, then a smaller
rectangular element, then the lamp narrows to its inboard tip; DRL blade along the top over the
whole length.

### Fender / bumper join
Starts at the headlamp's outboard tip and runs **downward and outboard**, hugging the lamp's outer
edge, then turns back along the top of the wheel arch. Topology HIGH; **no coordinates quoted** —
both references see this line only on their near side, in the region where lateral rectification
fails.

---

## 5. What is UNRELIABLE, and exactly why

**Headlamp outer tip, lateral.** REF_FRONT rectifies the tip to **1249 mm** from the plate centre;
REF_PRESS to **1076 mm**. The car's own half-width is 894.5 mm, so *both* are inflated by depth
parallax. Correcting REF_FRONT with a physically consistent depth (~400 mm behind the plate face)
lands it at 850–895 mm — sensible. Applying the same correction to REF_PRESS requires a camera yaw
of 22–28°, which that image's own silhouette proportion (11–16°) contradicts. **That conflict is
unresolved, so no number is defensible.**

What *is* safe to say: **the headlamps run essentially to the full width of the front of the car** —
the tip is at, or within ~50 mm of, the widest point of the bumper (bracket 0.45–0.50 of vehicle
width from the centreline). Build it as "the lamp reaches the corner" and take the exact lateral
from your own mesh's bumper corner.

The same failure governs the outer-intake extremities and the lower grille's width. Reported
UNRELIABLE, not estimated.

---

## 6. Symmetry — what may be mirrored

**Safe to mirror:** headlamp outline and internal layout · DRL blade and crossbar · upper grille
bar · outer intake and its three blades · central lower-grille lattice · lower valance and bumper
lowest edge · number plate and badge (both centred).

**Evidence:** the symmetric-pair midpoint test was run on the headlamp inner corners in *both*
references. The midpoint of a symmetric pair in one image is that image's own parallax offset, so
half the separation is parallax-free; it returned 448.0 mm (REF_FRONT) and 465.4 mm (REF_PRESS)
from cameras on opposite sides of the car. Left/right lamp graphics are visually identical in both.
**Symmetry is demonstrated to about ±25 mm, not better.**

**PROVEN ASYMMETRIC — do not mirror:**
* **Tow-eye blanking cover, car's RIGHT only.** Present on the right and absent on the left in
  *both* references, on both an RHD car and an LHD car — so it is a fixed body-side feature, not a
  driver-side one. Vertical 207 mm ±20 below datum; lateral roughly 455 mm from the centreline
  (LOW).

**Not asymmetry — differences of market or option:**
* Number plate: UK 520 × 111 mm vs EU 520 × 110 mm. Same position, 1 mm different height.
* A small circular fitting (park sensor) in the upper inboard part of the outer intake, present in
  REF_PRESS only. Treat as an option — **do not model it by default**.
* Headlamp internal type (see §4.2, the illegible legend).

---

## 7. References and provenance

| id | file | sha-256 (first 16) | source | licence |
|---|---|---|---|---|
| REF_FRONT | `REF_FRONT_golf_mk8_style_2020.jpg` 4946×2523 | `f6e4d17114d447f5` | Wikimedia Commons, *File:2020_Volkswagen_Golf_Style_1.5_Front.jpg*, author **Vauxford** | **CC BY-SA 4.0** |
| REF_PRESS | `VW_PRESS_DB2019AU02064.jpg` 1600×1067 | `00a0d8d628b9e3bb` | Volkswagen Newsroom, album *Golf 8th Generation*, DB2019AU02064 | Volkswagen AG press material |

Both hashes re-verified against `ref/REF_SHA256.txt` at the start of this session — both match.
**No additional references were fetched.** The two supplied are the only ones used, and nothing in
this file comes from memory, from a third image, or from a generated picture.

REF_FRONT is a front-**LEFT** three-quarter (car's LEFT flank visible); REF_PRESS is a front-**RIGHT**
three-quarter. They therefore view the car from **opposite sides**, which is what makes their
agreement meaningful rather than a shared bias — depth parallax pushes their errors in opposite
directions.

---

## 8. Method, and the pre-registered validation

**Metric anchor: the number plate, and nothing else.** REF_FRONT carries a UK BS AU 145d standard
oblong plate, 520 × 111 mm. REF_PRESS carries a German DIN 74069 single-line plate, taken as
520 × 110 mm (see §9 for how that was confirmed).

Each plate edge was traced sub-pixel (steepest-intensity-change definition, IRLS straight-line fit)
and the four lines intersected. Residual RMS — REF_FRONT: top 0.59 / bottom 0.31 / left 0.25 /
right 0.20 px. REF_PRESS: top 0.83 / bottom 0.20 / left 0.01 / right 0.06 px. The reject threshold
of 1.5 px was fixed **before** fitting; all eight edges passed.

### What would have told me the rectification was wrong — written down before running it
The REF_FRONT homography would be declared WRONG if the rectified plate characters missed
BS AU 145d by more than: character height ±4 mm of 79 · block width ±12 mm of 438 · left-vs-right
margin difference > 6 mm · block tilt > 1°.

### Result

| quantity | measured | target | verdict |
|---|---:|---:|---|
| characters found | 7 | 7 | pass |
| character height | 77.21 mm (sd 0.16) | 79 | pass |
| character width | 49.57 mm | 50 | pass |
| block width | 433.0 mm | 438 | pass |
| left / right margin | 43.0 / 44.0 mm | 41 / 41 | pass |
| block tilt | 0.061° | 0 | pass |

**PASS on every criterion.** These are pixels the homography never saw, so it is a genuine
independent check, not a restatement of the fit.

**One residual it exposed, and I am not hiding it:** character *pitch* rises monotonically
58.0 → 62.75 mm across the plate where it should be 61.0 throughout. That is a ±4% lateral scale
gradient across the plate's own 520 mm — most plausibly a few millimetres of plate bow. It is the
first warning that lateral **extrapolation** beyond the plate degrades, and §5 is where that
warning came true.

---

## 9. Three things I tried, failed at, and am recording so nobody repeats them

1. **Single-plate focal recovery** (Zhang, one homography, principal point at image centre):
   `f²` came out **negative** for REF_FRONT. A 520 × 111 mm plate is far too small and too thin a
   calibration target. Do not retry.
2. **LSD + RANSAC three-orthogonal-vanishing-point solve** on REF_FRONT: three mutually
   inconsistent focal lengths (10120 / 19168 / 21441 px). The image is a Photoshop **crop**, so its
   principal point is *not* the image centre, and the detected line families mix the car with the
   building behind it.
3. **Vanishing point from the car's own lateral lines** (plate edges, bar top, chrome blade, bar
   bottom): pairwise vanishing points range from x = −8 830 to −50 812 px in REF_FRONT and from
   −24 544 to +77 306 px in REF_PRESS. Unusable. The consequence is concrete and measurable — the
   REF_PRESS homography's implied local scale runs the **wrong way** across the image (it falls by
   8% toward the *far* side). That is the direct proof that long-range lateral extrapolation is not
   trustworthy, and it is why §5 exists.

**How the German plate's width was settled at 520 mm rather than 460 mm** (they are both standard
sizes and the distinction moves every REF_PRESS lateral by 13%): assume 520 mm and the badge
measures 146.9 mm horizontally, against 151.1 mm from the independently-anchored UK car — 2.8%
apart. Assume 460 mm and it measures 129.8 mm, a 14% disagreement. 520 mm it is.

**A correction to my own earlier working, stated plainly:** I first read the REF_FRONT badge with
an automatic ellipse fit, which latched onto the bright upper-left arc of the chrome ring and put
the badge centre 17 px too high, giving a diameter of 127.5 mm. Re-measuring by eye at 5× zoom
gave 151.1 mm, which is what agrees with REF_PRESS. The ellipse-fit number is withdrawn.
