# skin/ — the "double skin" on the Class-A Golf, diagnosed and repaired (2026-08-21)

## THE BRIEF'S DIAGNOSIS WAS WRONG, AND THE FIX IT ASKED FOR MADE THE RENDER WORSE

The task was stated as: *7.0% of faces sit in a near-coincident, opposite-facing
pair (0.54 m²); it renders as dark/red speckle across the bonnet, roof and flanks
(z-fighting between the two shells); delete the inner sheet of each pair.*

Both halves of that are false on `car_rebound.glb`, and the second half is
expensive to act on. What is actually there is **one triangulated surface whose
triangles are partitioned between materials, with a speckled partition**.

### The evidence chain, in the order it was produced

1. **The anti-parallel census is real but is not the speckle.** An independent
   detector (`dbl.py`, three negative controls: single sheet 0.000%, doubled-at-
   0.2 mm 100.000%, real 5 mm thin solid 0.000% at 0.5 mm / 100% at 6 mm) measures
   **6.438% of faces / 0.779 m² at 0.25 mm** on `car_rebound.glb` — close enough to
   the brief's 7.0%/0.54 m² to be the same phenomenon. Rendering that exact face
   set in magenta put **nothing on the bonnet or the roof**, where the speckle is
   worst. 50% of it is `Interior`↔`Interior`, deep inside the cabin, invisible.
2. **A deterministic mesh-ID pass** (flat emission, 1 sample, AA off, 0 bounces —
   the `bl_label_render` rule; a point-sampled shaded render cannot do this)
   showed the bonnet/roof speckle is a *different mesh winning the pixel*:
   `Interior` takes **10.1% of roof pixels and 9.0% of bonnet pixels** while taking
   **0.07% of the flank**. That is the profile of speckle, not of a panel.
3. **Recolouring `Interior_Plastic` green** turned the speckle green. Confirmed by
   eye and by pixel count.
4. **`Body_Shell` rendered alone**, with a Backfacing→magenta shader, is *massively
   backfacing across the bonnet and roof* — i.e. the paint mesh is **perforated**
   there and we are seeing the inside of its far side. It carries **78,218 boundary
   edges** after welding.
5. **The geometry is sound.** A clay render (one grey diffuse, the file's own
   geometry and its own authored normals, same lights) is **clean**. Normals are
   not the cause either: `Body_Shell` has **14 flipped faces of 190,385 (0.01%)**,
   and clearing every authored split normal changes nothing.
6. **The two meshes are one surface.** Exactly **1** `Interior` face is a duplicate
   triangle of a `Body_Shell` face. **23,232** `Interior` faces have all three
   vertices *exactly* coincident with `Body_Shell` vertices, and **92.4%** of those
   share an edge with a `Body_Shell` **boundary** edge — they sit *in* its holes,
   on its rim.

**So deleting them would punch ~30,000 real holes in the bonnet and roof.** That
was not left as an argument: `deskin.py` was built, it deleted 3.71 m² by exactly
the rule the brief specifies (ray order to pick the loser, an outward field from
visibility to pick the side), and the matched render got **worse** — bonnet
5.34% → 6.41% dark specks, roof 5.55% → 6.28%. It is kept in this directory as the
record of a route that was tried and measured, not as a tool to run.

## THE REPAIR: `relabel.py`

Absorb speckled label islands into the material that surrounds them, by editing
**only the glTF index data**. Positions and normals are copied byte for byte, so
face count, area, extents and silhouette are unchanged *by construction* — and the
triangle multiset is provably identical (`hole_test.py`).

Selection is measured, not chosen: same-material connected components on the
**welded** surface (adjacency crosses mesh boundaries because the meshes share
exact vertex positions). Dark components split cleanly into ~12.6k islands of
≤ 0.03 m² and a handful of real parts of ≥ 0.26 m² — a **9× gap**. Default
thresholds sit inside it: area < 0.002 m² and ≥ 90% of the boundary neighbour area
belonging to the absorbing material. Looser settings (0.010/0.80 and 0.030/0.70)
were built and rendered and scored **identically**, so the tightest was kept.

`glass`, `Tyre_Rubber`, `Rim_Alloy`, `Brake_Disc` and both `Lamp_Lens` materials
are **frozen** in both directions — the 2026-08-11 glazing ruling and the tyre/rim
rulings. Measured on the locked camera, their visible pixel counts move by ≤ 8 px
(anti-aliasing noise) while `Interior_Plastic` on the body drops 16,162 → 9,540 px.

**This is not "concealing a geometry defect with paint"** (production brief rule 1).
The clay render is the evidence that the geometry underneath is already correct;
the only thing wrong was which material the triangles were bound to.

## Traps paid for here

* **`sc.graph.get(geom_name)` raises `No path from world->X_1` on a multi-primitive
  GLB**, and trimesh's node dedup suffix carries a **hash that changes between
  loads** (`Body_Shell_529452` one load, `Body_Shell_cd1a53` the next) — so node
  names must never be used as a join key across two loads. Iterate
  `graph.nodes_geometry`. Colour diagnostics by MATERIAL (`matid_mat.py`), not by
  node.
* **`trimesh` submesh export drops NORMAL accessors** (the recorded crumpled-foil
  class). It also makes a before/after render uncomparable, because the shading
  changes for a reason unrelated to the fix. Every edit here is an index rewrite.
* **An emission/label/clay render hides this defect completely.** The first three
  diagnostics all came back clean and each one was nearly read as "fixed".
* **A centroid-distance doubling test under-reports by ~5×** when the two sheets
  are tessellated differently: centroids sit ~Lc/2 apart laterally at zero gap.
  Measure perpendicular separation with a projection-overlap test (`dbl.py` v2;
  v1 is withdrawn and says so).
* **An outward field must be built only from VISIBLE faces.** `deskin.py` v1 used
  every face; the 543,164 faces that are never visible have a zero outward vector,
  `side` read 0.0, and **17.3% of the car was condemned**.

## Files

| file | what it is |
|---|---|
| `relabel.py` | **the repair.** Island absorption by glTF index edit. |
| `dbl.py` | anti-parallel near-coincidence census + 3 negative controls |
| `label_islands.py` | component census on the welded surface (threshold evidence) |
| `skinprobe.py` | ray visibility / depth-order / ordered mesh-pair table |
| `hole_test.py` | exact triangle-multiset equality + 15-direction ray hole test |
| `skin_render.py` | locked-camera Cycles rig: shaded, clay, label, backfacing, AO, bisect |
| `speckle.py`, `speck2.py` | dark-speck counters (fixed regions / paint mask) |
| `matid_mat.py`, `matid_glb.py`, `greenify.py`, `diag_glb.py` | diagnostics |
| `check_gates.py` | glazing / tyres / materials / Khronos validator on a local GLB |
| `glb_facecut.py` | index-only face deletion (used by the withdrawn route) |
| `deskin.py` | **withdrawn.** The deletion route; measured to make the render worse |
| `sb_put.py` | chunked upload + verification by LISTING the prefix |
| `HYPOTHESIS.md` | the falsification criteria, written before any probe was built |

Artefacts: `car-meshes/staging/skin/glb/` (chunked GLBs + MANIFEST) and
`car-meshes/staging/skin/` (evidence sheets, reports, mobile export).
