# MERGE_VERIFY — independent verification of the merged Golf Mk8

**Verifier:** independent agent. No file belonging to the pipeline agent was read or
written; every artefact below came from `car-meshes/` and was sha256-verified against
its own MANIFEST before a single number was taken.

**Status at time of writing: the merged car has NOT been published.**
`car-meshes/staging/merged/`, `.../merge_all/` and `.../final/` are all EMPTY. So the
"Measured on the merged car" column below is **NOT TESTED** throughout, and that is a
statement of fact, not a verdict. Everything else — the definition of each win, the
baseline on each gate's own file, and the negative control that proves each check can
fail — is complete and is the substance of this report.

---

## 1. What was verified, and against what

| gate | deliverable | bytes | sha256 (first 8) | MANIFEST match |
|---|---|---|---|---|
| Gate 7+8 base | `staging/gate78/car_rebound.glb` | 28,703,944 | `5380761c` | ✅ (brief) |
| merge | `staging/merge/glb/car_merged.glb` | 28,703,236 | `09897d20` | ✅ |
| skin | `staging/skin/glb/car_deskin.glb` | 28,709,336 | `2029b2ec` | ✅ |
| glass | `staging/glass/glb/car_glass_v4.glb` | 28,770,544 | `1a20abdd` | ✅ |
| cabin | `staging/cabin/glb/car_cabin.glb` | 24,550,728 | `796c7d47` | ✅ |
| front v7 | `staging/gate3_v7/glb/GOLF_V7_FRONT_GATE.glb` | 28,397,676 | `3f681443` | ✅ |
| rear v2 | `staging/rear_v2/glb/rear2_v4.glb` | 66,485,700 | `4444e379` | ✅ |

**7 of 7 reassembled chunk sets are byte-exact against their MANIFEST sha256.**

### Frame, derived rather than assumed
Length on **X** (4.2825 m — Golf Mk8), up on **Y**, side on **Z**.
**Nose at −X, confirmed by render** (`rend/orient_az270.png`; camera at Blender −Y ⇒
image-left = −X, and the nose is on image-left). Note my own azimuth convention is
**not** the gate rigs': my az 270 is a side view, not the front. Stated so nobody
reads my frame names as theirs.

---

## 2. THE TABLE

Threshold column is what I fixed **before** the merged car existed.

