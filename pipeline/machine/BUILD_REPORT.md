# ONE CAR, SIX GATES — `build_golf.py`

**Deliverable** `car-meshes/staging/final/glb/GOLF_ALL_GATES.glb.part_{000,001}` +
`MANIFEST_GOLF_ALL_GATES.glb.txt`
sha256 `400d994a9fd034cc55d64cf340ec70eedb0d5fa93c188e739da03a787b21084f`,
**25,684,968 B**, 83 nodes · 83 meshes · 107 primitives · **888,807 faces**.
Uploaded chunked, **verified by LISTING the prefix**, and then re-downloaded part
by part, concatenated and re-hashed: identical.

**Mobile** `car-meshes/staging/final/mobile/GOLF_ALL_GATES_mobile.glb` — Draco,
**3,070,968 B** (8.36×), sha256 `b0d0356d…`.

**Answer to the question asked: YES.** One car now carries all six gates, built
by one re-runnable pipeline that REPLAYS each gate's operations onto one base
rather than diffing or stitching six output files.

---

## 1. Each gate's win, MEASURED ON THE MERGED FILE

| gate | the brief's figure | measured on `GOLF_ALL_GATES.glb` | verdict |
|---|---|---|---|
| **merge** | all four tyre bottoms 0.000 mm; body rigid 4.730°, residual 0.12 µm | **FL −0.0000 · FR +0.0000 · RL −0.0000 · RR −0.0000 mm** (world minima of the TYRE nodes). Pose applied as one rigid transform: **4.7301°**, translation **[−0.47, −101.61, +11.87] mm**, det **1.000000000**, orthogonality error 1.1e−16 | **CARRIED** |
| **skin** | roof specks 5.62 → 0.36 %, bonnet 3.77 → 0.96 % | `Interior_Plastic` visible on the car **32,917 → 10,511 px, −68.1 %**; `carpaint` **+23,664 px**; **every frozen material moves exactly 0 px**. Geometry provably untouched: faces 888,807 → 888,807, area **91.748508548 → 91.748508548 m² (Δ = 0.000000000)**, extents identical, **triangle multiset identical** (887,609 unique triangles) | **CARRIED** (different instrument — see §5) |
| **glass** | `Glass_Windscreen` 0.1622 → 0.9894 m² | **0.989443 m²** | **CARRIED, exact** |
| **cabin** | through-glass `Interior` blocking 69.9 → 8.0 % | through-glass pixels are **72.2 % `Cabin_*` parts** (bench back 22.1, front seats 15.1, parcel shelf 7.9, door cards 11.7, headliner 2.7); **`Interior` 5.7 %** | **CARRIED** |
| **front v7** | 20 components, 0.0 % coincidence, symmetry 5.9e−05 mm, badge/plate centreline 0.0000 mm | **20 parts**; face-centroid coincidence with the source **0.0000 %** on all nine sampled parts, with the inherited control `Body_Shell` at **100.0000 % / 0.000 mm**; mirror residual in the feature zone **0.0 mm**; plate centre offset from the fascia centreline **−0.0 mm** | **CARRIED** |
| **rear v2** | hatch/bumper waviness 0.23 / 0.12 mm rms vs melt 2.39 / 2.29; hidden melt 1.92 % / 3.61 % | built waviness **hatch 0.2548 / bumper 0.1433 mm rms**; hidden melt **hatch 1.40 % · bumper 2.01 %** (outer-skin owners only — see §4) | **CARRIED** |

Every constructed component's provenance was re-measured with an INHERITED
CONTROL in the same run, because a column of zeros is otherwise indistinguishable
from a broken test:

```
Grille_Upper  0.0000%   Hatch             0.0000%   Cabin_Dash        0.0000%
Grille_Lower  0.0000%   Hatch_Inner       0.0000%   Cabin_SeatFD_Cush 0.0000%
Headlamp_*    0.0000%   Bumper_Rear       0.0000%   Cabin_Headliner   0.0000%
Badge/Plate   0.0000%   Glass_Backlight   0.0000%   Cabin_Wheel       0.0000%
Valance_Front 0.0000%   Plate_Rear        0.0000%
Body_Shell  100.0000% @ 0.000 mm  <-- INHERITED CONTROL, the test fires
TailLamp_L  100.0000% @ 0.000 mm  <-- INHERITED CONTROL (melt, deliberately spared)
```

