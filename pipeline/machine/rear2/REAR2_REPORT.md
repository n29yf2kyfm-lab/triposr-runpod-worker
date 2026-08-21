# REAR GATE v2 — HATCH AND REAR BUMPER SURFACES REBUILT

**Deliverable:** `car-meshes/staging/rear_v2/glb/rear2_v4.glb.part_000..003` +
`MANIFEST_rear2_v4.glb.txt` (66,485,700 B reassembled, `cat` in part order).

**Input chosen: Gate 4's `rear_v3.glb`** (65,349,280 B, sha256
`734542a2e302d25376780d2a89195d441a3d5f05e4366dda657c640660447862`, matching Gate 4's
manifest byte for byte).

*Why:* acceptance criterion 4 requires Gate 4's four lamp solids intact and holding
colour through a respray, and they exist **only** in this file. On `car_rebound` /
`car_merged` the best-named rear nodes (`TailLamp_L/R`, `Bumper_Rear_Paint/Trim`) are the
original melt under clean semantic names, so choosing either would have meant abandoning
criterion 4 or rebuilding lamps my brief puts out of scope.

*Risk accepted:* `rear_v3` carries Gate 4's material table (carpaint textured, metallic
1.0) rather than Gate 7+8's rebind, and it is **not grounded or de-pitched** — the merge
operator must re-apply grounding to this output.

*What I would have seen if that were the wrong call:* glass_probe not clear/proven, tyres
not black, or the respray control failing on the input. All three were tested BEFORE any
geometry was touched: glass clear/proven, `Tyre_Rubber` baseColorFactor 0.047, validator
0 errors. Had any failed I would have switched to `car_merged` and ported the lamps.

---

## 1. ACCEPTANCE

| # | criterion | verdict | measurement |
|---|---|---|---|
| 1 | hatch + rear bumper are REBUILT Class-A surfaces, not regrouped melt | **PASS** | Geometric provenance, the Gate 3 v6 test. Every rebuilt node scores **0.00%** of its vertices coincident with any source vertex (Hatch 0.0, Hatch_Inner 0.0, Bumper_Rear 0.0, Bumper_Rear_Inner 0.0, Plate_Rear 0.0, Glass_Backlight 0.0); every inherited node scores **100.00% at 0.000 mm**, including the renamed-melt control `Rear_Upper_Legacy_Melt`. Independent signature: valence-6 share 91.7-96.6% on rebuilt panels vs 5.5-27.5% on melt. Surface quality, SAME estimator on both: rebuilt hatch **0.2236 mm rms** waviness, rebuilt bumper **0.1307 mm rms**, against the melt they replace at **2.3913 / 2.2859 mm rms** — 10-18x better. |
| 2 | no hidden melt underneath | **PASS** | Radial rays through both footprints, naming the owner of every crossing within 100 mm behind the outer skin. Rays with a NON-REBUILT surface in that window: **hatch 1.92%, bumper 3.61%**. Before the rebuild the same rays found a second melt surface within 100 mm on **97.52% (hatch) / 100.0% (bumper)**. First surface is now the rebuilt panel on 694 of 832 hatch rays. |
| 3 | structurally separate named components; no crack or hole | **PASS with a measured caveat** | 26 named meshes. 15-direction ray test (az 0/+-22/+-40 x el 0/+-18, 29,040 rays): **36 rays of 22188 lost the surface entirely (0.162%)**. 687 rays (3.2585%) see the nearest surface recede >60 mm; the map shows those lie on the shut lines, the plate recess and the tailgate's upper join — largest connected component 43 rays, none a blob mid-panel. NEGATIVE CONTROL FIRES: a 90 mm through-hole punched in the tailgate moves the figure 3.2585% -> 4.4979%. |
| 4 | Gate 4's four lamp solids intact and holding colour | **PASS** | The two hatch units sit on the REBUILT skin: **0.00% of vertices buried**, minimum clearance +4.65 / +1.86 mm, median +24.63 / +26.54 mm. The two outer units sit on the quarters, which this gate does not rebuild: `Tail_Lens_LO/RO` and `Rear_Quarter_L/R` are **100% coincident with source, max displacement 0.0 micron** — preserved by construction, not by assertion. All four lens units still watertight, still bound to the single `Tail_Lens_Red` material. |
| 5 | rear screen boundary clean; glass_probe still clear/proven | **PASS** | The backlight aperture is a rectangle in the tailgate's own parameter space with grid lines placed exactly on its edges, so the boundary is clean **by construction**; the pane is cut from the same grid, so pane and aperture cannot disagree. `glass_probe` verbatim on the file: **clear / proven**, flat_shell False, alpha_shell False. Source raggedness for scale: the old glazing label's sill wandered over **100 mm** (min y 0.894 at z=-0.54 against 0.994 at z=-0.14) and reached z -0.729 one side against +0.445 the other. |
| 6 | left/right correspondence against the shear | **REPORTED, not claimed symmetric** | Rebuilt tailgate symmetric to within **17 mm** in lateral reach (it lives between the lamps, where the body is not sheared). Rebuilt bumper carries the body's real shear of **134-199 mm**, and surface depth at mirrored abs(z)=0.45 differs by up to **45 mm**. The rebuild PRESERVES the car's measured asymmetry rather than inventing symmetry it does not have. |
| 7 | validator 0 errors; fresh import clean | **PASS** | `gltf-transform validate rear2_v4.glb`: **No errors found. No warnings found. No infos found.** (HINTs only: BUFFER_VIEW_TARGET_MISSING, as on the source.) Re-reading the WRITTEN file: **26/26 primitives carry NORMAL, 0 zero-length, 0 non-unit, 0 unreferenced vertices, 0 zero-area faces.** Fresh Blender process: 26 objects, 1045089 triangles, 0 loose verts, no object without normals. |

