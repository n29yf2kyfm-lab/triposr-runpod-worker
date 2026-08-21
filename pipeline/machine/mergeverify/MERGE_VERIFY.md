# MERGE_VERIFY — independent verification of the merged Golf Mk8

**Verifier:** independent agent. No file belonging to the pipeline agent was read or
written; every artefact below came from `car-meshes/` and was sha256-verified against
its own MANIFEST before a single number was taken.

**THE MERGED CAR ARRIVED AND HAS BEEN VERIFIED.**
`car-meshes/staging/final/glb/GOLF_ALL_GATES.glb`, 25,684,968 bytes,
sha256 `400d994a9fd034cc55d64cf340ec70eedb0d5fa93c188e739da03a787b21084f` —
**byte-exact against its own MANIFEST.** 83 nodes, 888,807 faces, 107 primitives.
See **§0** for the verdict and **§9** for the two defects found on it.

---

## 0. VERDICT ON THE MERGED CAR — 5 of 6 gates' wins survived intact

| gate | win | on the merged car | status |
|---|---|---|---|
| **merge** | four tyre bottoms 0.000 mm | **0.000 / 0.000 / 0.000 / 0.000 mm** | ✅ **SURVIVED** |
| **skin** | roof/bonnet specks | see §9.3 | ✅ **SURVIVED** |
| **glass** | windscreen 0.9894 m² | **0.9894 m²**, and it does not take paint under respray | ✅ **SURVIVED** |
| **cabin** | `Interior` out of the glazing | 28/28 components, seats/dash visible through the glass | ✅ **SURVIVED** |
| **front v7** | 20 components, 0.0% reuse, symmetry 5.9e-05 mm | **20/20**, **0.0%**, **1.59e-04 mm** about its own fitted plane | ✅ **SURVIVED** |
| **rear v2** | 14 components, waviness, hidden melt | **6 of 14** — the **8 constructed tail-lamp units are ABSENT** | ⚠️ **PARTIAL** |

**Also passing:** Khronos validator **0 errors / 0 warnings** on both the desktop and
the mobile file · NORMAL present, unit-length on **all 107 primitives** ·
`extensionsUsed` carries clearcoat + IOR + transmission · `carpaint` correct
(metallic 0, rough 0.24, clearcoat 1.0) · `Tyre_Rubber` 0.0288 · respray control
**passes on all four cameras** (paint 38.7–85.1; tyres 1.33–2.90, rims 1.70–5.52,
lamps ≤6.4, discs ≤0.84; **tail lamps hold red in all four**) · **A21 collision
RESOLVED** (96.21% → **0.00%**) · **A22 no stacking** · provenance: 54 nodes at
**0.0%** coincidence with the source = genuinely constructed.

**Two defects found, both in §9.** One is a **serving-path divergence** that would ship
a broken car to mobile users.

---

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

### 3.1 CORRECTED — I got this partly WRONG, and the correction matters more than the finding

**What I published earlier in this session and now retract:** that `rear2_v4.glb`'s
`carpaint` and `Rim_Alloy` are *"[1,1,1,1] metallic 1 rough 1 — the glTF-defaults
flat-shell signature"*. **That is wrong.** Both materials carry a `baseColorTexture`
**and** a `metallicRoughnessTexture` — the file holds **4 images / 4 textures**, where
the other six gate files hold **zero**. On a *textured* material a `[1,1,1,1]` factor
with metallic 1 / roughness 1 is the **neutral multiplier**, and is exactly correct.

This is precisely the trap CLAUDE.md already records for the tyre probe — *"the factor
on a textured material is a MULTIPLIER and is [1,1,1] on nearly all of them, so treating
a failed read as opaque white invents a tyre failure"* — reproduced by me, on a
different material, in a report warning about instrument error.

**How it surfaced, because the mechanism is the useful part.** I ran the respray
control on `rear2_v4` to turn a table read into measured behaviour. It returned a mean
delta of **exactly 0.00 across 64,486 pixels**, with base and alt mean colour identical
to the integer. An exact zero over 64k pixels is not physics, so I checked instead of
publishing: the two PNGs were **pixel-identical**, differing only in PNG metadata.

The cause was a **second bug, this one in my own rig**: `set_paint` wrote
`default_value` onto the Principled BSDF's `Base Color` — an input that on a textured
material is **LINKED** to an Image Texture node. Writing a default on a linked input
does nothing. So my respray silently no-opped and would have reported "the paint does
not respond" on **any** textured car. Both bugs are fixed:

* `bl_render.set_paint` now detects a linked input, inserts a MULTIPLY `MixRGB` to tint
  the texture, and **prints what it did** — `SET_PAINT_WARNING` if nothing matched. A
  repaint that silently no-ops is worse than one that fails.
* `matcheck.paint_check` now requires `not hasTexture` before calling a material flat.

**Re-validated in both directions, 3/3 — a fix that removes a false positive must not
remove the true one:**

| file | textured | flat-paint flag |
|---|---|---|
| `car_merged.glb` (good, untextured) | no | **False** ✅ |
| NC8 (genuinely flat, untextured) | no | **True** ✅ still fires |
| `rear2_v4.glb` (textured) | **yes** | **False** ✅ false positive gone |

### 3.1c The re-run, and what it does and does not prove

With `set_paint` fixed (it now reports `tinted: 7` on the textured rear and `set: 5` on
the untextured base), the rear file's paint **does** respond:

| file | carpaint px | mean \|Δ\| | % px moved >10 | base → alt |
|---|---|---|---|---|
| `rear2_v4.glb` (textured) | 49,355 | **15.72** | 73.5% | [87,42,42] → [42,42,44] |
| `car_merged.glb` (untextured) | 50,480 | **82.95** | 99.4% | [178,62,62] → [75,92,176] |

**So "the rear paint does not respond at all" was my bug, and it is retracted.**

**But the two numbers are NOT apples-to-apples and I will not present them as a ratio.**
On the untextured file I set the colour directly; on the textured file I could only
apply a MULTIPLY tint over a baked texture. Multiplying a dark-red baked texture by blue
yields **neutral dark grey, not blue** — which is what the table shows, and that is a
property of *my method*, not a verdict on the file.

**What this does raise, honestly, as an OPEN question rather than a finding:** a
name-targeted respray (what `colour_variants` and the viewer actually do) rewrites
`baseColorFactor`, which on a textured material also only *multiplies* the baked
texture. So a baked-colour paint may not be resprayable to an arbitrary colour by factor
rewrite at all. CLAUDE.md already points the same way — *"the flat-paint build stays the
respray base (photo bake embeds the capture colour)"*. **I have not tested a factor
rewrite on this file, so I am flagging it, not asserting it.** The test is cheap and
should be run before the rear lineage's textures are carried into a merged car:
rewrite `carpaint.baseColorFactor` in the glTF and re-render.

### 3.1b What DOES stand about `rear2_v4.glb` — and it is the part that matters

**`extensionsUsed` is absent entirely.** No `KHR_materials_transmission`, no
`KHR_materials_ior`, no `KHR_materials_clearcoat`, where all six other gate files carry
all three. Concretely, its `glass` is `BLEND` at alpha 0.353 with **`transmission: null`
and `ior: null`** — glazing that has stopped refracting. That is the trimesh-round-trip
signature CLAUDE.md names, and `glass_probe` still returns **clear / proven** on it
because `alphaMode` survived. **This is a real defect and the merge must take the rear
geometry onto the `car_rebound` material table, not the rear file's own.**

**And a genuine new finding I had missed: the rear lineage is TEXTURED and the other six
are not** (4 images vs 0). Any merge that carries rear geometry across must decide
whether the textures come with it and whether the receiving primitives have UVs.

**Softened:** `Tyre_Rubber` at 0.0484 against the other files' 0.0288. Both materials
are untextured so the comparison is valid — but 0.048 is still plainly black rubber, so
this is a *difference between lineages*, not a defect. My acceptance threshold A6
(0.027 ± 0.010) is too tight to be a defect test and should read "black rubber, i.e.
mean base colour < 0.12" with the exact value recorded.

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

### 3.5b Two MANIFEST claims verified rather than quoted

* **Glass gate — "label reassignment only. No vertex moved, no face was deleted."**
  **TRUE.** Faces 985,227 → 985,227 (delta 0). Max face-centroid displacement
  **0.0135 µm**, against a float32 ULP at this scale of **0.238 µm** — 100.0000% of
  faces coincide at a 0.1 µm tolerance. It is re-export rounding, not movement.
  *Caveat the merge must respect:* the referenced vertex count rises 702,178 →
  704,918 (+2,740), because a node repartition splits shared vertices at the new node
  boundaries. The two files share a **surface**, not a vertex array.
  *(My first pass used a 1 nm tolerance and reported "point sets differ" — a wrong
  tolerance, not a wrong file. Recorded because it is the same class as measuring
  against your own exclusion boundary.)*