---

## 2. THE MUST-NOT-BREAK PANEL, after every stage

Re-run in full after each of the eight stages; a stage that regressed anything
**stopped the pipeline** rather than continuing.

| stage | glazing | projected opening | glass extensions | tyre | validator | normals | respray |
|---|---|---|---|---|---|---|---|
| base | clear/proven | 0.9753 m² (100.0 %) | ior+transmission | 0.02745 | 0 err | 30/30 z0 u0 | cp 129.0 / frozen ≤14.0 |
| glass | clear/proven | 1.1062 (113.4 %) | ior+transmission | 0.02745 | 0 err | 32/32 z0 u0 | cp 128.4 / ≤13.9 |
| front | clear/proven | 1.1062 (113.4 %) | ior+transmission | 0.02745 | 0 err | 49/49 z0 u0 | cp 128.2 / ≤13.9 |
| rear | clear/proven | 1.0678 (109.5 %) | ior+transmission | 0.02745 | 0 err | 55/55 z0 u0 | cp 127.5 / ≤14.3 |
| cabin | clear/proven | 1.0678 (109.5 %) | ior+transmission | 0.02745 | 0 err | 83/83 z0 u0 | cp 127.7 / ≤8.8 |
| skin | clear/proven | 1.0678 (109.5 %) | ior+transmission | 0.02745 | 0 err | 107/107 z0 u0 | cp 127.8 / ≤8.4 |
| pose | clear/proven | 1.0807 (110.8 %) | ior+transmission | 0.02745 | 0 err | 107/107 z0 u0 | cp 129.9 / ≤8.7 |
| **finish** | **clear/proven** | **1.0807 (110.8 %)** | **ior+transmission** | **0.02745** | **0 err** | **107/107 z0 u0** | **cp 129.9 / ≤8.7** |

`cp` = mean sRGB movement of `carpaint` under a red→blue respray at a locked
camera; `frozen` = the worst of `Tyre_Rubber`, `glass`, `Rim_Alloy`,
`Brake_Disc`, `Lamp_Lens`, `Lamp_Lens_Rear`. The paint moves **15×** further
than the worst frozen material on the final car.

Also on the final file: **`nodes_sharing_one_mesh`: NONE** · **nodes with no mesh
binding: NONE** · material table 22 entries · `extensionsUsed`
`[clearcoat, ior, transmission]` · `flat_shell` false · `alpha_shell` false.

---

## 3. EVERY GATE IS PROVEN TO FIRE — ten negative controls

CLAUDE.md records three checks found in one day that could never fire. So each
check here was injected with the defect it exists to catch, and the base was
re-run clean each time.

| control | targets | fired | note |
|---|---|---|---|
| glazing geometry cut to 1/40 | `glass_area` | **yes** | `glass_probe` **still clear/proven** |
| all KHR material extensions stripped | `glass_material_written` | **yes** | `glass_probe` **still clear/proven** |
| windscreen pane rebound to `carpaint` | `glass_regions` | **yes** | `glass_probe` **still clear/proven** |
| `Tyre_Rubber` baseColor → 0.82 | `tyres_black` | **yes** | |
| tyre primitives rebound to `carpaint` | `tyres_black` + `respray` | **yes** | see §5, my prediction was wrong |
| NORMAL accessor removed from one mesh | `normals` | **yes** | |
| accessor `min` corrupted | `validator` | **yes** | invisible in a render |
| a glazing node duplicated in place | **A21** stack | **yes** | 100 % / 100 % at 5.2 mm |
| front kit shoved 40 mm REARWARD | **A22** parts-over-melt | **yes** | base proud share 49.3 % |
| front kit shoved 40 mm FORWARD | **A22** must NOT fire | **correctly passes** | the rule is directional |

**The three glazing controls are the headline.** All three keep `glass_probe` at
`clear / proven` while the car is broken three different ways. That reproduces,
inside this pipeline's own harness, what two agents found independently on
2026-08-21 — and it is why the verdict here is never reported alone.