**MUST-NOT-BREAK, re-verified on the OUTPUT:** `glass_probe` **clear / proven** ·
`Tyre_Rubber` baseColorFactor **0.047**, 100% coincident with source (untouched) ·
respray control rendered · Khronos validator **0 errors** · NORMAL on **26/26**.


---

## 2. WHAT WAS ACTUALLY BUILT, AND HOW

**Frame facts for this file, established by render and by geometry, not inherited.**
The TAIL is at **+X**, so **az 090 = straight rear**, az 035/125 the rear 3/4s, az 270
the front. Confirmed with one render before anything was built.

**`rear_v3.glb`'s node transforms are ALL EXACTLY IDENTITY** — max |world − local| =
**0.000000000** over all 22 nodes and every vertex. The coordinator's transform warning
is real but applies to `car_rebound`/`car_merged`, not to this file, so every measurement
here is already world-space. Checked rather than assumed, in five lines.

**Tyre contact heights on this file, world space, transforms applied:** RL **+11.5 mm**,
FL **+193.8 mm**, FR **+204.4 mm** — rear down, front up, nose UP. The brief's
"tyres y −0.3067 rear / −0.3241 front" is wrong for this file too. Grounding is another
gate's scope; recorded so no camera or section plane is derived from a 324 mm offset that
does not exist.

### 2.1 The panels

Each panel is a **robust tensor-product polynomial** fitted to the measured outer skin in
the panel's own parameter space, plus a **heavily low-passed residual correction** that
pulls it onto the real car. A low-order polynomial is C-infinity, so the panel is
curvature-continuous by construction and cannot carry the melt's waviness; the residual is
band-limited, so it adds fidelity without adding roughness. Both properties are measured
on the built grid, not asserted.

The parameterisation was chosen by measurement:
* **bumper — radial** `r(theta,y)` about the section's own pivot. It has to be: the bumper
  wraps to both flank tangents, where x stops being a function of (y,z).
* **hatch — direct `x(y,z)`**. Inside the tailgate outline the surface is rear-facing
  everywhere, so x is single-valued.

The tailgate is **two fitted patches sharing a single vertex row at the backlight sill**,
so the sill is a real crease and the door is still one closed component; one high-degree
fit across that knuckle would have rounded it off.