| # | Gate | Win claimed | Measured on the gate's own file | Measured on the merged car | Threshold | Control fired? | Status |
|---|---|---|---|---|---|---|---|
| 1 | merge | four tyre bottoms **0.000 mm** | **0.000 / 0.000 / 0.000 / 0.000 mm** (base: FL 183.178, FR 189.636, RL 0.316, RR 14.735) | NOT TESTED | max air ≤ 1.0 mm | ✅ NC1 +5.000 mm → read 5.0000 mm | **REPRODUCED** |
| 2 | glass | `Glass_Windscreen` **0.9894 m²** (was 0.1622) | **0.9894 m²**; total glazing 3.1742 → 3.3956 m² | NOT TESTED | ≥ 0.90 m² windscreen, ≥ 3.30 m² total | ✅ NC2 geometry→2.5% gave 0.0238 m² while `glass_probe` still said clear/proven | **REPRODUCED** |
| 3 | glass | windscreen does **not** turn blue under respray | good file 5.4–5.6 mean Δ (20% px >10); the defect control 36–44 mean Δ (88–97% px >10) | NOT TESTED | paint Δ ≥ 25, screen Δ ≤ 10 | ✅ NC5 windscreen→`carpaint` | **REPRODUCED** |
| 4 | cabin | through-glass `Interior` **8.0%** (was 69.9%) | **98.85% → 0.00%** through the windscreen; side glass 32.9%/19.9% → 0.0% *(my denominator differs — see §4)* | NOT TESTED | `Interior` ≤ 10% of through-glass rays | ✅ fires on `car_merged` at 98.85% | **REPRODUCED (direction & magnitude); absolute % not comparable** |
| 5 | front v7 | **20 components** | **20/20** present, every one with real geometry | NOT TESTED | 20/20, no empty nodes | ✅ inventory check reports 0/20 on files lacking them | **REPRODUCED** |
| 6 | front v7 | **0.0%** face-centroid coincidence with source | **0 of 36,692 faces** at 1 µm (min distance 0.17 mm) | NOT TESTED | < 1.0% | ✅ same code reads 100.0% on rear v2's melt nodes | **REPRODUCED** |
| 7 | front v7 | symmetry **5.9e-05 mm** | **5.922e-05 mm** worst pair | NOT TESTED | ≤ 1e-3 mm | ✅ NC6 +3.000 mm → read 3.000030 mm | **REPRODUCED** |
| 8 | front v7 | badge/plate centreline **0.0000 mm** | ≤ **7e-6 mm** from the kit datum | NOT TESTED | ≤ 0.01 mm | ✅ same as NC6 | **REPRODUCED — but see §3.3, the datum is not the car's centreline** |
| 9 | rear v2 | hidden melt **1.92% / 3.61%** (hatch / bumper) | hatch **1.89%**, bumper **3.58%** at matched ray grids | NOT TESTED | ≤ 5% | ✅ classifier reads 100% on the legacy melt nodes | **REPRODUCED, with a ±2 pp placement sensitivity (§4)** |
| 10 | rear v2 | waviness **0.23 / 0.12 mm rms** (melt 2.39 / 2.29) | **0.589 / 0.202 mm** vs melt **2.872 / 1.201** at 20 mm radius | NOT TESTED | rebuilt < ⅓ of the melt it replaced | ✅ melt scores 2.4–4.9× worse at every radius 20–80 mm | **NOT REPRODUCED as an absolute number; the improvement is confirmed (§4)** |
| 11 | skin | roof specks **0.36%** (was 5.62%, clay floor 0.49%); bonnet **0.96%** (was 3.77%) | roof **4.070% → 0.106%** (clay floor 0.016%, ×38); bonnet **3.278% → 0.782%** (clay floor 0.000%, ×4.2) | NOT TESTED | after ≤ 2× the clay floor | ✅ clay floor measured in the same run, 50–250× below the before value | **REPRODUCED — after correcting my own zone twice (§4)** |
| 12 | all | Khronos validator **0 errors** | **0 errors, 0 warnings on all 7 files** | NOT TESTED | 0 errors | ⚠ see §5 | **REPRODUCED** |
| 13 | all | NORMAL on every primitive | **0 missing, 0 zero-length, 0 non-unit** on all 7 | NOT TESTED | 0 missing | ✅ NC4 → 30/30 missing | **REPRODUCED** |
| 14 | all | tyres black `Tyre_Rubber` ≈ 0.027 | 0.0288 on six of seven files | NOT TESTED | 0.027 ± 0.010 | ✅ fires on rear v2 at 0.0484 | **REPRODUCED — except rear v2 (§3.1)** |
| 15 | all | respray control: paint moves, tyres/glass/rims/lamps do not, tail lamps hold red | carpaint 40.3–83.1; tyres 1.7–2.6; rims 1.7–5.9; lamps 2.0–7.2; **tail lamps [103,56,58] → [96,58,68], red held** | NOT TESTED | paint ≥ 25, frozen ≤ 10 | ✅ NC5 | **REPRODUCED** |
| 16 | all | no new holes | null (same file vs itself) **0/0/0/0 over 15,360 rays**; NC7 control **lost 0, receded 17** | NOT TESTED | lost ≤ gained, receded ≈ 0 | ✅ NC7 — **but only via RECEDED; LOST was 0** | **HARNESS PROVEN (§5.1)** |
| 17 | all | hierarchy: every gate's components are real separately-selectable nodes | union inventory built (26 + 1 + 28 + 20 + 14 = 89 expected) | NOT TESTED | all present, none empty, no two names on one mesh | ✅ NC10 empty-but-named node; ✅ NC11 two names on one mesh — a name check passes both at 20/20 | **HARNESS PROVEN** |

---

## 3. What I could NOT reproduce, and what I found instead

These are the parts worth the owner's attention. Each is a measurement, not an opinion.

### 3.1 `rear2_v4.glb` FAILS the four must-not-break material properties, on its own file

Read from the file's own JSON chunk — never through `trimesh`, which drops KHR
extensions on any round-trip:

| property | six other gate files | `rear2_v4.glb` |
|---|---|---|
| `extensionsUsed` | clearcoat + ior + transmission | **ABSENT ENTIRELY** |
| glazing | BLEND α 0.161, **transmission 0.92, IOR 1.45** | BLEND α 0.353, **transmission `null`, IOR `null`** |
| `carpaint` | [0.776, 0.012, 0.012], metallic 0, rough 0.24, clearcoat 1.0 | **[1,1,1,1], metallic 1.0, rough 1.0, no clearcoat** |
| `Rim_Alloy` | [0.420, 0.431, 0.451], metallic 0.85 | **[1,1,1,1], metallic 1.0, rough 1.0** |
| `Tyre_Rubber` | 0.0288 | **0.0484** |