---

## 4. THE HARD JOIN — decided explicitly

**Rear v2 was built on Gate 4's `rear_v3.glb`, not on the rebound lineage.
I REPLAYED its operations; I did not transplant its components.**

*The measurement that made the replay possible.* `rear_v3.glb` and
`car_rebound.glb` are the same car in the same world frame: identical bbox
minimum (−2.142195, 0.000316, −0.894503), identical height, and a tail profile
(99.7th-percentile x per 50 mm height band at |z| < 0.30) agreeing to **under
2 mm at every height from y 0.225 to y 1.375**. The only two exceptions,
+16.8 mm at y 0.375 and +4.4 mm at y 0.875, are Gate 4's own constructed plate
and lamp solids standing proud of the skin. So rear v2's world-space band
constants transferred unchanged and did not have to be re-derived.

*Why not transplant.* `rear_v3` carries Gate 4's material table with
**`extensionsUsed` absent entirely** — no transmission, no IOR, no clearcoat —
and it has **no per-corner wheel nodes**, only single `Rim_Alloy` /
`Tyre_Rubber` ones, so `merge_op` refuses it outright and the car could never be
grounded. A transplant would have imported a second material table into a car
whose glazing certification depends on the first.

*What I would have seen if this were the wrong call.* The replayed panels would
not have landed: the residual pull onto the measured skin would be large rather
than a low-passed correction, the strip footprint would cut geometry the new
panels do not cover, and rays would pass clean through the tail. Measured
instead: fit residual **3.7 / 5.6 / 4.2 mm rms** on bumper / hatch_low /
hatch_surr, applied residual **6.6–10.3 mm rms** over **99.96–100 % measured
cells**, and the hole test below.