Every panel is a **closed pressing**, not a sheet: an outer Class-A skin, an inner skin
offset by the panel thickness and extended 14 mm beyond the outer outline, and a return
stitching them all round. The protruding inner skin is the **shut-line backstop** — a gap
with nothing behind it is a hole; a gap with a dark hemmed flange behind it is a shut
line. It carries its own material (`Shut_Line_Dark`) so a body respray cannot reach it.

The **plate recess is a pressing in the bumper**, produced by displacing the panel grid
through a smoothstep pocket applied to both skins so thickness is preserved. It is
therefore **NOT a separate node**, and there is deliberately no `Plate_Recess_Rear` in the
hierarchy: on a real car the recess is part of the bumper, and creating an empty node to
make an inventory look full is exactly what the brief forbids. `Plate_Rear` is a real
separate node. The recess is centred on the **bumper's own section centre** (z = −0.071),
not on z = 0, because the tail is sheared — a plate on the car's centreline would sit
71 mm off this panel's own middle.

### 2.2 The cut

The strip is a **face deletion only** — no vertex is moved anywhere in the file, which is
what makes a crack impossible when 25,369 carpaint vertices are coincident with interior
vertices. **72,012 faces removed.** The footprint is the rebuilt panel's own rasterised
coverage, so the cut can never exceed what gets covered again. Depth came from
measurement: the melt hatch and bumper are thin closed shells (a second surface within
20 mm on ~92% of rays, within 40 mm on 99.7%), so a 60 mm window takes the whole shell and
reaches nothing that should stay. Wheels are excluded — the bumper footprint sweeps to
theta ~±88 deg and without that exclusion it clipped 211 rear-tyre sidewall faces.

**The components-hidden render is the proof the cut is real** (`V4_CAVITY_az090/035`): with
the rebuilt parts hidden there is an open cavity through the tailgate and bumper into the
boot, with Gate 4's lamps left floating on the untouched quarters.

---

## 3. LEFT/RIGHT, MEASURED — the car is crooked and the rebuild says so

Gate 4's 150 mm shear is confirmed independently here: |z-| − |z+| runs **0.100–0.160 m**
at every height sampled across the tail.

| | source | rebuilt |
|---|---|---|
| tailgate lateral reach, worst asymmetry | 9 mm | **17 mm** |
| bumper lateral reach, shear | 133–148 mm | **134–199 mm** |
| tail depth at mirrored abs(z)=0.45, hatch | up to −42 mm | up to **−45 mm** |

The tailgate is near-symmetric because it lives *between* the lamps, where the body is not
sheared. The bumper is not, because it wraps to two corners that genuinely are 134–199 mm
apart in reach. **I did not straighten it.** De-shearing requires moving body vertices
across the coincident set and is a canon-level operation, out of this gate's scope.

**One place the rebuild made the asymmetry WORSE and I am not hiding it:** at the bumper's
lowest band (y = 0.26) the rebuilt +z reach is 0.665 against the source's 0.744 — the
panel falls **79 mm short** at its lower +z corner, so the shear reads 199 mm there
against the source's 148 mm. Cause: the outline's smoothed theta range plus the envelope
clamp. Legacy melt remains in that corner.

---

## 4. WHAT I WITHDREW OR CORRECTED MID-RUN

Nine things. Recorded because a withdrawn finding is worth more than a defended one, and
because four of these were caught only by a control.

1. **The layer probe sorted crossings by UNSIGNED radius**, so a hit on the car's NOSE
   (r = 3.4) sorted ahead of the tailgate (r = 0.75). It reported `carpaint` — a mesh whose
   faces stop at x = 1.369 — as the FIRST surface at the tail. Any strip depth chosen from
   that output would have been measured from the wrong end of the car.
2. **The radial parameterisation degenerated on the upper tailgate** (theta reaching ±91
   deg, pivot drifting forward to xc = 1.00, residual 18.5 mm rms / 45 mm max). That
   looked like a bad panel and was a bad coordinate system. Switched to physical (y,z):
   residual 4.9 mm rms, waviness 0.10 mm.
3. **I first described that corner error as "650 mm".** Wrong — I compared the corner
   against the panel's CENTRE value. Re-measured against the surface at the same (y,z) it
   is ~210 mm. Corrected here rather than quietly dropped.