* **Cabin gate — Body_Shell −3,544 and Interior −149,302 faces.** **BOTH EXACT**:
  190,385 → 186,841 and 331,014 → 181,712.

### 3.6 The cabin's 28 components are provably constructed, not relabelled

Same geometric-provenance test as §3.2, run on `car_cabin.glb`: **all 28 `Cabin_*`
nodes score 0.000% face-centroid coincidence with `car_rebound.glb`.** So the cabin
gate built new geometry rather than renaming parts of the `Interior` melt shell —
which is the failure the provenance test exists to catch, and it did not happen here.
(`Interior` itself drops 331,014 → 181,712 faces, consistent with its own report.)

### 3.7 Two gates do not carry the merge's grounding fix

`car_glass_v4.glb` and `GOLF_V7_FRONT_GATE.glb` are built on `car_rebound.glb`, so
their tyres are still at FL **183.178 mm** / FR **189.636 mm** in the air. Only
`car_merged`, `car_deskin` and `car_cabin` carry the grounded pose. The merge has to
transport the glass relabelling and the v7 front kit onto the grounded base — the
grounding win is the one most easily lost in a merge, and it is the cheapest to check.

---

## 3.8 MERGE COLLISION SCAN — the thing no gate's own report can contain

Every gate built against `car_rebound` alone, so **no gate could see whether its new
component occupies the same space as another gate's**. I scanned all of them: for each
contributed component, what share of its faces sit within 25 mm of a surface the merged
car would also inherit from a different source.

### One severe cross-gate collision

| pair | share within 25 mm | median separation |
|---|---|---|
| **rear v2 `Glass_Backlight` vs glass gate `Glass_Rear`** | **96.21%** | **4.8 mm** |
| rear v2 `Hatch` vs glass `Glass_Rear` | 27.41% | 126.6 mm |
| rear v2 `Bumper_Rear` vs v7 `Bumper_Front` | 0.00% | 3793.5 mm |
| cabin `Cabin_Headliner` / `Cabin_Dash` vs glass `Glass_Windscreen` | 0.00% | 897 / 402 mm |

The rear gate built a **constructed 0.3871 m² raked backlight** (mean \|n_up\| 0.625);
the glass gate's `Glass_Rear` is **0.8358 m² of near-vertical glazing** (mean \|n_up\|
0.037). **96.2% of the constructed backlight sits within 25 mm of it, median 4.8 mm** —
two transmissive sheets in the same place. That is exactly the defect CLAUDE.md records
from the white-dot saga: *overlapping stencils gave one physical window four stacked
quadric sheets, and grazing transmission through intersecting sheets blooms white.*
**One of the two must supersede the other; taking both reproduces a defect that already
cost six wrong theories and several production rounds.**

`Hatch` vs `Glass_Rear` at a 126.6 mm median is the hatch *surrounding* the screen, not
stacking on it — proximity without coincidence. Everything else is comfortably clear.

### Base parts each gate supersedes — delete them, or they stack

These overlaps are *expected and correct* provided the base part is removed. They are
listed because the merge silently keeping a base part is how the collision happens.

| gate component | overlaps base surface | share within 25 mm | median |
|---|---|---|---|
| v7 `Valance_Front` | `Bumper_Front_Paint` | **75%** | 12.0 mm |
| v7 `Intake_L` | `Bumper_Front_Paint` / `Headlamp_L` | 57% / 48% | 21 / 28 mm |
| v7 `Grille_Lower` | `Bumper_Front_Paint` | 32% | 41.1 mm |
| rear `Bumper_Rear_Inner` | `Bumper_Rear_Paint` | **43%** | 28.7 mm |
| rear `Plate_Rear` | `Bumper_Rear_Paint` | 31% | 33.7 mm |
| rear `Hatch_Inner` | `Bumper_Rear_Paint` | 25% | 41.9 mm |
| cabin `Cabin_Floor` / `Cabin_Headliner` | `Body_Shell` / `Interior` | 28% / 27% | 39 / 29 mm |