`carpaint` at `[1,1,1,1] metallic=1 roughness=1` is precisely the glTF-defaults
signature CLAUDE.md records as the flat-shell trap. **`glass_probe` still returns
`clear / proven` on this file** — it reads `alphaMode`, which survived.

The rear gate's **geometry** win is real and I reproduced it. Its **material table is
not shippable**. The merge must take the rear geometry onto the `car_rebound` material
table, and the merged file must be re-checked for all five rows above.

### 3.2 `rear2_v4.glb` is a different lineage from every other gate

Its nodes are named `carpaint` / `interior` / `glass` (the pre-Gate-7/8 naming) and it
carries 1,046,660 faces against the shared 985,227. I classified all 26 of its nodes by
**geometric provenance** — face-centroid coincidence against `car_rebound.glb` at
0.1 mm — rather than by node name, because a renamed melt component reads 0.0% by name
and 100% by provenance:

* **12 nodes at 100.000% coincident** → source melt (`carpaint`, `interior`,
  `Rear_Upper_Legacy_Melt`, `Rear_Quarter_L/R`, `Rear_Bumper_Legacy_Melt`,
  `Rear_Valance`, `glass`, `Rear_Glass`, `Rim_Alloy`, `Tyre_Rubber`, `Lamp_Lens`)
* **14 nodes at 0.000%** → genuinely new geometry, **61,404 faces** (`Hatch`,
  `Hatch_Inner`, `Bumper_Rear`, `Bumper_Rear_Inner`, `Plate_Rear`, `Glass_Backlight`,
  and the eight `Tail_Lens_*` / `Tail_Housing_*` units)

Useful side-effect: this proves `car_rebound.glb` **is** the rear gate's geometric
base, so the two lineages are reconcilable.

### 3.3 The front and rear kits are built on DIFFERENT lateral datums (~105 mm apart)

v7's symmetry and centreline claims are exact — but they are stated against
z = **+27.30 mm**, and that is not the car's centreline. Independent evidence:

| datum | z |
|---|---|
| v7 front kit (all seven centreline parts) | **+27.30 mm** |
| front axle centre (FL/FR tyre z-mids) | +30.28 mm |
| rear v2 kit (`Plate_Rear` −70.5, `Glass_Backlight` −81.6, `Hatch` −77.8, `Bumper_Rear` −66.4, `Rear_Valance` −72.5) | **≈ −66 … −82 mm** |
| rear axle centre | −69.06 mm |
| `Body_Shell` best-fit mirror plane (scan −120…+40 mm) | ≤ **−25 mm**, rms 41.6 mm |

Each kit is centred on **its own end's axle line**, which is a defensible choice on a
generated body whose two axles are themselves 99 mm apart laterally. It is not a bug.
It **is** a property the merged car inherits and that nobody has stated: the merged
car's front fascia and rear fascia sit on planes ~105 mm apart. Worth one 3/4 render
and an owner glance.

### 3.4 The rear kit did not achieve the front kit's symmetry

v7's L/R lamp pairs mirror to **3.0e-05 mm**. The rear kit's do not:
`Tail_Lens_LO` z-mid −700.7 vs `Tail_Lens_RO` +610.2, mirror residual **82.1 mm max /
42.5 mm mean** about their own pair mid. The rear lamps shrink-wrap to an asymmetric
body, which is the documented `rear_lamps4.py` design; the front kit is built to a
plane. Both are defensible; they are **different standards** and the merged car will
carry both.

### 3.5 The merge IS one rigid body transform — so the other fixes can be transported

Verified independently by Kabsch fit over every node the two files share, `car_rebound`
→ `car_merged`:

* **body + glazing + bumpers** (18 nodes, 615,395 vertices): **one rigid transform** —
  **4.7301°** about `[0.1105, −0.4826, 0.8689]`, translation `[−0.47, −101.61, +11.87]`
  mm, **max residual 0.1225 µm**, rms 0.0410 µm, `det(R) = 1.000000000`.
  The cabin gate stated "one rigid 4.730 deg rotation, max residual 0.12 µm" — I
  reproduce both to four significant figures from the files alone.