4. **`verify_holes` v1 used `ray.intersects_any`** — "does this ray hit ANYTHING". A car
   has a cabin behind every outer panel, so a ray through a hole punched clean out of the
   tailgate still hits something. The selftest returned a **byte-identical** result to the
   real run, and that identity is what exposed it. Rewritten to compare first-hit DEPTH.
5. **The rewritten selftest still did not fire**, because it punched only the outer skin
   and the panel's OWN inner skin sits 14 mm behind — under tolerance. That is not a probe
   failure, it is the panel being a real pressing. Punching both skins made it fire
   (3.26% → 4.50%).
6. **`verify_lamps` v1 reproduced Gate 4's documented artefact.** It measured every unit
   along +x; run as a control on Gate 4's untouched file it reported the OUTER units
   **66.8% and 76.2% buried** on a file Gate 4 measured at 0%. A corner-wrap unit's
   outward direction is lateral, not +x. Rewritten to measure the hatch units against the
   rebuilt panel's exact fitted surface and to assert the outer units' seating from
   coincidence instead.
7. **The first assembly shipped 80,000 zero-length normals** and `gltf-transform validate`
   reported ERRORS while every render still looked fine. Each rebuilt node carried the
   panel's full vertex array (outer + inner skins) while its faces referenced only one, so
   the other half was unreferenced. Fixed with a finalise stage; the written file is now
   re-read and asserted, and the source scores 0/0/0/0 as a positive control.
8. **My coverage raster was DOTTED, not solid** — 6 mm cells against 7–9 mm grid node
   spacing — so faces landing between nodes were never tested and never cut. Cost:
   **172 legacy-melt faces survived inside the panel footprint and stood up to 48 mm proud
   of the rebuilt skin**, visible as dark shards on the lower tailgate at 3x zoom. Found by
   naming the owner of every proud face, not by guessing. Fixed with binary closing +
   hole-filling (solid interior without pushing the outline outward), plus a deliberately
   wider footprint for the proud test only. Melt under the hatch skin fell 3.49% → 1.92%.
9. **Two upload bugs.** A 22 MB part returned HTTP 400 once and the byte-identical retry
   returned 200 — retry added. And my own listing check summed EVERY `part_` object in the
   prefix, so it printed MISMATCH when two artefacts shared it; now filtered by basename.

---

## 5. HONEST RESIDUALS IN WHAT I DELIVERED

* **The tailgate is rebuilt up to y = 1.300 only.** Above that, and at the two upper
  D-pillar corners, the original melt survives as **`Rear_Upper_Legacy_Melt`** — a name
  chosen so nobody mistakes it for rebuilt work. The reason is measured, not a shortcut:
  at the +z upper corner the tail surface drops from x = 1.783 at y = 1.21 to x = 1.324 at
  y = 1.33, and there the skin map has **no data at all** (x stops being a function of
  (y,z) as the pillar sweeps forward). Extrapolating a panel into a region with no
  measurement is how the first build put that corner 210 mm inside the car. The panel is
  trimmed to where the measurement exists; the corner keeps its original geometry.
* **The tailgate's top edge is a flush join, not a shut line.** A horizontal seam across
  the upper tailgate would be a styling line the car does not have, so the new panel abuts
  the surviving geometry instead. It shows in the hole probe as a line of receded rays at
  y = 1.30 and is visible as a faint step in the 3/4 views.
* **The bumper's lower +z corner falls 79 mm short** (§3). Legacy melt remains there.
* **`Rear_Valance` below y = 0.23 is untouched torn melt**, inherited from the source and
  outside this gate's named scope. It is the ragged material under the bumper in every
  straight-rear view, and Gate 4 flagged the same thing.
* **Melt remains within 100 mm behind the bumper skin on 3.61% of rays** — almost all of
  it `Rear_Valance`, i.e. structure behind the bumper rather than a second bumper skin.