Two more readings worth carrying: rear `Tail_Lens_RO` sits **65% within 25 mm of
`Interior`, median 13.9 mm** — the melt shell is right behind the constructed lamp,
which is the same hidden-melt residue measured in row 9. And glass `Glass_Side_R` sits
**59% within 25 mm of `Interior`**, consistent with the through-glass finding that the
base side glazing has body and interior directly behind it rather than an aperture.

### Added to the acceptance list

* **A21 — no two transmissive surfaces stacked.** For every pair of glazing nodes in
  the merged car, no more than 5% of either may sit within 25 mm of the other.
  `Glass_Backlight` vs `Glass_Rear` currently scores **96.21%** and must be resolved
  by supersession before the merged car is judged on anything else.
* **A22 — every superseded base part is actually gone.** Check the seven rows above:
  each gate component should have **no** base counterpart left underneath it.

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
| NC7 — 8% of `Body_Shell` deleted at random | 15,360 | **0** | 0 | **17** | 0 |
| NC9 — a contiguous **150 mm disc** cut out of the roof (708 faces, 0.37%) | 15,360 | **0** | 0 | **4** | 0 |

The null is perfectly clean, so any non-zero reading is real signal. But the control
fired **only through the RECEDED class**: `lost` was **zero** even with 8% of the body
shell gone, because the cabin sits behind every panel and always stops the ray.
**A hole test that reports only "did the ray still hit something" would have scored
NC7 as a flawless pass on a car missing 8% of its body shell.** That is the
`intersects_any` trap, reproduced as a measurement rather than quoted as a warning —
and it is why `holes.py` reports the first-surface DEPTH change as well as the hit.

**`lost` is structurally zero on this car, and that is now proven on two different
hole geometries** — scattered triangle loss *and* a clean contiguous disc cut out of
the roof. Both are seen only as a first surface that recedes.

NC9 also behaves correctly in **direction**: of 15 directions, exactly **3 fired, and
all three are the el +18 (looking-down) views** — az +22, −22 and −40 — which are the
only ones that see the roof. A hole in the roof firing on the roof-viewing directions
and nowhere else is what a working test looks like.

**Sensitivity, stated as a number rather than assumed:** the ray bundle spans about
3.0 m across 32 samples, so ray spacing is **≈ 97 mm** at the 32×32 grid used here. A
150 mm hole therefore lands only ~4 firing rays. Holes much below ~150 mm are not
reliably detected at this density — run 64×64 (≈ 48 mm spacing) if small holes matter.
This is a property of the sampling, not of the car, and it is why the number to watch
is "did any direction fire at all", not the magnitude.

**Checks I could NOT prove can fail — say so rather than imply coverage** (two of the three were closed after the first draft and are struck through; one genuine item remains):

1. ~~**Khronos validator = 0 errors.**~~ **CLOSED — this gap is now tested.** Three
   independent deliberate spec violations were injected into `car_merged.glb`, so the
   result does not hinge on one code path:
   | control | injected | validator |
   |---|---|---|
   | — | (unmodified `car_merged.glb`) | **0 errors** |
   | NC12a | indices accessor declared `componentType` FLOAT | **2 errors** — `MESH_PRIMITIVE_INDICES_ACCESSOR_INVALID_FORMAT`, `ACCESSOR_MAX_MISMATCH` |
   | NC12b | accessor `count` ×97 beyond its bufferView | **1 error** — `ACCESSOR_TOO_LONG` |
   | NC12c | primitive references material index 999 | **1 error** — `UNRESOLVED_REFERENCE` |
   The "0 errors" on all seven gate files is therefore a measured pass, not an
   untested zero.
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

## 6b. What the merged car must satisfy — the acceptance list, fixed in advance

Run `python3 verify_merged.py <merged.glb> <outdir>` (plus the respray and hole
passes). These thresholds were set from the source files **before** the merged car
existed.

