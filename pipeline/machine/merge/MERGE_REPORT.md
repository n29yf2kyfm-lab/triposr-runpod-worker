# MERGE OPERATOR — Gate 6 stance onto the Gate 7+8 material-rebound car

**Deliverable** `car-meshes/staging/merge/glb/car_merged.glb` — 28,703,236 bytes,
sha256 `09897d2037a4566bd447f1fc80fb07b4d818c757e756760bfdbcb1723ae25e8d`,
stored as 2 parts + `MANIFEST.txt`, re-downloaded from the bucket and compared
byte-for-byte against the local file: identical.

---

## 1. The four tyre bottoms, and the four Gate 7+8 properties

| tyre bottom (world y) | value |
|---|---|
| FL | **+0.000000 mm** |
| FR | **−0.000000 mm** |
| RL | **−0.000000 mm** |
| RR | **−0.000000 mm** |

Tolerance was ±0.5 mm. Measured from the written GLB by composing node
transforms, not from the operator's plan. Before the merge those same four
tyres were at +183.2 / +189.6 / +0.3 / +14.7 mm.

| Gate 7+8 property | before | after | verdict |
|---|---|---|---|
| `glass_probe` | clear / proven, flat_shell false, alpha_shell false | identical | **SURVIVED** |
| tyres black | `Tyre_Rubber` baseColor 0.027 | unchanged; blue respray moves it by 1.1–1.4 sRGB | **SURVIVED** |
| red/blue respray control | — | carpaint moves 175–215 sRGB; tyres 1.1–1.4, glass 5.7–21.4, rims 5.6–7.9, tail lamps 0.1–0.2 | **SURVIVED** |
| Khronos validator | 0 errors, 0 warnings, 2 infos, 90 hints | **0 errors, 0 warnings, 2 infos, 90 hints** | **SURVIVED** |

Plus: NORMAL accessor on **30/30** primitives, 0 zero-length normals (0 before,
0 after); material table diff **empty**; primitive→material binding diff
**empty**; all 30 node names unchanged.

---

## 2. Correction to the brief — the base was never 324 mm underground

The brief states the base's tyre bottoms are y = RL −0.3067 · RR −0.3067 ·
FL −0.3233 · FR −0.3241, "so the contact plane is ~324 mm below y=0 AND the
nose sits ~17 mm low."

**Those four numbers are the wheel meshes' node-LOCAL accessor minima.** The
twelve wheel nodes in `car_rebound.glb` carry real node translations
(`Wheel_FL_*` at [−1.2707, 0.5065, −0.6515], and so on). Composed to world:

```
node            local min y   nodeT.y    WORLD min y
Wheel_FL_Tyre     -0.3233    +0.5065      +0.1832
Wheel_FR_Tyre     -0.3241    +0.5137      +0.1896
Wheel_RL_Tyre     -0.3067    +0.3070      +0.0003
Wheel_RR_Tyre     -0.3067    +0.3214      +0.0147
```

local + nodeT reproduces the brief's numbers exactly. The car was not under the
floor; **the front tyres were 183 and 190 mm IN THE AIR**, which is Gate 6's own
recorded baseline (+197.7 / +188.5 / +22.1 / +8.1 mm, with Gate 6's mirrored
L/R labels). This is the trap the brief itself warns about — "measure from
TRANSFORMED VERTICES, never from a node translation" — applied in the other
direction, and it changed what the operator had to do: the fix was a 4.1° pitch
plus a drop, not a 324 mm lift.

Confirming the frame: the base's world AABB is **4.282490 × 1.455398 ×
1.788713**, identical to six decimals to Gate 6's recorded `aabb_before`. The
base sits in Gate 6's input frame, so Gate 6's recorded matrix applies directly.

---

## 3. Route chosen: (B) re-apply the operations

Route A (transplant Gate 6's wheel geometry) was rejected before any code:

* Gate 6's wheels were **cut out of a fused shell** and are four-material
  mixtures (`Rim_Alloy`, `Tyre_Rubber`, `carpaint`, `interior` — from its own
  `op_wheels.json`). The base binds `Brake_Disc` / `Rim_Alloy` / `Tyre_Rubber`
  to three clean nodes per corner. Rebinding a mixture onto that scheme is the
  "silently opaques the glazing" class of net loss, done by hand, with no check
  that could prove it right.
* Gate 6's shippable file is **texture-reduced** (its 63 MB original 413'd).
* It does not generalise, and generalising is the point — Gate 3 v7's output
  needs the same treatment.

**What I would have seen if route B were wrong:** the base's wheels would not
have been separable, and scaling a wheel welded into the body shell needs a
face-level cut with duplicated shared vertices — Gate 6's hardest step and where
it shipped 1,980 validator errors. Measured before committing: twelve separate
wheel nodes, no vertex shared with the body. The cut route B would have needed
does not exist here, so route B was not merely safer, it was free.