* **The rebuilt panels are flat-painted.** They are bound to the real `carpaint` material
  but with UVs pinned to a single measured body-paint texel (sRGB 225,28,31; 17x17
  neighbourhood std 0.58/0.16/0.00). Transferring the original UVs would have re-imported
  the **painted-on tail lamps** baked into that texture — the very thing Gate 4 replaced
  with real lamp solids. The consequence is that the rebuilt panels carry no baked
  texture detail, which on these two panels is correct and on a hero car would not be.
* **The hatch's edge-length CV is 1.29**, higher than the melt's 0.46. The grid is
  deliberately non-uniform (rows compress at the sill, columns land exactly on the
  aperture edges). It does not affect smoothness — measured waviness is 0.23 mm — but it
  is not a uniform quad field either.
* **The car is not grounded and not de-pitched** (front tyres ~194–204 mm up, rear ~11 mm,
  nose up). Another gate owns that; the merge operator must re-apply grounding on top of
  this file.
* **Vehicle identity is still unresolved.** CLAUDE.md records this test bed as a Toyota
  Yaris XP130 canonicalised to Golf length; no dimension here should be read as a
  spec-correct anything.

---

## 6. EVIDENCE

Prefix `car-meshes/staging/rear_v2/`.

| path | what |
|---|---|
| `glb/rear2_v4.glb.part_000..003` + `glb/MANIFEST_rear2_v4.glb.txt` | the delivered car, 66,485,700 B |
| `REAR2_SHEET.jpg` | captioned 8-tile evidence sheet, azimuth convention printed on it |
| `evidence/V4_CAVITY_az090/035.png` | **the cut proof** — components hidden, open cavity |
| `evidence/V4_shaded_az090/035/125.png` | production-style views |
| `evidence/V4_matid_az090/035.png` | component separation in the owner's colours |
| `evidence/V4_clay_az090/035.png` | surface truth, 0.000% clipped |
| `evidence/V4_blue_az090/035.png`, `V4_red_az090.png` | respray controls |
| `evidence/V4_glasson_az090.png` | worker-style forced transmission on glazing |
| `evidence/BASE_*.png` | the same cameras and exposure on the input |
| `measurements/*.json` | every number in this report |
| `pipeline/machine/rear2/*.py` | every stage, committed on `claude/lovable-connection-ki7jch` |

Nothing was published and nothing customer-visible was changed. The input was copied,
never modified in place.

**THE COMPLETE VEHICLE REMAINS NOT PRODUCTION-READY.** This gate closes one named gap —
the hatch and rear bumper surfaces — on a car whose front, flanks, roof, valance,
glazing optics, wheels, grounding and identity are all still open, and whose body is
crooked by 150 mm.

---

## 7. THE RESPRAY CONTROL, MEASURED PER COMPONENT

Masks taken from the matID pass (flat emission, 1 sample, AA off), so the pixel sets are
per-COMPONENT and not per-region; the same pixels are then sampled in the body-red and
body-blue shaded renders, which share a camera and an exposure. Both tiles verified
unclipped first (0.578% and 0.541% of car pixels).

| component | px | body RED | body BLUE | max channel delta |
|---|---|---|---|---|
| `Hatch (cyan)` | 90855 | [223.2, 58.1, 60.0] | [87.3, 117.8, 208.0] | **148.0** |
| `Bumper_Rear (yellow)` | 75114 | [208.8, 60.6, 62.4] | [82.4, 110.5, 194.4] | **131.9** |
| `Tail_Lens_L (magenta)` | 8846 | [149.5, 62.4, 66.8] | [147.8, 63.5, 70.4] | **3.5** |
| `Tail_Lens_R (orange)` | 6418 | [170.0, 66.9, 72.3] | [168.2, 68.0, 75.8] | **3.5** |
| `Glass_Backlight (dk blue)` | 49335 | [61.3, 63.2, 67.6] | [59.4, 63.7, 69.6] | **1.9** |
| `Plate_Rear (white)` | 9825 | [229.7, 228.8, 227.4] | [228.9, 229.0, 228.1] | **0.8** |
| `Rear_Upper_Legacy_Melt` | 23935 | [226.2, 125.1, 127.0] | [124.2, 144.6, 217.7] | **102.0** |