*What had to change, and it was only NAMES.* `fit_panels` reads each panel's
OUTLINE off a separated component; Gate 4 had `Rear_Hatch` and `Rear_Bumper`,
this lineage has the tailgate inside `Body_Shell` and `Bumper_Rear_*` nodes that
run to y 0.903 — 343 mm past the real bumper shut line. The bumper outline still
comes off nodes (`Bumper_Rear_Paint` + `Bumper_Rear_Trim`, which reproduce Gate
4's `Rear_Bumper` lateral extent to **0.0–19 mm, mostly under 6 mm**); the hatch
outline is reconstructed geometrically and **validated against Gate 4's own
separated node — 0.1–15.5 mm through `hatch_low` (median ≈ 4 mm), 3–36 mm over
most of `hatch_surr`**, against a melt component whose own boundary is ragged by
~100 mm. All overrides are env vars whose defaults are the Gate-4 values, so
re-running that gate on `rear_v3.glb` is unchanged behaviour.

*The risk I accepted, and what it cost.* Gate 4's four constructed tail-lamp
solids do not exist on this lineage; the best-named rear-lamp nodes
(`TailLamp_L/R`) are the original melt. They are **spared rather than cut**,
because deleting them would leave the car with no rear lamps at all. Measured
consequence, inside the rebuilt panels' footprint: median clearance **−0.57 mm
(L) / +1.81 mm (R)**, worst interpenetration **−14.7 / −17.7 mm**, i.e. the melt
lamp shells punch through the Class-A tailgate by up to ~18 mm in places. **This
is a real residual and it is the price of the join.** Rear v2's acceptance
criterion 4 (lamps intact through a respray) is Gate 4's win, not rear v2's, and
is **not claimed here**.

*Hidden melt, by owner.* The raw figure behind the rebuilt hatch is 10.67 %, and
splitting it by owner is what makes it meaningful: **5.20 % is the spared melt
tail lamps** (a component, not hidden melt), 4.07 % is `Interior` — the cabin
lining, which is supposed to be behind a tailgate — and the genuine leftover
OUTER SKIN is **1.40 %** (`Body_Shell` 1.00, `Bumper_Rear_Paint` 0.20,
`Glass_Rear` 0.20) against rear v2's 1.92 %. Behind the rebuilt bumper the same
split gives **2.01 %** outer skin against rear v2's 3.61 %.

---

## 5. WHERE I WAS WRONG, corrected in writing

Six things this build proved wrong. Four were my own.

1. **The `cabin/` gate's tools were NOT in git.** The brief states all six gates'
   tools are in git. Cabin's existed only in the bucket
   (`staging/cabin/tools/`). Recovered verbatim into `pipeline/machine/cabin/`
   as the first commit of this session; without that the merge could not have
   been replayed at all.

2. **I put `Glass_` wholesale in the rear replay's KEEP list**, sparing the MELT
   rear screen inside the rebuilt tailgate. The constructed `Glass_Backlight`
   came out **96.8 % within 25 mm of it at a median of 6.0 mm** — two
   transmissive sheets in one place, which is the recorded white-dot defect that
   cost six wrong theories the last time. Gate 4's own file does not keep its
   `Rear_Glass` either. Fixed; A21 now passes.

3. **Surface area is the wrong instrument for "how much window is there".** The
   melt rear screen carries **0.8358 m² of surface over an opening that projects
   to 0.3058 m² — a ratio of 2.73**, i.e. the sheet is crumpled and/or doubled.
   The clean pane replacing it covers **0.2861 m² of the same opening (93.6 %)**
   with 0.3877 m² of surface, ratio 1.35. Judged on surface area that reads as
   losing half the rear window; judged on the opening it is the same window with
   the crumple removed. The glazing gates now measure the **projected opening**.

4. **I predicted the tyre-rebind control would be caught by the respray gate. It
   was not** — a material bound to nothing owns no pixels for a respray to move,
   so the BINDING half of `tyres_black` caught it. Both gates catch it now; the
   respray gate additionally requires `Tyre_Rubber` and `glass` to be PRESENT in
   the render.

5. **I hypothesised the melt tail lamps were cut through because I had excluded
   them from the measured point set. Wrong** — including them moved the burial
   figures 37/38 % → 42/35 %, i.e. nowhere. Recorded because the fix looked
   obvious and was not. Separately, my first lamp-clearance proxy was itself
   wrong: it compared lamp vertices against "the nearest rebuilt-panel vertex"
   when 97.7 % of the supposedly-buried ones lie at |z| > 0.60, on the QUARTERS,
   which this gate does not rebuild.

6. **THE COORDINATOR'S "rear2_v4 is a flat shell" WAS RETRACTED and I record the
   retraction rather than the claim.** That file's `carpaint` and `Rim_Alloy`
   carry base-colour AND metallic-roughness TEXTURES, so their [1,1,1,1] /
   metallic 1 factors are the neutral multiplier and are correct — the exact
   trap CLAUDE.md documents for the tyre probe. What stands is narrower and is
   the reason the replay was right anyway: that lineage has **no KHR extensions
   at all**.

**And one measurement I am NOT publishing.** My first attempt at the skin gate's
pixel speckle figure placed its roof / bonnet / flank regions by hand on a frame
where they did not fall — the clay floor scored a HIGHER dark-pixel rate than the
car, which is impossible. Rather than report a number I could not trust I
replaced it with a threshold-free one: an exact `Interior_Plastic` pixel count
from a material-ID pass at matched cameras (§1). CLAUDE.md's rule applies —
a metric that confidently says "all clear" is worse than no metric.

---

## 6. THE CENTRELINE CONFLICT — resolved, not averaged away

The v7 front kit sits at **z = +27.30 mm** and the rear kit at **z ≈ −70 mm**,
about **97 mm apart**. Measured on the merged car, the body's own midline sweeps
monotonically from **+58 mm at the nose (x −1.65) to −77 mm at the tail
(x +1.95) — 135 mm, and it is bowed.**

| station x | body z-midline |
|---|---|
| −1.95 | +47.5 mm |
| −1.65 | +58.1 |
| −0.75 | +19.9 |
| +0.15 | −17.9 |
| +1.05 | −60.5 |
| +1.95 | −77.0 |

So the front kit sits within ~20–30 mm of its own end's midline and the rear kit
within 2–7 mm of its own. **Decision: each kit stays on its own end's measured
centre.** Three reasons:

1. The criterion that matters for a constructed kit is that it MEETS THE
   SURVIVING BODYWORK at its cut edge. Gate 3 v7's whole design is "each panel
   extends past the cut edge and ramps 10 mm rearward so it passes behind the
   surviving shell"; rear v2's is "the strip footprint is the rebuilt panel's own
   coverage, so the cut can never exceed what gets covered again". Forcing either
   kit onto a shared centreline moves it ~50 mm off its own aperture and turns a
   sealed join into a hole on one side and an overlap on the other.
2. Rear v2 made the same call explicitly and measured it: its plate recess is
   "centred on the bumper's own section centre (z = −0.071), not on z = 0,
   because the tail is sheared — a plate on the car's centreline would sit 71 mm
   off this panel's own middle."
3. The midline sweeps 135 mm monotonically. There is no single centreline that is
   right for both ends, and choosing one would be inventing symmetry the mesh
   does not have.

**The consequence, stated rather than hidden:** viewed from directly above, the
front number plate and the rear number plate are **96.4 mm apart in z**. That is
a property of this body, not of the merge. The alternative — aligned plates on
misaligned apertures — is worse and is measurable at the seams.

---

## 7. A21 / A22 — the cross-gate collisions

No gate could see these: each built against `car_rebound` alone.

**A21 glazing stack — PASS.** No two glazing nodes stacked. The only pairs above
1 % are `Glass_Side_L` / `Glass_Windscreen` (7.36 % / 7.33 %) and
`Glass_Side_R` / `Glass_Windscreen` (4.99 % / 1.16 %) — and both have **median
separations of 468–818 mm**, i.e. they are panes MEETING at the A-pillar. A
stack and an adjacency are not the same thing and a share threshold alone cannot
tell them apart: the injected duplicate scores 100 % / 100 % at a median of
5.2 mm. The rule therefore requires a high share AND a small median.

**A22 superseded base parts — PASS**, on the measurement that answers the
question. "Share of the COMPONENT within 25 mm of the base part" is the wrong
direction and convicts a correct build: v7 deliberately leaves a 12 mm flange of
original bodywork at every cut edge and ramps each panel behind it, so a small
new part beside a large surviving surface scores 90 %+ by construction
(`Valance_Front` 97.66 %). The defect this item exists to catch is base geometry
standing OUTSIDE the component that replaces it, so the verdict is taken on the
share of nearby BASE faces that sit radially further out than the component:

```
                                     base_in_comp   BASE PROUD   median radial
Valance_Front  -> Bumper_Front_Paint     16.94%       37.41%        -0.71 mm
Intake_L       -> Bumper_Front_Paint      2.56%       18.38%        -2.29 mm
Grille_Upper   -> Bumper_Front_Paint      2.21%       26.53%        -1.86 mm
Grille_Lower   -> Bumper_Front_Paint      0.00%        0.00%         --
Intake_L/R     -> Headlamp_L/R            0.00%   base part FULLY REMOVED
Bumper_Rear    -> Bumper_Rear_Paint       2.40%        4.48%        -7.47 mm
Hatch_Inner    -> Bumper_Rear_Paint       1.82%       28.64%       -11.66 mm
Cabin_Floor / Cabin_Headliner        [interior, exempt — a floor is SUPPOSED
                                      to sit inside the floorpan]
```

The strips are real: `Bumper_Front_Paint` **58,448 → 25,064 faces (−57 %)**,
`Headlamp_L/R` and `Bumper_Front_Trim` deleted entirely, `Body_Shell`
190,385 → 177,440. Of the base bumper that survives, only **31 %** lies within
25 mm of the kit at all, at a median of 58.3 mm; where it does, the median
radial offset is **negative** — the base sits INSIDE the new panel, which is the
designed tuck, not parts over melt.

---

## 8. THE PIPELINE

`pipeline/machine/build_golf.py` + `pipeline/machine/buildstages/`. Staged,
resumable, one hard gate after every stage.

```
base → glass → front → rear → cabin → skin → pose → finish → mobile → sheet
```

**Order, and why.** Label-only ops preserve topology exactly, so they compose;
strips move no vertex, which is what makes them safe when 25,369 `carpaint`
vertices are exactly coincident with `interior` ones; pose is last so everything
upstream is built in one consistent frame.

**Two deliberate departures from the brief's proposed order, both measured:**

* **Each gate's strip and add are kept ATOMIC** rather than running all strips
  then all adds. The reason strips come first is that deletion is safe; that
  property is preserved by running gate A's strip+add then gate B's strip+add,
  provided B's strip cannot cut A's parts. Ordering front → rear → cabin
  guarantees that: the rear strip iterates every node, so a cabin parcel shelf
  built first would be cut by it.
* **The skin relabel runs LAST of the label ops, not first.** It writes a SECOND
  PRIMITIVE onto existing meshes, and trimesh then loads those as `Body_Shell`,
  `Body_Shell_1`, `Body_Shell_2`… Measured: every downstream stage reading
  `sc.graph["Body_Shell"]` would silently see **171,314 of 190,385 faces**, and
  `cabin/assemble.py` asserts one primitive per mesh. The relabel is provably
  topology-preserving so it composes anywhere; this is the only place it
  composes safely.

**Resumability.** Each stage writes `work/<stage>.glb` and
`receipts/<stage>.json` recording the input sha, the output sha and bytes, the
full gate panel and the elapsed time. A stage is skipped only when its receipt
records the same INPUT sha and its output still hashes to the recorded value —
so a re-run after a rollback resumes, and a changed upstream stage correctly
invalidates everything after it. `--from`, `--only`, `--to`, `--regate` and
`--selftest` are provided.

---

## 9. RESIDUALS — measured, not hidden

1. **The melt tail lamps interpenetrate the rebuilt tailgate** by up to 14.7 mm
   (L) / 17.7 mm (R), median −0.6 / +1.8 mm, over the 56–64 % of each lamp that
   lies inside the panels' footprint. Gate 4's constructed lamp solids do not
   exist on this lineage. Fixing it properly means porting Gate 4's four lamp
   units onto this material table — a separate job with its own gate.
2. **Residual label speckle on the roof and cant rail.** `Interior_Plastic` on
   the car falls 68 % but does not reach zero; the skin gate's own report records
   the cowl/scuttle as an unresolved connected dark network larger than its
   island threshold, and its rule 1 forbids painting over anything not proved
   wrong.
3. **A roof spike (antenna class)** is present on the base and survives every
   gate. Inherited, not introduced.
4. **The front wing / bumper seam reads as a dark line** at the v7 cut edge in
   the studio renders. That is the deliberate 12 mm flange plus the 10 mm
   rearward ramp seen at this exposure, not an open hole — the hole test finds no
   through-path there.
5. **Front / rear number plates 96.4 mm apart in z** — §6.
6. **`Glass_Rear` survives as a 0.0119 m² remnant** outside the rebuilt
   tailgate's footprint. Below every threshold and not a stack (A21 passes), but
   it is a leftover rather than a designed part.

---

## 10. WHAT IS IN THE BUCKET

```
car-meshes/staging/final/
  glb/     GOLF_ALL_GATES.glb.part_000 (22,000,000 B)
           GOLF_ALL_GATES.glb.part_001 (3,684,968 B)
           MANIFEST_GOLF_ALL_GATES.glb.txt   <- part order, per-part sha256,
                                                whole-file sha256, cat command
  mobile/  GOLF_ALL_GATES_mobile.glb (3,070,968 B, Draco)
  receipts/  one JSON per stage, each carrying its full gate panel
  evidence/  the 8-view sheet, the before/after strip, the clay pass,
             COLLIDE.json (A21/A22), SELFTEST.json, WINS_*.json
```

Reassemble with `cat GOLF_ALL_GATES.glb.part_* > GOLF_ALL_GATES.glb`; the
manifest carries the sha256 to check it against.

Tools: `pipeline/machine/build_golf.py`, `pipeline/machine/buildstages/`
(`glbmeas.py`, `gates.py`, `render.py`, `collide.py`, `rear_replay.py`,
`cabin_rigcfg.py`, `evidence.py`, `wins.py`, `sbchunk.py`) and
`pipeline/machine/cabin/` (recovered), on `claude/lovable-connection-ki7jch`.