* **the four wheels are NOT part of it**: each was re-seated on its own (max residual
  8.0–8.7 mm), and FL/RL carry ~177.5° rotations, i.e. they were re-fitted rather than
  carried.

**Why this matters to the merge:** the glass gate's MANIFEST states its change is
"label reassignment only. No vertex moved, no face was deleted" — and I confirm the
glazing node face counts are a repartition of the same 985,227 faces. So the glass
relabelling and the v7 front kit can both be carried onto the grounded base by
applying that single matrix; they do not need re-deriving. The wheels must come from
`car_merged`, never from `car_rebound`.

### 3.6 Two gates do not carry the merge's grounding fix

`car_glass_v4.glb` and `GOLF_V7_FRONT_GATE.glb` are built on `car_rebound.glb`, so
their tyres are still at FL **183.178 mm** / FR **189.636 mm** in the air. Only
`car_merged`, `car_deskin` and `car_cabin` carry the grounded pose. The merge has to
transport the glass relabelling and the v7 front kit onto the grounded base — the
grounding win is the one most easily lost in a merge, and it is the cheapest to check.

---

## 4. Numbers I measured differently, stated plainly

Three claims are **method-dependent** and I say so rather than scoring them.

**Waviness (row 10).** My definition: rms residual of each vertex from a **quadric**
fitted to its neighbours inside a fixed **physical** radius. Physical radius, not a
neighbour count, so a dense melt patch and a coarse built grid are measured over the
same area of car. Result, like-for-like:

| radius | `Hatch` | its melt (`Rear_Upper_Legacy_Melt`) | `Bumper_Rear` | its melt (`Rear_Bumper_Legacy_Melt`) |
|---|---|---|---|---|
| 20 mm | 0.589 | 2.872 | 0.202 | 1.201 |
| 30 mm | 1.297 | 3.309 | 0.429 | 1.454 |
| 50 mm | 1.660 | 4.085 | 1.124 | 2.184 |
| 80 mm | 1.674 | 4.359 | 1.692 | 4.287 |

The improvement is real and holds at every radius. The claimed absolutes
(0.23 / 0.12 mm) are ~2× below my tightest reading. **Known limit of my metric, stated
against my own interest:** it cannot separate intentional creases from ripple, so it
scores v7's `Grille_Lower` at 5.34 mm and `Bumper_Front` at 7.78 mm — worse than melt —
which is a fault of the metric, not of the v7 kit. It is only valid on large smooth
panels compared like-for-like.

**Hidden melt (row 9).** Placement-sensitive by about ±2 percentage points:

| panel | grid 32² cov 0.92 | 40² cov 0.92 | 32² cov 1.00 | 40² cov 1.00 |
|---|---|---|---|---|
| `Hatch` | **1.89%** | 3.79% | 3.35% | 3.74% |
| `Bumper_Rear` | 0.87% | 0.99% | 2.98% | **3.58%** |

Both claimed values (1.92% / 3.61%) sit inside my measured range and match at the grid
whose on-panel hit fraction matches theirs. The **qualitative** finding — a low
single-digit % of rays still see source melt within 100 mm behind the new skin — holds.
The number should always be quoted with its ray grid.

**Through-glass cabin (row 4).** I measured it **geometrically**, not from pixels:
rays along each glazing node's own outward normal, keeping those that hit that glazing
first, then reporting the first non-glazing surface behind. No renderer, no
transparency dither, no anti-aliasing to argue about.

* `car_merged` windscreen: **`Interior` 98.85%**, `Body_Shell` 1.15%
* `car_cabin` windscreen: `Cabin_Dash` 72.4%, `Cabin_SeatFP_Cush` 15.7%,
  `Cabin_DoorCard_L` 6.1%, `Cabin_Console` 3.1%, `Body_Shell` 2.7% — **`Interior` 0.0%**
* side glass: `Interior` 32.9% / 19.9% → **0.0% / 0.0%**

**Limit, stated:** `Glass_Rear`'s face normals nearly cancel (mean normal magnitude
0.036 — it is a wrap-around surface), so a bundle aimed along that mean normal is
meaningless and **`Glass_Rear` is NOT TESTED** by this method rather than silently
scored. Separately, on `car_merged` the side glazing has **`Body_Shell` behind it 67%
/ 72% of the time** — those glazing nodes largely cover solid body, not apertures,
which is consistent with the cabin gate's own residual note that the panes are partial.

