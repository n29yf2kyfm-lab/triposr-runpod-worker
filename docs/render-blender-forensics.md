# Render + Blender Stack — Forensic Analysis
**Owner document · 2026-07-15 · every line of `render/handler.py` (615) and all
18 scripts in `pipeline/blender/` (2,450 lines) read and cross-checked against
observed behaviour (Golf/Scirocco runs, the "paint fuk" incident, the 95-asset
quarantine sweep).**

Motivating problem: renders that pass the gates still "look shit" to the
owner's eye. This report separates what actually degrades the picture from
what is merely ugly code, and ends with prioritised fixes.

---

## 1. The single biggest visual defect: two recolour philosophies, the worse one serves

- `render/handler.py:299-304` — the serving renderer's recolour **unlinks the
  Base Color texture and sets a flat colour** on every detected body material,
  then forces `Metallic 0.6`. All baked detail (shutlines, grille shading,
  panel variation, badges baked into the atlas) is destroyed in that node cut.
  On material-separated library models this is survivable; on anything where
  the "body" material carries real texture detail it produces the flat,
  ragged, toy-like paint the owner has rejected repeatedly.
- `pipeline/blender/generic_recolour.py:22-30` — the **proven** method
  (multiply Mix node inserted before Base Color: shading and detail survive,
  exports as `baseColorFactor`). It exists, it shipped the Golf colour
  variants, and the render worker never uses it.

