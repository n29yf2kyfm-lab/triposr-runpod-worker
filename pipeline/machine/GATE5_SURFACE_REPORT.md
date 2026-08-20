# Gate 5 — Class-A body-surface repair, VW Golf Mk8 master

**Car:** `car.glb` — 4.284 × 1.789 × 1.456 m, 985,227 faces, 6 label submeshes
**Delivered:** `golf_g5_repaired.glb` — 984,964 faces, 65,122,208 bytes,
sha256 `968303b840801efa61d6201095464032626621c3349d079588cbadbe791b81bd`
**Chain:** geometric exterior-panel selection → whole-car welded thin-plate fairing
(lam 3000, feature-hold 300) → mesh hygiene.

**Overall: the gate is NOT PASSED. 1 of 6 acceptance criteria passes.** The repair is a real,
render-visible geometry improvement on the panel *fields* — waviness down 24–29% on the bonnet and
flanks, median slope error down 23% — and it does not reach Class-A on any surface criterion. Two
criteria are shown to be **unreachable by local repair** and to need reconstruction. Details and
costs in §6.

**Constraint observed.** No smooth shading, weighted normals, subdivision or glossy paint carries
any claim here. The geometry claim is made from **FLAT-shaded** renders, which contain no vertex
normals at all. Every smooth-shaded comparison puts the *same* recomputed-normals treatment on both
sides, via a lam=0 control that moves geometry by exactly **0.00 mm** and leaves crease length
unchanged at 891.93 m.

---

## 1. Two measurements that changed what a correct repair looks like

Made before any repair was attempted.

**The six meshes are one surface, cut into label submeshes.** 25,369 `carpaint` vertices are
*exactly* coincident with `interior` vertices; every mesh shares vertices with `interior`:

| | interior | carpaint | glass | rim | tyre |
|---|---|---|---|---|---|
| **interior** | – | 25,369 | 7,030 | 5,869 | 4,290 |
| **carpaint** | 25,369 | – | 4,676 | 384 | 1,072 |

Repairing one geometry alone moves one copy of a shared vertex and not the other — it **opens a
crack in 25,369 places**. A per-geometry repair here is not partial, it is destructive.

**The material names do not delimit the body.** `interior` is bound to the front bumper and the
sills and holds **107,936 of the 244,723 exterior body-panel faces — 9.18 m² of 20.54 m², 45% of the
body**, including two panels this gate names (rocker/sill, rear bumper). So the body is selected
*geometrically*: 32 uniform rays per face centroid, exterior = escapes often. It never consults the
face normal — this mesh carries large patches of inverted normals, and a normal-direction test fails
in plausible-looking *regions* rather than at random. Verified by rendering the selection alone: it
is the outer skin, sills and bumper present, glazing and wheels absent.

---

## 2. The metric and its calibration

`sigma_theta(R)`: area-weighted RMS angle between each panel face's normal and the local quadric
fitted to its neighbourhood, at 25 mm (roughness) and 80 mm (waviness). The quadric absorbs honest
crown, so a curved panel is not penalised for being curved.

**The catalogue-car calibration was confounded and is withdrawn.** Against 14 audited catalogue cars
this Golf scored a *lower* sigma than every one (3.7° vs 9–32°). That is not evidence it is
smoother: sigma uses a physical radius, this Golf's median edge is 14 mm and a 19,200-face catalogue
car's is 60 mm+, so on the catalogue car a 25 mm ball holds almost nothing and the number describes
the sampling. Real cars also carry deliberate hard-surface detail, which raises sigma honestly.

**Replaced by a synthetic reference of known quality at this car's own sampling density** — a
doubly-curved panel with real roof crown radii (2.0 × 8.0 m), irregularly triangulated at 14 mm,
displaced by band-limited noise near the generator's voxel pitch (white per-vertex noise would be
far easier for a quadric to reject and would flatter the floor):

| noise (mm) | 0 | 0.05 | 0.10 | 0.25 | 0.50 | 1.00 | 2.00 |
|---|---|---|---|---|---|---|---|
| sigma 25 mm (°) | **0.077** | 0.350 | 0.687 | 1.708 | 3.410 | 6.798 | 13.414 |

* **Floor 0.077°** — a perfect surface at this tessellation. The metric is not tessellation-bound.
* **Scale ≈ 6.8° per mm**, so any sigma reads in millimetres.
* **Pure noise scores coherence 0.21–0.42; this car's panels score 0.69–0.80.** The earlier reading
  of this car as "incoherent melt" is **not supported** and is withdrawn — its residual is far more
  organised than noise.

---

## 3. The repair

Whole car welded once (592,715 → 485,832 vertices); thin-plate fairing solves over that single
surface; result scattered back to every duplicate, so seams stay sealed by construction. Everything
that is not exterior panel is *held* by a large data weight rather than excluded — a hold arrives at
its value smoothly, a mask leaves a step. Held geometry moves mean 0.085 mm, max 2.0 mm.