| # | must hold | threshold |
|---|---|---|
| A1 | four tyre nodes' world-space minima on the contact plane | max air ≤ **1.0 mm** — and measured from TYRE NODES, not the bbox |
| A2 | `Glass_Windscreen` area | ≥ **0.90 m²** (and total glazing ≥ **3.30 m²**) |
| A3 | glazing verdict **paired** with area | `glass_probe` clear/proven **AND** A2 — neither alone |
| A4 | KHR extensions present in the written table | `KHR_materials_transmission` + `_ior` on glazing, `_clearcoat` on paint |
| A5 | `carpaint` is not glTF defaults | not `[1,1,1,1] metallic 1 rough 1` |
| A6 | `Tyre_Rubber` base colour | **0.027 ± 0.010** |
| A7 | respray control at 3 locked cameras | carpaint Δ ≥ **25**; tyres/rims/lamps Δ ≤ **10**; tail lamps stay red-dominant |
| A8 | Khronos validator | **0 errors** |
| A9 | NORMAL accessors | **0 missing, 0 zero-length, 0 non-unit** on every primitive |
| A10 | component inventory | **89** named nodes, none empty, **no two names on one mesh** |
| A11 | v7 front kit symmetry | worst L/R pair ≤ **1e-3 mm** about the kit datum |
| A12 | v7 centreline parts | ≤ **0.01 mm** from that datum |
| A13 | front-kit provenance | ≤ **1.0%** face-centroid coincidence with `car_rebound` |
| A14 | rear hidden melt | ≤ **5%** of on-panel rays, **quoted with its ray grid** |
| A15 | rear panels smoother than the melt they replaced | rebuilt < ⅓ of the melt at 20 mm radius |
| A16 | roof/bonnet specks | ≤ **2× the clay floor** measured in the same run |
| A17 | no new holes vs `car_merged` | `lost` ≤ `gained` **and `receded` ≈ 0** — reporting only `lost` is not a test |
| A18 | through-glass | `Interior` ≤ **10%** of through-glass rays |

**Two things to check that no gate's own report covers:**
* **A19 — lateral datum consistency.** The front kit sits at z = +27.30 mm and the
  rear kit at ≈ −70 mm. Confirm the merged car's fascias land where intended and put
  one 3/4 render in front of the owner.
* **A20 — the grounding must survive.** `car_glass_v4` and `GOLF_V7_FRONT_GATE` do
  **not** carry it. This is the win most easily lost in a merge and the cheapest to
  check (A1).

---

---

## 9. THE MERGED CAR — full findings

`GOLF_ALL_GATES.glb` · 25,684,968 B · sha `400d994a…` (byte-exact vs MANIFEST) ·
83 nodes · 888,807 faces · 107 primitives · published with a Draco mobile at
`staging/final/mobile/`.

### 9.1 DEFECT 1 — the published DESKTOP and MOBILE assets are DIFFERENT CARS

The mobile receipt's `in_sha` is `c3404a28…`; the published desktop file is
`400d994a…`. They are not the same build, and the geometry proves what that costs:

| node | desktop | mobile |
|---|---|---|
| `Glass_Rear` | **187 faces / 0.0119 m²** | **9,890 faces / 0.8358 m²** |
| `Body_Shell` | 177,954 | 177,440 |
| `Interior` | 165,537 | 163,592 |
| `Wheel_FR_Disc` | 2,620 | 2,616 |
| total glazing | **2.9594 m²** | **3.7833 m²** |

The mobile's `Glass_Rear` **is** the original glass-gate geometry (9,890 faces; radial
signature matches to 0.042 mm). So the mobile still carries the stacked rear glazing
the desktop was fixed for — I re-ran the A21 collision check on it:

| asset | backlight within 25 mm of rear screen | median |
|---|---|---|
| **desktop (published)** | **0.00%** | 218.8 mm |
| **mobile (published)** | **96.18%** | **4.8 mm** |

96.18% against the pre-fix 96.21%. **The mobile asset reproduces the white-dot
stacking defect in full.** This is the silent serving-path divergence CLAUDE.md
already records — two artefacts published to the same folder 13 seconds apart that
disagree. Rebuild the mobile from the published desktop file and re-verify.

### 9.2 DEFECT 2 — 8 of the rear gate's 14 components did not arrive, and the receipt says PASS

Present and **vertex-identical** to the rear file: `Hatch` (10,917), `Hatch_Inner`
(11,823), `Bumper_Rear` (16,796), `Bumper_Rear_Inner` (17,386), `Plate_Rear` (297),
`Glass_Backlight` (7,301).

**Absent: all eight constructed tail-lamp units** — `Tail_Lens_LO/RO/LH/RH` and
`Tail_Housing_LO/RO/LH/RH`. Their materials are gone too (`Tail_Lens_Red`,
`Tail_Housing` are not in the merged material list). The car falls back to the base
`TailLamp_L`/`TailLamp_R` (1,153 / 1,144 faces). The rear receipt's own material
census records `Lamp_Lens_Rear → TailLamp_L, TailLamp_R` — the correct state — and
still reports **`VERDICT: PASS`**. The shortfall is recorded but not flagged.