**Root cause chain:** recolour was built for material-separated GLBs → flat
repaint looked fine there → the same code path was later fed fused/generated
shells → texture unlink turned baked detail into flat patches ("The paint
fuk") → fixed offline with multiply-tint, but the serving path still carries
the destructive version. Confidence: high (~90%) — both code paths read in
full, incident reproduced and fixed this session.

**Fix (F1):** port the multiply-tint node insertion into `_render()`. Rule:
paint-named material → flat repaint allowed (clean OEM-style respray);
anything else → multiply-tint only. This encodes the operational rule in code
instead of in memory.

## 2. Paint finish is one-size-fits-all

`render/handler.py:304-308`: every recoloured body gets `Metallic 0.6`,
`Roughness 0.11`, `Coat 1.0` — regardless of colour. Solid white, solid
black, metallic silver and pearl white all render as the same semi-metallic
lacquer. The OEM paint database (`platform/paint/oem_paint_db.csv`) carries a
`FINISH` column (solid/metallic/pearlescent) that nothing reads.

**Fix (F2):** map FINISH → shader params (solid: metallic 0.0–0.1, rough
0.18; metallic: metallic 0.75, rough 0.10 + coat; pearl: coat colour tint).
Cheap, and it is exactly the "premium paint" gap the owner keeps seeing.

## 3. No guard where the operational rule says "never"

`_choose_body()` (`render/handler.py:155-177`) falls back to an area rule:
any non-excluded material ≥55% of the biggest area gets repainted. On a fused
single-material shell (every generated asset, most scans) that floods the
whole car — glass, lights, wheels — with body colour. We *know* this
(the 95-asset quarantine, the recolour hard rule in project memory), but the
code does not: the worker will still happily flood-paint a fused shell if a
caller asks. The `mat_audit` mode exists precisely to measure this and is not
consulted on the render path.

**Fix (F3):** in `_render()`, if the chosen set contains no paint-named
material AND covers >85% of total area, refuse flat repaint (fall back to
multiply-tint or return `"recolour": "skipped_fused_shell"`). Turns a
memory-rule into a machine-rule.

## 4. Render consistency defects (catalogue-visible)

- **Backdrop flips with paint colour** (`handler.py:399-424`): dark colours
  trigger `use_bright` → the raw HDRI room is visible behind the car, while
  light colours get the dark graded backdrop. Catalogue pages mix two
  different studios. `studio=True` already solves this (dark backdrop + bright
  reflections) but is opt-in. **Fix (F4): make `studio` the default** for
  catalogue/turntable renders; keep `bright` for debugging.
- **Plate can jump ends mid-turntable** (`handler.py:472`): the plate is
  placed on whichever end is *closest to the camera*, decided per frame. In a
  360° sweep the plate teleports from nose to tail as the camera crosses the
  side. Fix: caller passes the end once (`plate_end: "front"|"rear"`), infer
  only as fallback.
- **Glass thresholds disagree with QC**: render classifies alpha < 0.55 as
  glass (`handler.py:133`); the audit gate accepts alpha < 0.9
  (`asset_audit` G2); `cabin_assembly` makes glass at alpha 0.72. A
  third-party glass material at alpha 0.6–0.9 with a non-glass name passes
  the audit as glass and is then *repainted body colour* by the renderer.
  One constant, one place (see §7).
- **Lights don't follow the camera azimuth**: key/rim/fill are fixed in world
  space around the bbox. Fine for the default 40° hero and consistent for
  turntables (deliberate), but rear-quarter frames (az 150–210°) are lit by
  the rim light only — the darkest, noisiest frames in every sweep. Optional
  fix: rotate the light rig with `az` for hero shots, keep fixed for
  turntables.

## 5. Silent Blender-4.1+ regression: the smoothing fix that doesn't export

`clean_export.py:53-57` and `golf_finish.py:40-42` both do
`o.data.use_auto_smooth = True` in a try/except. That attribute was **removed
in Blender 4.1** — so on our 4.2 builds the try silently fails:

- `golf_finish.py`: non-paint objects (glass, trim, lights) lose their smooth
  angle split entirely → soft blobby edges. Paint objects survive only
  because they separately get a WeightedNormal modifier.
- `clean_export.py`: worse — the fallback adds a WeightedNormal modifier but
  exports with `export_apply=False` (to preserve hierarchy), and the glTF
  exporter ignores unapplied modifiers. **The advertised smoothing fix is
  silently absent from every clean_export output produced on Blender ≥4.1.**

**Fix (F5):** replace with the 4.1+ API (`bpy.ops.object.shade_auto_smooth`
or the "Smooth by Angle" modifier) and, in clean_export, either apply that
one modifier before export or use custom split normals. This is the same
failure class as the Hunyuan build defects: silent `try/except` around an API
that moved. Institutional rule already exists — builds/exports must verify
their own effect.

## 6. Copy-paste drift: three wheel detectors, three paint-name lists, two axis conventions

The same heuristics are re-implemented with different constants:

| Heuristic | cabin_assembly | prop_fix | wheel_replace | render/handler |
|---|---|---|---|---|
| Wheel cylinder radius | R×1.18 | R×1.35 | R×1.10 | — |
| Wheel height cut | 0.42·H | 2.1·R | 2.05·R | — |
| Length axis | auto (argmax) | auto | **assumed y** | auto (bbox) |
| Paint names | — | — | — | `_PAINT` regex |

Plus: `golf_finish`/`fill_gaps`/`bridge_gaps` hardcode
`{"Paint_Color","Car_Paint"}`; `generic_recolour` uses regex
`paint|body|carpaint|lack|carros`; the render worker uses a third, larger
regex. `add_plates.py` *asserts* y-is-length (`add_plates.py:39`);
`wheel_replace.py` assumes it without asserting — both break on an x-length
model that `prop_fix`/`cabin_assembly` would handle fine.

**Root cause:** each script was written in a separate incident under time
pressure, none imports from a shared module. This drift is why "every new
model breaks something": a model that passes one script's geometry
assumptions hits a sibling script with different constants. Confidence ~85%.

**Fix (F6):** extract `pipeline/blender/car_common.py`: `detect_axes()`,
`detect_wheel_arches()` (one histogram implementation, one set of constants),
`PAINT_RE / GLASS_RE / WHEEL_RE` (single source, imported by the render
worker too), glass alpha threshold. Mechanical refactor, zero behaviour
choices left per-script.

## 7. Known-fragile geometry (accepted, documented)

- `prop_fix.py`: width is robust (lowband percentile, audit-matched) but L
  and H still come from raw min/max — one stray vertex skews the target
  ratios the script then "corrects" to. Also: wheel verts translate rigidly
  while the body stretches → a shear step at the arch lip for large
  corrections (invisible at k≈1.05, visible at k≥1.2). And only the FIRST
  mesh object is processed — silently wrong on multi-object GLBs.
- `cabin_assembly.py`: beltline 0.60·H, tumblehome 0.84, screen bands — tuned
  on hatchbacks; SUVs/pickups will misclassify. Already flagged in the Alam
  3D report; the majority-vote cleanup pass remains unbuilt.
- `bridge_gaps.py`: the shipped gap method; sound (skin never moves), but the
  per-object `seam_dark` material duplicates on multi-panel models.
- `qc_audit.py`: flipped-shell detection uses local coordinates — an object
  with negative scale in its transform would false-flag; glTF import usually
  bakes transforms so low risk.

## 8. Dead weight and boobytraps to fence off

| Script | Status | Danger if run naively |
|---|---|---|
| `automotive_refinery.py` | deprecated by its own verdict header | **Stage 3b clears ALL materials on every mesh** and applies one paint — glass/trim destroyed. The "keep baked texture if no hex" promise in the comment is *not implemented*. |
| `build_golf.py` | proven-negative experiment (kept as documentation) | none — but it's 191 lines someone could mistake for production |
| `fix_bmw5.py` | one-off (hardcoded `Object_9..20`) | wrong objects recoloured on any other GLB |
| `palette_recolour.py` | one-off; UV point-sampling under-covers big palette patches on high-res atlases | patchy recolour |
| `build_interior_gte.py`, `process_candidate.py`, `rig_panels.py` | experimental stage-2 tooling, honest headers | `process_candidate` **joins all meshes** — destroys the object/material structure of any multi-part input |

**Fix (F7):** move one-offs to `pipeline/blender/attic/` (or add a loud
`DEPRECATED — do not run on library assets` first line) so the production set
is exactly: `cabin_assembly, prop_fix, generic_recolour, wheel_replace,
bridge_gaps, fill_gaps, clean_export, add_plates, golf_finish, qc_audit` +
`make_plate_textures`.

## 9. What is genuinely good (keep, don't churn)

- Percentile framing (`handler.py:331-350`) — stray verts can't blow up the
  camera; floor at true z-min so wheels never float.
- Scale normalisation to ~4.5 units before any light/DOF math.
- `_norm_name()` + property-based glass/emission detection — survives
  multilingual, underscore-separated material names.
- Paint-named-authoritative body choice with the 15% plausibility floor
  (`handler.py:170`) — the Golf/A1 counter-examples in the comment are real
  and the rule is right.
- `mat_audit` render-free mode — the right measurement tool; it just needs to
  be consulted (F3).
- `bridge_gaps`' invariant (outer skin never moves) and `clean_export`'s
  non-destructive contract — correct philosophies, worth extending.
- AgX + graded backdrop + 4-light rig: the studio look itself is not the
  problem; consistency of its application is (F4).

## 10. Priority order (highest visual ROI first)

1. **F1 multiply-tint in the render worker** — kills the flat-paint failure
   class at serve time. (~40 lines, port from generic_recolour.)
2. **F2 FINISH-aware shader params** — solid/metallic/pearl stop looking
   identical; uses data we already ship.
3. **F4 studio default + plate_end** — one consistent catalogue look; no
   teleporting plates on turntables.
4. **F3 fused-shell guard** — the "never flood-paint" rule becomes code.
5. **F5 Blender 4.1+ smoothing fix** — clean_export/golf_finish actually do
   what their headers claim again.
6. **F6 car_common.py extraction** — ends the constant drift; makes every
   later fix land once.
7. **F7 attic the one-offs** — removes the boobytraps.

Risks if ignored: F1/F2 are the direct feeders of the owner's "look shit"
verdicts on recoloured renders; F5 quietly degrades every cleaned export on
current Blender; F6 guarantees the next new bodystyle breaks a random subset
of scripts again.