lam sweep, every variant scored on the **same fixed baseline face mask** (feature-hold 60):

| lam | crease | flank s25 | flank s80 | bonnet s80 | all s80 |
|---|---|---|---|---|---|
| 50 | −1.1% | −8.5% | −11.5% | −9.4% | −6.9% |
| 200 | −2.2% | −11.2% | −18.3% | −15.6% | −10.5% |
| 800 | −3.3% | −13.8% | −25.4% | −22.1% | −13.6% |
| 3000 | −5.7% | −15.7% | −30.8% | −26.9% | −16.2% |

**Delivered: lam 3000, feature-hold 300.** Crease 891.9 → 844.4 m (−5.3%):

| region | s25 before → after | s80 before → after |
|---|---|---|
| all | 5.388 → 5.260 (−2.4%) | 6.364 → 5.402 (**−15.1%**) |
| flank | 3.481 → 2.941 (**−15.5%**) | 5.947 → 4.228 (**−28.9%**) |
| bonnet | 4.925 → 4.181 (**−15.1%**) | 8.096 → 6.139 (**−24.2%**) |
| roof | 5.210 → 5.118 (−1.8%) | 4.984 → 4.485 (−10.0%) |

**The gate's defect list is almost entirely 80 mm-band** — bonnet waves, roof waves, door dents,
quarter deformation, fender ripples, bumper swelling — and that band improves 10–29%.

### Distribution, on identical faces (142,371), and a correction to my own earlier reading

| | before | after | change |
|---|---|---|---|
| median | 0.972° (0.14 mm) | 0.752° (0.11 mm) | **−22.6%** |
| p75 | 3.344° | 2.458° | **−26.5%** |
| p90 | 9.321° | 8.372° | −10.2% |
| p99 | 27.459° | 28.735° | +4.6% |
| single-sheet faces | 0.588° (0.086 mm) | 0.447° (0.066 mm) | **−24.0%** |
| area-weighted RMS | 5.354° | 5.247° | −2.0% |

**The RMS is not a description of this car.** The hottest 5% of faces carry **75% of the
squared-slope energy**. The bulk of the surface improves by roughly a quarter while a small,
severely defective population is untouched, and that population sets the RMS.

**A hypothesis I formed from the heat map and then disproved.** I read the error as living on
aperture edges and shut lines. The ring-distance decomposition says otherwise — faces **11+ rings
from any feature carry 64.5% of the energy** at sigma 4.55. Edge bands *are* hotter per unit area
(8.1–10.4°) but are far too small to dominate. The real discriminator is **neighbourhood
thickness**: faces whose 25 mm ball spans a single sheet score **0.45°**; faces whose ball spans
>17 mm score **18.6°**. That is a doubled-shell / fragment-soup signature, not an edge problem, and
it is why fairing the outer sheet cannot move it.

---

## 4. Mesh hygiene

Measured per glTF primitive, straight out of the binary chunk. The 30 zero-length normals *are* the
master's 30 validator errors; the 17 repeated-index triangles in `interior` are its 17 reported
degenerate triangles.

| | master | delivered |
|---|---|---|
| zero-length NORMAL | 30 | **0** |
| non-unit NORMAL | 30 | **0** |
| zero-area faces | 23 | **0** |
| repeated-index (degenerate) | 17 | **0** |
| aspect ratio max | 2.7 × 10¹² | **71.7** |
| faces above 50:1 aspect | 55 | **9** of 984,964 (0.0009%) |
| **Khronos glTF-Validator** | **FAIL — 30 errors** | **PASS — 0 errors, 0 warnings, 0 infos** |

Method: zero-area faces are dropped (a face with no area contributes no pixels, so removal cannot
open a hole); sub-0.20 mm edges are *collapsed* rather than the slivers deleted (deleting a real
2500:1 triangle would open a real hole; merging its corners moved the surface by at most **0.17 mm**,
below the 2.5 mm voxel the geometry was generated on); normals are rebuilt, because a zero-length
normal has no direction in it to preserve. 263 faces removed in total. UVs preserved on both
primitives that carry them.

*The fairing itself created 30 new zero-area faces (carpaint 6 → 36); hygiene removed those too.*

---

## 5. Left/right symmetry — probe validated before the finding was believed

The probe was first run against an **exactly mirror-symmetric control** built from this car's own
left half at the same tessellation:

| | median | p90 | >2 mm | mid-plane found |
|---|---|---|---|---|
| symmetric control | **0.0000 mm** | 0.0000 mm | **0.00%** | +0.0000 exactly |
| **Golf master, panel set** | **22.72 mm** | 100.68 mm | **87.9%** | – |
| delivered | 23.22 mm | 90.21 mm | 88.1% | – |

Point-to-*triangle* distance against the reflected surface (vertex-to-vertex would report several
millimetres on a symmetric shape whose sides are merely tessellated differently). Per-side flank
quality also differs: sigma25 left 3.842° vs right 3.055°, a 22.8% relative difference.