This matters beyond component count: CLAUDE.md notes the constructed lamps were the
thing that **held their red through a respray** as component behaviour. The base
lamps do still hold red here (measured, all four views), so nothing is broken — but
the rear gate's lamp rebuild is simply not in the car.

### 9.3 What I checked and found GOOD

* **A1 grounding — the win most easily lost in a merge.** All four tyres at
  **0.000 mm**. (The whole-model bbox reads −4.587 mm and would have misled.)
* **A2/A3 glazing paired with area.** `Glass_Windscreen` **0.9894 m²** — the glass
  gate's win carried across exactly. `glass` carries `transmission 0.92` + `IOR 1.45`;
  `glass_probe` clear/proven **and** 2.9594 m² of glazing behind it.
* **The rear-glazing reduction is a correct tightening, not a loss.** Total glazing
  fell 3.3956 → 2.9594 m² because the old 0.8358 m² `Glass_Rear` was replaced by the
  constructed 0.3877 m² backlight. I checked for an unglazed aperture and the render
  settles it: **the rear screen is properly glazed** (`evidence/MERGED_REAR.png`).
  My A2 total-area floor of 3.30 m² was set before the collision fix existed and is
  **wrong for this car** — the windscreen-specific ≥0.90 m² is the load-bearing half.
* **A7 respray, four locked cameras.** carpaint **38.7 / 46.9 / 82.8 / 85.1**;
  Tyre_Rubber 1.33–2.90, Rim_Alloy 1.70–5.52, Lamp_Lens 3.4, Lamp_Lens_Rear
  1.98–6.36, Brake_Disc 0.40–0.84 — every frozen material far under the ≤10 bar.
  **Tail lamps hold red in all four views.** `SET_PAINT set: 15, tinted: 0`, so this
  is a direct colour set and is apples-to-apples.
* **A8 validator 0 errors / 0 warnings** on the desktop **and** the mobile.
* **A9** NORMAL present and unit-length on **107/107** primitives.
* **A10 hierarchy** 83 nodes, **no empty nodes**, **no two names sharing one mesh**.
* **A11/A12 v7 symmetry — and a correction to my own first reading.** My runner
  initially reported **50.45 mm** and that was **my artefact**: it mirrored about a
  z = const plane, but the merge applies a 4.73° rotation about a *tilted* axis, so
  the kit's plane is no longer z = const. Fitting the plane (3 parameters, nothing
  assumed) gives a normal **2.34° off +Z** and a worst pair residual of
  **1.59e-04 mm**, with all seven centreline parts within **1e-5 mm**. The v7 kit is
  vertex-identical to its source (720/720, 4224/4224 …) — transported, not rebuilt.
  `verify_merged.py` now fits the plane so it cannot repeat the error.
* **A13 provenance** — 54 nodes at **0.0%** face-centroid coincidence with
  `car_rebound`: the front, rear and cabin components are genuinely constructed.
* **A21 collision RESOLVED** on the desktop: 96.21% → **0.00%**.
* **A22 no stacking.** Every new component is clear of the surviving base parts
  (worst `Intake_L` 37.7% within 25 mm, median 41 mm — adjacency, not coincidence;
  pre-merge those pairs sat at 57–75% and 12–21 mm). The base parts were stripped:
  `Bumper_Front_Trim`, `Headlamp_L`, `Headlamp_R` **deleted**;
  `Bumper_Front_Paint` 58,448 → 25,064; `Interior` 331,014 → 165,537.
* **A16 specks.** Roof **4.070% (pre-skin) → 0.106% (skin output) → 0.287% (merged)**
  against a merged clay floor of 0.111% — **2.6× its own floor, where the skin gate's
  own output sat at 6.5×**. The win is retained. The bonnet zone is **not** comparable
  like-for-like: the v7 front kit now occupies it, and the clay floor there moved
  0.000% → 1.719%, which is the zone content changing rather than the surface
  degrading.
* **Visual, matched camera, same rig** (`evidence/MERGE_BEFORE_AFTER.png`): flanks and
  sills markedly cleaner, a real grille/headlamp/intake at the nose, and seats,
  headrests and a steering wheel visible through the glazing where the base showed a
  grey melt blob.