**How the material layer is preserved — by construction, not by care.**
`glb_io.py` edits only the bytes behind the POSITION and NORMAL accessors and
rewrites those accessors' min/max. Materials, extensions
(`KHR_materials_transmission` / `_ior` / `_clearcoat` — the three that make this
car's glazing read clear/proven), mesh names, node names, bindings and index
buffers are never rewritten. The operator additionally **refuses to write** if
the material table or the binding table diffs non-empty.

---

## 4. Pose: yaw / pitch / roll and the residual

Applied: Gate 6's recorded rigid transform, yaw **+2.267685°**, pitch
**+4.119073°**, roll **+0.441308°**, translation
(−0.000469, −0.101609, +0.011872). Orthogonality error 1.1e−16, determinant
1.000000000.

Residual, measured on the OUTPUT from the **body's own symmetry plane** — body
evidence only, so it cannot be circular with the wheel work:

| | before | after | method |
|---|---|---|---|
| yaw | −2.3648° | **−0.2287°** | lateral midpoint of the body silhouette per length slab, trimmed LSQ |
| roll | −1.9616° | **−0.2685°** | same, per height slab |
| pitch | +4.119° applied | **0 by construction** | each wheel is grounded independently onto y=0, so a contact-plane fit reads back its own input. There is no independent horizontal reference on this body; I will not manufacture one. |

My pre-pose yaw estimate (−2.3648°) agrees with Gate 6's independent
`_sym_plane` (−2.2677°) to 0.10°, from a different implementation.

---

## 5. Rigidity

* 20,000 random vertex pairs over the 615,395 **non-wheel** vertices:
  max |d_before − d_after| = **0.197 µm**, rms 0.040 µm (float32 rounding).
* Face count **985,227 → 985,227**, per-node diff empty.
* Published dims: L 4.27929 m (**−0.11%** vs 4.284), height above ground
  1.44766 m (**−0.57%** vs 1.456). Width excl. mirrors 1.74667 m (−2.37%) — an
  **inherited** deviation: Gate 6 measured the same body at 1.61/1.66 m across
  the arches against 1.789 published. No stance operator can change it.
* L/W/H versus **Gate 6's own delivered car: max delta 0.0000 mm**, and the
  merged body's median nearest-neighbour distance to that file is **0.0000 mm**
  (mean 0.456 mm) over 20,000 sampled body vertices. The pose transferred
  exactly.

The wheels are reported separately **because they are not rigid**: each is a
radial scale of 0.97567–1.02532 with axial scale 1.0 and determinant > 0.
Calling that rigid would be a comfortable wrong number.

---

## 6. What I did NOT do, and why: the wheel axes are not squared

Gate 6 rotated each wheel to zero toe and camber. I do not, and this is the one
place where I deliberately carry less than Gate 6 did. Gate 6's own acceptance
graded every toe and camber **NOT MEASURABLE**, so nothing certified is lost.

Evidence, from `merge_calib.py` (injection ladder through this package's own CLI
path, 9 rungs from −2.0° to +2.0°, on a real written GLB each time):

| corner | toe slope | camber slope | ladder rms | null drift | 4-estimator spread |
|---|---|---|---|---|---|
| FL | +0.770 | +0.734 | 0.065° / 0.132° | 0.109° | 9.20° |
| FR | **−0.735** | **−0.928** | 0.113° / 0.038° | 0.000° | 11.15° |
| RL | +0.967 | +0.820 | 0.015° / 0.060° | 0.049° | 9.63° |
| RR | **−0.400** | **−0.461** | 0.909° / 0.362° | 0.377° | 2.90° |

**On two of the four corners the response slope is NEGATIVE** — the probe
reports an injected rotation as a rotation the other way, so squaring by the
reported error drives the wheel further from square. The four independent
estimators of the same axis (tread cylinder fit, brake-disc vertex PCA,
brake-disc area-weighted face normals, rim PCA) disagree by up to **11.15°**, and
a contact-patch estimator was incoherent across thresholds.

This is not theoretical. I built the squaring version first: it left residual
toe of +1.287 / +0.636 / +0.057 / **−1.132°**, i.e. RR overshot and **changed
sign**, exactly as the −0.400 slope predicts. `--square-axes` keeps that
behaviour available; it is off by default.

The same reasoning removed the axial (width) equalisation: the width measure is
the lateral span of the tread band about the *fitted* axis, so an axis error of
δ inflates it by 2R·sin δ — 18 mm at 1.7°, which is the whole size of the 18 mm
spread it would be correcting. `--equalise-width` is available and off.

**Track** likewise uses each axle's own measured mean rather than Gate 6's
delivered numbers: Gate 6's pass 1 placed its RL hub at z=+0.74109 and its pass 2
then *measured* that same wheel at z=+0.697305 — its own two passes disagree by
43.8 mm on that one quantity. Copying a target coordinate is only valid where the
two instruments agree about where the wheel is now. `--track-mode gate6` copies
the literal numbers; the report always carries both.

---

## 7. Checks, each proven able to fail

`verify_merge.py --controls` runs every check twice — once on the real output,
once on a copy with a defect injected. Gate 6 shipped an arch-intersection test
that was empty by construction and reported PASS for weeks.

| check | injected defect | real | injected | control |
|---|---|---|---|---|
| ground | FL tyre lifted 3.0 mm | PASS | FAIL | **PASS** |
| rigidity | Body_Shell scaled ×1.001 | PASS | FAIL | **PASS** |
| glass | glass forced OPAQUE, transmission removed | PASS | FAIL | **PASS** |
| materials | node `Glass_Rear` renamed | PASS | FAIL | **PASS** |
| normals | NORMAL accessor removed from `Mirror_L` | PASS | FAIL | **PASS** |
| pose | whole car yawed 1.5° | PASS | FAIL | **PASS** |

`ALL_OK: true`, `CONTROLS_OK: true`.

`selftest.py` proves the reusability claim rather than asserting it: it builds a
**v7-shaped input** out of the real base (fascia nodes renamed to
`Fascia_Front_v7` / `Grille_Front_v7` / `Headlamp_{L,R}_v7`, the grille rebound
to a brand-new material) and runs the operator on it. The wheel plan comes out
**identical to the reference run, worst delta 0.000e+00** — a front rebuild
cannot perturb a wheel, because corners are found from node geometry and the
pose is a recorded matrix. The renamed nodes and the new 12th material survive,
all four tyres ground, and the three refusal paths (instanced mesh, corner label
disagreeing with geometry, missing NORMAL) each stop the operator.

---

## 8. Two things I corrected mid-run

1. **The respray control initially reported four FAILs** — `glass`,
   `Arch_Liner`, `Trim_Black`, `Interior_Plastic` appeared to take the paint.
   Two separate artefacts, both identified and then *tested* rather than
   assumed. Glass was optical: with diffuse bounces off it stopped moving
   (27.8 → 7.9). The other three were **anti-aliasing bleed at the mask edge** —
   the matID pass is rendered with the filter off so each pixel carries one
   label, while the beauty renders are filtered, so boundary pixels of thin
   regions are mixtures. The prediction was written first (thin regions only)
   and it held: the three that "moved" have 68–100% of their mask in the
   2-pixel border, the ones that did not have 14–36%. Eroding the mask by 2 px
   resolves all three under full lighting.
2. **`merge_calib.py`'s conclusion line was pre-written as "the ladder is
   faithful"** and the data said 0.77 / 0.73, then −0.40 on RR. The conclusion
   is now computed from the numbers, and a negative slope is named as such
   instead of being filed under "attenuated".

---

## 9. Honest open items

* **Contact patches are small**: 2 / 5 / 11 / 5 tyre vertices within 0.5 mm of
  the ground (7 / 10 / 20 / 11 within 1 mm; 30 / 51 / 66 / 72 within 5 mm). The
  tyre is 4.0–4.8 mm rms out of round, so it touches near a point. Gate 6's
  104–156 came from also scaling widths, which I declined for the reason above.
  Gate 6's criterion was ≥3 verts; FL is at 2 at the tightest tolerance and
  clears it at 1 mm.
* **`Arch_Liner` dips 4.59 mm below the contact plane.** Inherited, and the
  documented "the ground plane is not the lowest scene vertex" condition — Gate
  6's delivered car has an interior shell 10.12 mm under. Not introduced here.
* **The front fascia is still melt.** That is Gate 3 v7's job; this operator is
  built to be re-run on its output.
* Absolute toe and camber remain **NOT MEASURABLE** on this geometry. The
  numbers in the transform table are recorded for continuity, not certified.

---

## Files

`car-meshes/staging/merge/`

| path | what |
|---|---|
| `glb/car_merged.glb.part000` + `.part001` + `MANIFEST.txt` | the deliverable |
| `MERGE_REPORT.md` | this report |
| `TRANSFORM_TABLE.txt` | the full per-corner table with achieved numbers |
| `MERGE_REPORT.json` | the operator's own machine-readable record |
| `VERIFY.json` | acceptance battery + negative-control matrix |
| `CALIB_{FL,FR,RL,RR}.json` | injection ladders, null controls, 4-estimator spreads |
| `CONTROL_NUMBERS.txt` / `_NOGI.txt` | respray control, full lighting and direct-only |
| `gltf_validate_car_merged.json` / `_base.json` | Khronos reports |
| `BEFORE_AFTER.png`, `GROUND_CROPS.png` | matched-camera before/after |
| `views/` | the raw matched renders (base, merged, blue control, matID) |

Tools: `pipeline/machine/merge/` on `claude/lovable-connection-ki7jch` —
`glb_io.py`, `wheel_probe.py`, `merge_op.py`, `verify_merge.py`,
`merge_calib.py`, `merge_views.py`, `control_numbers.py`, `sb_chunk.py`,
`selftest.py`.

**Re-run on the v7 output:**

```
python3 pipeline/machine/merge/merge_op.py V7.glb OUT.glb \
    --pose-mode record --pose-json op_pose.json --report R.json
python3 pipeline/machine/merge/verify_merge.py V7.glb OUT.glb \
    --merge-report R.json --controls
```