**Read it this way.** The two REBUILT PAINT panels move fully with the respray — the
tailgate's R−B flips from **+163.2 to −120.7** — so they are genuinely bound to the
`carpaint` material and a colour variant will paint them. **Gate 4's tail lamps hold their
red at a maximum channel delta of 3.5/255**, the identical figure Gate 4 measured against
its own surface, so nothing this gate did loosened them. The rebuilt glazing pane (1.9)
and the rebuilt number plate (0.8) do not move either. This is the control that painted-on
components can never pass.

## 8. SHUT LINES AND CLEARANCES, MEASURED

Closest approach between components (3-D nearest neighbour over face centres):

| seam | closest approach |
|---|---|
| `Hatch <-> Rear_Quarter_L` | **6.68 mm** |
| `Hatch <-> Rear_Quarter_R` | **11.82 mm** |
| `Hatch <-> Bumper_Rear` | **8.45 mm** |
| `Bumper_Rear <-> Rear_Quarter_L` | **12.21 mm** |
| `Bumper_Rear <-> Rear_Quarter_R` | **11.98 mm** |
| `Hatch <-> Rear_Upper_Legacy_Melt` | **6.01 mm** |
| `Glass_Backlight <-> Hatch` | **2.93 mm** |

No two components touch or interpenetrate. The glass-to-frame figure of 2.93 mm is the
designed standoff (brief phase 5 asks 2-3 mm) and it lands where it was aimed.

## 9. EXPOSURE — every render carries its own number

Gate 4's first tiles clipped 42.58% of car pixels and a clipped render is not evidence.

| render | car px % | clipped % of car | mean luminance |
|---|---|---|---|
| `V4_clay_az090` | 23.00 | **0.000** | 162.1 |
| `V4_clay_az035` | 37.52 | **0.000** | 176.1 |
| `V4_CAVITY_az090` | 24.94 | **0.000** | 92.3 |
| `V4_shaded_az090` | 25.29 | 0.578 | 96.6 |
| `V4_shaded_az035` | 38.14 | 4.079 | 97.6 |
| `V4_shaded_az125` | 35.90 | 0.398 | 96.3 |
| `V4_blue_az090` | 25.30 | 0.541 | 108.7 |
| `V4_red_az090` | 25.31 | 0.532 | 103.6 |
| `V4_glasson_az090` | 25.29 | 0.575 | 93.9 |
| `V4_matid_az090` | 25.33 | 59.858 | 175.4 |

The clay and cavity passes — the two that judge SURFACE and STRUCTURE — are **0.000%
clipped**, so nothing in them is hidden in a blown highlight. The matID figure is not a
defect and must not be read as one: a label pass is flat emission in saturated palette
colours, several of which are 255 in a channel by definition. (The v3 matID read 8.2%
purely because its palette was hash-generated and unsaturated; the model did not change.)

## 10. THE PANELS ARE CLOSED PRESSINGS — proved by topology, not by claim

Each rebuilt panel is split into two NODES by material (`Hatch` is the Class-A outer skin
on `carpaint`; `Hatch_Inner` is the inner skin, the perimeter return, the aperture return
and the hemmed flange, on `Shut_Line_Dark`). That split is anatomically what a real
tailgate is — an outer skin and an inner panel — and it is what lets a body respray reach
the skin and not the shut line. Welded back together at their shared boundary:

| panel | verts | faces | watertight | boundary edges | Euler characteristic |
|---|---|---|---|---|---|
| `Hatch` + `Hatch_Inner` | 21,834 | 43,668 | **True** | **0** | **0** |
| `Bumper_Rear` + `Bumper_Rear_Inner` | 33,592 | 67,180 | **True** | **0** | **2** |

The Euler numbers are an independent check on the topology nobody had to trust me for:
**chi = 0 is a genus-1 surface — a closed panel with exactly ONE hole**, which is the
backlight aperture, and **chi = 2 is a closed sphere-topology solid**, which is a bumper
with no aperture at all. Both are what they should be, and a stray hole or an unclosed
return would have shown up in either number.

All eight of Gate 4's lamp components remain individually watertight in the shipped file.