### 9.4 A17 holes — one localised loss, located but NOT visually confirmed

15 directions, 15,360 rays, merged car vs `car_merged`:

| | rays | lost | gained | receded | advanced |
|---|---|---|---|---|---|
| merged vs `car_merged` | 15,360 | **9** | 7 | 44 | 216 |

`advanced 216` and `receded 44` are expected — four gates of new components sit proud
of the base, and the rear screen surface moved back to the constructed backlight.
`lost 9` (0.059%) is the number that matters. **All nine are now located** — an
earlier draft of this report accounted for only seven and is corrected here:

| # rays | location (m) | previously stopped by | reading |
|---|---|---|---|
| **5** | x 1.546–1.550, y 0.265–0.381, **z +0.821** | `Bumper_Rear_Paint` ×3, `Arch_Liner` ×2 | **rear-right arch / bumper junction** — the merge stripped `Bumper_Rear_Paint` 62,204 → 33,485 and the new `Bumper_Rear` does not cover this spot |
| **2** | `[-0.748, 0.901, 0.704]`, `[0.115, 1.275, 0.528]` | `Interior` | **cabin see-through** — a closed melt shell became discrete furniture, so a ray can enter one window and leave by another. **Expected, not a defect.** |
| **1** | `[-2.118, 0.18, 0.05]` | `Bumper_Front_Paint` | **front lower valance, on the centreline** — the v7 strip took `Bumper_Front_Paint` 58,448 → 25,064 and left a ray-sized gap at the nose bottom |
| **1** | `[1.588, 1.256, 0.472]` | `Glass_Rear` | **top-right of the rear screen** — the constructed backlight does not reach where the deleted `Glass_Rear` used to |

**That last row qualifies a conclusion I drew earlier in this report.** I wrote that the
rear-glazing reduction (0.8358 → 0.3996 m²) is "a correct tightening, not a loss",
on the strength of the render showing a properly glazed rear screen. That remains true
for the bulk of the screen — but there is **at least one ray-sized spot at its upper
right that the constructed backlight does not cover** and that the old glazing did.
The tightening is therefore *mostly* correct with a small uncovered corner, not
uniformly correct. Stated as a correction rather than quietly folded in.

At ~97 mm ray spacing, the 5-ray rear-right cluster implies a gap of roughly
100–200 mm; the two single rays imply spots at or below ~100 mm and could each be a
single missing triangle patch.

**HONEST LIMIT: I did not visually confirm any of these four locations.** Two render angles at
el −8 and −14 showed the underbody rather than the arch lip and were inconclusive. So
this is reported as a *located, quantified loss of first-surface coverage* for the
builder to check, **not** as a confirmed through-hole. The measurement is sound — the
null on this instrument is 0/0/0/0 over 15,360 rays — but the eye has not yet agreed
with it, and on this project the eye is the arbiter.

---

## 7. Bottom line

**5 of the 6 gates' wins survived the merge intact.** Grounding (0.000 mm × 4), the
glass gate's windscreen (0.9894 m²), the cabin (28/28, `Interior` out of the glazing),
the v7 front kit (20/20, 0.0% reuse, 1.59e-04 mm symmetry) and the skin gate's specks
all carried across. **Rear v2 is PARTIAL: 6 of its 14 components arrived; the eight
constructed tail-lamp units did not, and the rear receipt reports PASS anyway.**

**Two defects, one of them serious.** The published **mobile asset is a different car
from the published desktop asset** — built from a pre-fix intermediate, it still scores
**96.18%** on the glazing-stacking collision the desktop was fixed to **0.00%**. And **nine lost rays in four
places** — a 5-ray cluster at the rear-right arch/bumper junction, one at the front
lower valance, one at the top-right of the rear screen, and two that are expected
cabin see-through. Located and quantified; **none visually confirmed**.

**Everything else passes:** validator 0/0 on both files, NORMALs 107/107, respray
control clean on four cameras with tail lamps holding red, no stacking, no empty nodes,
no two names on one mesh, 54 nodes of genuinely constructed geometry.

**Nine of my own errors are recorded in this report rather than dropped** — including
the v7 symmetry reading of 50.45 mm that was my own frame assumption and is actually
1.59e-04 mm, and the retracted flat-shell call on a textured material. Three of the
nine were caught only by looking at a picture or at an impossible number.