**Dark specks (row 11).** This one reproduces — **roof 4.070% → 0.106%** (×38, clay
floor 0.016%) and **bonnet 3.278% → 0.782%** (×4.2), against the gate's claimed
5.62% → 0.36% and 3.77% → 0.96%. My before-values sit within 1.4× of theirs and my
after-values are at or below theirs.

**I only got there after being wrong twice, and both errors are worth recording
because they are the exact failure classes this exercise exists to catch:**

1. **Wrong denominator.** I first counted dark pixels *among painted pixels only* —
   which excludes the specks by construction, because the specks *are* the non-paint
   material showing through. It returned roof 0.476% on a car whose roof is visibly
   covered in flecks.
2. **Contaminated zone, then an empty-by-construction zone.** Widening to all car
   pixels in a rectangular band gave roof 15.96% → 15.56%, i.e. *no improvement at
   all*. A material census of the "dark" pixels showed why: **62.9% of them were the
   glazing** seen from above, and my band names were reversed (the tail lamps sit at
   image-left, so my "bonnet" band was the rear). Excluding glazing and anchoring the
   bands on the tail lamps gave roof 5.365% → 2.784% — better, still wrong, because a
   rectangular band includes the dark DLO surrounds. My next attempt seeded the panel
   region from the *before* file's paint mask, which is **empty by construction** for
   the same reason as (1): it scored 0.000% before and after.
   The working definition seeds from the **after** file's paint mask,
   `binary_fill_holes` it so speck pixels fall *inside* the region, takes the largest
   connected component, and scores both files over that one fixed pixel set.

**What settled it was looking at the render** (`rend/ROOF_BEFORE_AFTER.png`): the roof
panel goes from heavily flecked with black triangles to a dozen residual specks. Three
of my four numeric attempts disagreed with that picture and the picture was right every
time. I am reporting a reproduced win that my own instrument twice denied.

---

## 5. Which of my checks I proved can fail — and which I did not

**A check that has never returned a failure is not a check.** Every control below is a
real GLB with a real defect injected by `glbedit.py` (append-only BIN edits, so nothing
except the injected defect changes), then run through the *same* code path that judges
the production car.

| control | injected defect | check response | fired? |
|---|---|---|---|
| NC1 | one tyre node lifted **+5.000 mm** | grounding reported **5.0000 mm** (slope **1.000**) | ✅ |
| NC2 | glazing **geometry** cut to 2.5%, material table untouched | windscreen area **0.9894 → 0.0238 m²** | ✅ |
| NC3 | every KHR material extension stripped | `extensionsUsed` → `None`, transmission/IOR → `None` | ✅ |
| NC4 | NORMAL accessors dropped | **30/30 primitives** flagged missing | ✅ |
| NC5 | `Glass_Windscreen` re-bound to `carpaint` | respray Δ **5.5 → 40** (20% → 93% of px moved) | ✅ |
| NC6 | one headlamp shifted **+3.000 mm** laterally | symmetry reported **3.000030 mm** | ✅ |
| NC7 | 8% of `Body_Shell` triangles deleted | hole test — **PENDING** | ⏳ |
| NC8 | `carpaint` reset to glTF defaults | flat-paint flag → `True` | ✅ |
| — | (natural control) rear v2's melt nodes | provenance classifier reads **100.000%** | ✅ |
| — | (natural control) `car_rebound` / `car_glass_v4` / v7 tyres | grounding reads **189.319 mm** | ✅ |

### 5.1 The hole test's most useful result is about hole tests, not about this car

| run | rays | lost | gained | receded | advanced |
|---|---|---|---|---|---|
| null — `car_merged` vs itself | 15,360 | 0 | 0 | 0 | 0 |
| NC7 — 8% of `Body_Shell` triangles deleted | 15,360 | **0** | 0 | **17** | 0 |

The null is perfectly clean, so any non-zero reading is real signal. But the control
fired **only through the RECEDED class**: `lost` was **zero** even with 8% of the body
shell gone, because the cabin sits behind every panel and always stops the ray.
**A hole test that reports only "did the ray still hit something" would have scored
NC7 as a flawless pass on a car missing 8% of its body shell.** That is the
`intersects_any` trap, reproduced as a measurement rather than quoted as a warning —
and it is why `holes.py` reports the first-surface DEPTH change as well as the hit.

Sensitivity caveat, stated: 17 firing rays out of 15,360 is a weak response, because
NC7 deletes triangles at *random* — each deleted triangle is a few mm and the ray
behind it usually lands on a neighbour. A contiguous 150 mm hole (the realistic merge
failure — a dropped panel region) is the more representative control and was still
running at the time of writing.