**The body is genuinely, grossly left/right asymmetric — 87.9% of sampled panel points sit more than
2 mm from their mirror image — and local fairing neither fixes nor worsens it.** A scanned mid-plane
was rejected as evidence: on an asymmetric object that objective is nearly flat (median varies only
21.3–24.5 mm across a ±60 mm sweep) and its optimum pinned to the window boundary while printing a
confident number. The geometric mid-plane is used instead, and it is trustworthy here — the panel
set spans −0.8945 … +0.8942, centred to 0.3 mm.

---

## 6. PASS / FAIL against each acceptance criterion

| # | Criterion | Verdict | Evidence |
|---|---|---|---|
| 1 | Continuous reflection flow | **FAIL** (materially improved) | Zebra sheet: field regions coalesce into larger, smoother bands; perimeter contour chatter persists. Class-A wants a handful of smooth parallel bands; this shows irregular blobs plus dense contour noise at every panel perimeter. |
| 2 | No visible triangle chatter | **FAIL** (materially improved) | Flat-shaded clay: the door's faceted blotching is largely resolved and the panel reads as continuous. Residual facet structure remains at arch lips, sill and the p90 population (8.37°). |
| 3 | No broad dents or scan noise | **FAIL** (materially improved) | s80 −24% bonnet, −29% flank; median −22.6%. But dimples remain visible on the front door in flat clay, and p99 slope error is unchanged. |
| 4 | Consistent left/right manufactured curvature | **FAIL — not reachable by local repair** | 22.7 mm median mirror distance, 87.9% >2 mm, on a probe that scores 0.0000 mm on an exact symmetric control. Unchanged by fairing. |
| 5 | Clean edge flow around apertures and panel gaps | **FAIL — not reachable by local repair** | Rings 0–10 from a feature score 8.1–10.4° against 4.5° in the field. Shut lines ramp over many face rings instead of being crisp. These are the protected features; fairing them is what would destroy them. |
| 6 | No zero-area or stretched faces | **PASS** | zero-area 23 → 0, degenerate 17 → 0, aspect max 2.7e12 → 71.7, 9 faces above 50:1 out of 984,964. Khronos validator FAIL (30 errors) → **PASS (0 errors, 0 warnings)**. |

### What criteria 4 and 5 would take

Both are **reconstruction jobs, not repair jobs**, and the spec permits saying so.

* **Symmetry (4).** The cheap route is to mirror the better flank onto the worse across the measured
  mid-plane and re-fair the seam — hours, but it discards genuine asymmetric detail (fuel filler,
  exhaust, badges) and must be masked around them. The correct route is to rebuild each panel as a
  surface fitted to a symmetric control net. Nothing local fixes a 22 mm mirror error.
* **Edge flow (5).** Apertures must be rebuilt as explicit boundary curves — fit the shut line as a
  space curve, rebuild the panel edge to it, and let the panel surface terminate on that curve —
  rather than inherited from a voxel grid whose 2.5 mm pitch cannot represent a 2–4 mm gap. This is
  the same conclusion the machine's own history reaches: the generator never sampled the feature, so
  no filter can restore it.
* **The doubled-shell population (the p90/p99 tail)** is the third reconstruction item, and it is
  the one that holds the RMS up. Those faces are where the outer skin runs within ~18 mm of a second
  surface; the region needs to be re-sheeted, not smoothed.

Criteria 1–3 are then reachable: with the fields already at 0.45° (0.066 mm equivalent) on
single-sheet faces, the surface *away from* those three problems is close to the metric's own floor.

---

## 7. Evidence

`car-meshes/staging/gate5_surface/`

* `glb/golf_g5_repaired.glb.part_00..02` + `MANIFEST.txt` (sha256 above; reassemble with `cat`)
* `sheets/G5_CLAY_BEFORE_AFTER.jpg` — 8 panels, matte clay + 7 long strip lights
* `sheets/G5_ZEBRA_BEFORE_AFTER.jpg` — 8 panels, chrome + hard strips
* `sheets/G5_NORMALS_BEFORE_AFTER.jpg` — 8 panels, world-space normal, unlit
* `sheets/G5_CLAY_FLAT_BEFORE_AFTER.jpg` — **flat-shaded, the geometry claim with shading removed**
* `evidence/` — calib.json, score_sweep.json, score_final.json, zones_before/after.json,
  symmetry.json, hygiene.json, validate.log, bodysel.npz

All renders replay one locked camera spec; before and after are the same cameras by construction,
not by promise. Tools: `class_a_views.py`, `body_surface.py`, `panel_reform.py --joint`,
`surface_metric.py`, `surface_score.py`, `surface_calib.py`, `surface_map.py`, `panel_symmetry.py`,
`mesh_hygiene.py`, `ab_sheet.py` — all committed.