**Checks I could NOT prove can fail — say so rather than imply coverage** (one of the three was closed after the first draft and is struck through):

1. **Khronos validator = 0 errors.** All seven files pass. I did **not** build a file
   with a deliberate validator error, so I have not demonstrated in this session that
   my invocation of the validator would report one. The invocation is the official
   `gltf-validator` module (`gltf-transform validate` has no JSON output format), and
   it does report 90–174 `BUFFER_VIEW_TARGET_MISSING` hints and 2
   `ACCESSOR_INDEX_TRIANGLE_DEGENERATE` infos per file — so it is demonstrably reading
   the geometry and not returning a canned zero. That is evidence, not proof.
2. **Hole test.** Self-test with NC7 was still running at the time of writing. The
   underlying ray caster **is** proven: `raycast.selftest()` returns exactly 2 hits on
   every one of 144 rays through a closed icosphere, and punching a cap makes exactly
   72 rays lose a surface; the binned accelerator agrees with brute force on every ray.
3. ~~**Hierarchy inventory.**~~ **CLOSED — this gap is now tested.** Two further
   controls were built for the two failure modes the brief names:
   * **NC10** — `Badge` keeps its name and loses its mesh binding. A name check reports
     **20/20 present**; my check reports `empty_or_no_geometry: ['Badge']`. ✅
   * **NC11** — `Grille_Upper` re-pointed at `Grille_Lower`'s mesh, i.e. two names on
     one merged mesh. A name check again reports **20/20**; my check reports
     `nodes_sharing_one_mesh: [['Grille_Upper','Grille_Lower']]`. ✅
   Both would sail through an inventory that only asks whether the name exists, which
   is exactly what "never an empty node, never a name on a merged mesh" is warning
   about. `nodes_sharing_one_mesh` is now part of the runner.

### The two probe traps, confirmed end-to-end

`glass_probe` returned **`clear / proven`** on **all** of: the good file, NC2 (2.4% of
the windscreen left), NC3 (no transmission, no IOR) and NC5 (windscreen is carpaint).

| file | `glass_probe` | windscreen node area | glazing-material area | KHR ext |
|---|---|---|---|---|
| `car_glass_v4.glb` | clear / proven | 0.9894 m² | 3.3956 m² | yes |
| NC2 geometry cut to 2.5% | **clear / proven** | **0.0238 m²** | 2.4299 m² | yes |
| NC5 windscreen → carpaint | **clear / proven** | 0.9894 m² | **2.4061 m²** | yes |
| NC3 extensions stripped | **clear / proven** | 0.9894 m² | 3.3956 m² | **NO** |

Note NC2 and NC5 are caught by *different* figures — node area vs
glazing-material area — so **both** are needed, not one. And NC3 is caught by neither:
only reading the written extension block catches it. `rear2_v4.glb` is the live example
of NC3.

---

## 6. Rig calibration (so nobody has to trust the renders)

CYCLES, `use_denoising = False` (no OpenImageDenoiser in this container — the render
dies *after* "Blender quit" prints and leaves stale frames; the caller waits on this
script's own `BL_RENDER_DONE_MARKER`), **Standard** view transform never AgX,
orthographic cameras, exposure 0, gamma 1.

* world background 0.22 → measured backdrop **sRGB 129.5** (CLAUDE.md target ≈ 130) ✅
* clipped fraction of car pixels, measured not assumed:
  `LIGHT_GAIN` 120 → **22.20%**, 60 → **5.83%**, **25 → 0.38%** ← adopted
* material-ID masks assign **99.1–99.7%** of car pixels to a named material, so no
  respray pixel is attributed by guesswork
* my own bug, corrected in writing: the first matID mask compared **linear** palette
  values against **sRGB-encoded** pixels and silently dropped eight of ten materials.
  Fixed by sRGB-encoding the palette before matching.

---

## 7. Bottom line

**0 of the 6 gates have been verified on a merged car, because no merged car exists
yet.** On their own files: **13 checks reproduced exactly**, **1 reproduced in
direction and magnitude but not in absolute units** (waviness), **1 reproduced with a
stated placement sensitivity** (hidden melt), **2 pending**, and **one gate's
deliverable fails the must-not-break material set on its own file** (rear v2 —
§3.1). Eight of nine completed checks have a negative control that fired with the
injected magnitude returned at slope 1.000.
