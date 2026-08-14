# 3D study: how cars are actually built, why our generator melts, and what to do

Written 2026-08-14 at the owner's instruction to stop and *learn* — geometry,
Blender, polish, car surfacing, the generator landscape, GLB authoring, and how
these machines are trained. Everything below that is a claim about **our files**
was measured today with `pipeline/qc/mesh_forensics.py`; everything that is a
claim about the **field** carries a source. Where a hypothesis of mine was wrong,
it is recorded as wrong rather than quietly dropped.

---

## 0. The headline, before the detail

**Our problem is not jaggedness. It is the opposite — terminal smoothness.**

I went in expecting the classic Marching-Cubes staircase (vertices pinned to a
voxel lattice, creases averaged away, stair-stepped diagonals). That is the
standard failure of implicit-field generators and it is what "jagged" would mean
here. **It is not what our files show.**

| file | sharp_share (face pairs >45°) | grid fingerprint | verdict |
|---|---|---|---|
| `cat_stelvio_uc.glb` (catalogue, human-made) | **18.6 %** | 0.005 (= baseline) | real panel edges |
| `authored_car.glb` (written from scratch today) | **6.5 %** | 0.012 | real, deliberate edges |
| `golf_generated.glb` (Hunyuan) | **1.9 %** | 0.006 (= baseline) | melt |
| `yaris_mv.glb` (Hunyuan 2mv, today) | **0.8 %** | 0.005 (= baseline) | melt |
| `yaris_mv_raw.glb` (pre-decimation) | **0.4 %** | 0.006 (= baseline) | melt, and worse raw |

Two findings in that table:

1. **My grid hypothesis found nothing — and the audit corrected WHY, twice.**
   `grid_score` — the share of vertices with ≥2 coordinates landing on a common
   lattice — sits at the random baseline for every generated file, *including
   the raw pre-decimation mesh*.
   **CORRECTED 2026-08-14 (council audit, verified against the cloned 2.1
   source):** the first version of this section said Hunyuan 2.1 "does not use
   Marching Cubes, it uses DISO/DiffDMC". That was documentation-sourced and is
   WRONG for our runs: `model.py:207` defaults to `MCSurfaceExtractor()`, which
   is skimage `measure.marching_cubes` — **classic MC**. `DMCSurfaceExtractor`
   (DiffDMC) exists but only engages via `enable_flashvdm_decoder()`, which our
   pipelines never call. Second correction: a lattice fingerprint SHOULD
   therefore exist, and my detector's failure to find one is methodological —
   it infers the cell size from the MESH extents, but the true grid spans the
   generator's bounds (±1.01), which the mesh never reaches, so scale and
   offset are both wrong; its resolution sweep also steps by 16 and skipped
   380, the resolution we actually ran. "No lattice" is therefore NOT
   established — "my detector cannot see the lattice" is. The melt conclusion
   below does not rest on this metric.
2. **The raw mesh is smoother than the decimated one** (0.4 % vs 0.8 %). Whatever
   sharpness exists is being *created* by decimation, not destroyed by it. The
   field itself has no creases in it.

So the melt is not an extraction artefact that a better extractor would fix. The
field being extracted is genuinely smooth.

---

## 1. Why a shut line cannot come out of these models — arithmetic, not opinion

A production panel gap is **3–5 mm** on a **~4000 mm** car. The generators work
on a cubic grid, so a feature must span at least ~2 cells to exist at all:

| octree resolution | voxel size | shut line in voxels | verdict |
|---|---|---|---|
| 256 (TRELLIS typical) | 15.6 mm | 0.19 | impossible |
| **380 (our Yaris run)** | **10.5 mm** | **0.29** | **impossible** |
| 512 (HY 2.1 practical max) | 7.8 mm | 0.38 | impossible |
| 1024 | 3.9 mm | 0.77 | impossible |
| 1536 (HY 3.0, hosted only) | 2.6 mm | 1.15 | marginal |

**A shut line is below the representable bandwidth of every open generator, by
3–5×.** No fine-tune, seed, prompt or view count changes this; it is the grid.
This retroactively explains the two-month record in `CLAUDE.md`: input prep, view
count, resolution, seed and Blender correction were each tried and each failed to
produce shut lines. They were always going to.

And the mirror-image fact, which is the opening for a cheap fix:

> Our viewer shows a 4000 mm car in ~800 px → **5 mm per pixel**. A 3 mm shut
> line is **0.6 of one pixel**. It is *sub-pixel geometry* that the customer
> nonetheless sees clearly — because what they see is a **dark line**, i.e. a
> shading feature, not a shape feature.

That is the whole argument for putting panel seams in a **normal/roughness map**
rather than in geometry. Games and product-viz have done exactly this for twenty
years, and at our viewing distance it is not a compromise — it is the correct
representation.

---

## 2. How a professional actually builds a car (and what we can borrow)

The industry pipeline, in the order it happens:

- **Class-A surfacing** (Alias/ICEM, NURBS) is the automotive gold standard: the
  aesthetic surfaces of the production car, built to **G2/G3 continuity** so that
  reflection highlights flow without breaks. "Class A" is a *continuity* standard,
  not a polygon standard — which is why a mesh can be dense and still look cheap.
- **Polygon car modelling** works to the same goal with different tools: **quads
  only**, edge loops that follow the real panel lines, and **support loops** — a
  pair of extra loops either side of a feature so that subdivision keeps it crisp
  instead of rounding it off. Sharpness is *authored*, by loop placement or by
  **edge creases**, never by adding density.
- **Panels are separate objects.** Bonnet, doors, tailgate are detached, given
  thickness with Solidify/Shell, and the gap between them *is* the shut line. This
  is why a real car reads as assembled: the gap has walls and catches a shadow.
- **Polygon budgets**: 300k–800k for exterior marketing renders; 500 k–5 M for
  hero/cinematic; 80–200 k for a racing-game hero car. Our catalogue Stelvio at
  155 k triangles sits exactly in the game-hero band, and it beats a 400 k
  generated mesh on every sharpness metric. **Density is not quality.**

**What we can borrow immediately:** separate panels + engraved gaps is a
*procedural* operation. It needs semantics (where is the door?), not artistry —
and semantics is what P3-SAM and PartCrafter already give us.

---

## 3. GLB authoring — proven by building one

I wrote `pipeline/trellis/author_car.py`: a car GLB built **from scratch in pure
Python**, no Blender, no generator — 219 KB, 14 meshes, 5 materials, rendered
successfully through the production rig (`scratchpad/study/auth_215.png`).

The format, as it actually is:

```
[ 12-byte header ][ JSON chunk ][ BIN chunk ]
  magic 'glTF'      scene graph    raw bytes
  version 2         materials      positions / normals / indices
  total length      accessors
```

- **buffer → bufferView → accessor** is the whole data path. A `bufferView` is a
  byte range; an `accessor` types it (`VEC3`/`FLOAT`, count, and for POSITION a
  mandatory `min`/`max`). Every block must be 4-byte aligned or the file loads in
  one viewer and fails in another.
- The JSON chunk pads with **spaces**, the BIN chunk with **zeros**. Getting that
  backwards produces a file that validates and then renders nothing.
- **Materials are just names + PBR factors** — which is precisely why every gate
  in this repo works the way it does: `glass_probe` reads `alphaMode`/alpha,
  `respray_gltf` rewrites `baseColorFactor` by material name. Authoring one makes
  the probes obvious rather than magical.

Measured result of the authored car: **`sharp_share` 6.5 %** (vs 0.8 % generated),
**`glass_probe` → clear / proven**, respray touches only `Material_0`. The three
engraved shut lines are plainly visible in the render as dark seams.

**Honest limitations of my car:** the shape is crude — a lofted superellipse
tube, not a designed body — and the greenhouse sits *inside* the body tube rather
than filling window openings, so the glazing does not read. It proves the
*technique* and the *format*, not that I can hand-model a Yaris.

---

## 4. The extraction algorithms, and which one we would want

| method | vertex placement | sharp features | notes |
|---|---|---|---|
| Marching Cubes | on cell **edges** | ✗ averaged away | the classic staircase; can't put a vertex on a crease |
| Dual Contouring | one free vertex **in cell** | ✓ (needs gradients) | can produce non-manifold vertices |
| Dual Marching Cubes | dual grid | partial | **what Hunyuan 2.1 uses (DISO/DiffDMC)** — tuned for smooth, uniform output |
| Neural Marching Cubes | learned | ✓ | learns the tessellation instead of fixing it |
| **FlexiCubes** | free + **learnable** per-cell weights | ✓ | differentiable; extends DMC to multiresolution; designed for gradient-based mesh optimisation |

The practical reading: we are already past naive MC. Moving to FlexiCubes would
buy differentiability and feature flexibility — but **it cannot invent detail the
field does not contain**, and §1 says the field cannot contain a shut line at our
grid size. Extraction is not our bottleneck.

---

## 5. The other family: generate the mesh, not the field

`MeshGPT → MeshAnything → EdgeRunner → TreeMeshGPT → PolyFlow / MeshRipple` are
**autoregressive artist-mesh generators**: they emit *triangles as tokens*, so the
output has artist-like edge flow and genuinely sharp edges by construction — no
field, no extraction, no smoothing. MeshAnything's trick is to take a *given*
shape and only learn the topology, which is why it trains cheaply.

The catch is the face budget — EdgeRunner reaches ~4 k faces; the family is in the
thousands, not the hundreds of thousands. A 4 k-face car is a game LOD, not a hero
asset. **Watch this family; do not bet the machine on it yet.** The interesting
hybrid, if it matures: Hunyuan for the shape, an artist-mesh model for the
*retopology*, which is the same division of labour that already worked for us in
`hybrid_transfer.py`.

---

## 6. Generator landscape, as of now

- **Hunyuan3D 2.1** — 3.3 B shape + 2 B paint, **the last open release with
  training code and PBR weights**. This is our base and the choice is confirmed.
- **Hunyuan3D 2.5 / 3.0 / 3.1 — hosted only, not open-sourced.** 3.0 (Sept 2025)
  reaches 1536³; 3.1 (Nov 2025) adds 8-view input, watertight meshes, cleaner
  topology, 4K PBR. Note 1536³ is the *only* tier where a shut line is even
  marginal — and it is exactly the tier we cannot clone.
- **Hi3DGen** — normal-bridging: image → *normal map* → geometry, with normal-
  regularised latent diffusion. It targets precisely our failure (sharp detail
  fidelity) and it is open. **Still the single most promising untested lever.**
- **Tripo / Meshy** — commercial, strong topology and speed; ruled out by the
  owner's "own model, not API".
- **DetailGen3D** — generative *enhancement* of a coarse shape via data-dependent
  flow, i.e. a refiner that takes existing generated geometry and adds detail.
  Structurally the right shape of tool for our problem; unverified on cars.

---

## 7. How these machines are trained (and what a fine-tune can and cannot do)

The standard stack, which Hunyuan 2.1 follows:

1. **3D VAE** encodes a watertight surface (sampled points + normals) into a
   *latent token set* — a few thousand tokens for a whole object.
2. **DiT + flow matching** learns to denoise those latents conditioned on image
   features (DINO/CLIP-class encoders); multi-view conditioning joins several
   images into the same condition.
3. **Decode → occupancy/SDF grid → surface extraction** (§4).
4. Texture is a **separate** model (Hunyuan3D-Paint).

Consequences that matter for our pilot:

- **The latent is the bandwidth ceiling.** A few thousand tokens for an entire car
  is roughly one token per ~2 cm of body — detail finer than that is not
  representable *before* the grid even gets involved. Fine-tuning changes what the
  model *puts* in those tokens, not how many there are.
- **So a fine-tune can realistically buy us**: better proportions, correct
  hatchback/saloon/SUV silhouettes, sharper *large* features (arch lips, shoulder
  lines, bumper breaks), fewer hallucinated rear ends. **It cannot buy shut
  lines.** That should be stated in the pilot's success criteria up front, or the
  pilot will be judged against something it cannot deliver.
- **LoRA/DoRA** is the sane parameterisation — low-rank updates on a 3.3 B model,
  affordable on rented GPUs, and reversible.
- Our data spec is already right: `{uid}_surface.npz` + 24 conditioning renders,
  which is what `dit_asl.py` actually reads, produced by our own
  `hy21_render.py`.
- **Curation is the lever we already validated**: 1/3 of the catalogue is *softer*
  than the generated car (`crease_density` sweep, `TRAINSET_SCORES.jsonl`), so
  training on all of it would teach the model to be *more* melty. The 225 cars
  ≥200 are the real training set.

---

## 8. Blender polish — what each tool does, and where it lies

From the repo's own scar tissue plus this study:

| tool | what it genuinely does | the trap |
|---|---|---|
| Subdivision Surface | smooths, quadruples faces | **cannot add detail** — it removes it unless supported by loops/creases |
| Edge Crease (Shift+E) | keeps an edge sharp under subdiv | crease data is glTF-lossy; bake it or model it |
| Support loops | the real way to hold a feature | needs *semantics* — you must know where the panel edge is |
| Bevel | turns a hard edge into a highlight-catching chamfer | on a generated shell there is no hard edge to bevel |
| Weighted Normals | fixes *shading* on hard surfaces | changes shading only; geometry stays soft |
| Corrective Smooth | removes deformation artefacts | measured a **visual no-op** on our melt (`process_candidate.py`) |
| Shrinkwrap | projects a clean mesh onto a dense one | **this is the retopology route** — the useful one |
| Remesh / QuadRemesher | rebuilds topology; auto-detects creases past ~30° dihedral | on our meshes there *are* no ≥30° dihedrals to detect (§0) — it will find nothing |

The pattern is stark: **every polish tool needs an existing feature to work on.**
Our generated cars have `sharp_share` 0.8 %. That is why two months of polish
attempts produced no shut lines — there was nothing for the tools to grab.

---

## 9. What I would actually do, ranked

1. **Engrave the panel seams procedurally** (highest value/cost ratio). We already
   have per-part semantics from P3-SAM (wheels, mirrors, trim cut cleanly) and
   PartCrafter (canopy). A door boundary is a curve on the body surface; a groove
   or a baked normal-map line along it is a solved geometry problem. §1 says this
   is not cheating — it is the only way the feature can exist at our resolution,
   and at 0.6 px it should arguably be *shading* anyway.
2. **Test Hi3DGen** (~$1, one pod). It attacks sharpness at the conditioning
   stage, which is the one stage we have never varied. Gate it on
   `mesh_forensics.sharp_share` against the Hunyuan baseline of 0.8 % — a
   material improvement means ≥3 %, and the flat clay-render comparison we have
   been using cannot measure that.
3. **Run the fine-tune pilot on the 225 curated cars** — with success criteria
   written in advance as *proportions, silhouette, large-feature sharpness*, and
   explicitly **not** shut lines.
4. **Try normal/roughness map detail** for seams, grille mesh and lamp internals.
   Cheap, and it targets exactly what a customer sees at 5 mm/px.
5. **Watch the artist-mesh family** for a face budget that reaches car scale.

**And the honest strategic sentence:** every open generator shares the same
bandwidth ceiling, so if 1–4 do not clear the premium bar, the conclusion is not
"try another model" — it is that image-to-3D cannot currently produce a premium
car, and the money belongs in sourcing or licensed heroes. That was already the
owner's standing position; this study puts a measured number under it.

---

## Tools written for this study

- `pipeline/qc/mesh_forensics.py` — grid fingerprint, `sharp_share`, dihedral
  histogram, triangle quality, valence. Tells a generated mesh from an authored
  one and says why.
- `pipeline/trellis/author_car.py` — a car GLB written byte-by-byte from scratch;
  reference for the format and a numeric target for what "sharp" looks like.
- `pipeline/qc/prod_render.py` — the production-rig harness, now in the repo.

## Sources

Class-A / automotive surfacing: [Autodesk — Understanding Class A Modeling](https://help.autodesk.com/view/ALIAS/2024/ENU/?guid=GUID-64611955-D2CC-44F2-98F0-D4F1FE931D8B),
[Class A surface (Wikipedia)](https://en.wikipedia.org/wiki/Class_A_surface),
[Car Body Design — Modeling Cars in Polygons](https://www.carbodydesign.com/article/59531-modeling-cars-in-polygons/),
[Polygon count guide 2026 (CGAxis)](https://cgaxis.com/polygon-count-guide-how-many-polys-do-you-really-need-in-2026/),
[Car modeling for games — topology & PBR](https://sunstrikestudios.com/en/blog/car_modeling_for_games/).
Extraction: [FlexiCubes (NVIDIA)](https://research.nvidia.com/publication/2023-08_flexible-isosurface-extraction-gradient-based-mesh-optimization),
[Occupancy-Based Dual Contouring](https://arxiv.org/html/2409.13418),
[Neural Marching Cubes](https://arxiv.org/pdf/2106.11272),
[DISO](https://github.com/SarahWeiii/diso),
[Hunyuan3D 2.1 shape stack](https://www.emergentmind.com/topics/hunyuan3d-2-1).
Artist meshes: [MeshAnything](https://buaacyw.github.io/mesh-anything/),
[EdgeRunner](https://ar5iv.labs.arxiv.org/html/2409.18114v1),
[TreeMeshGPT](https://arxiv.org/html/2503.11629).
Sharper generation: [Hi3DGen](https://stable-x.github.io/Hi3DGen/),
[DetailGen3D](https://detailgen3d.github.io/DetailGen3D/).
Landscape: [Tripo vs Hunyuan (2026)](https://www.tripo3d.ai/compare/tripo-vs-hunyuan),
[Meshy vs Hunyuan3D (2026)](https://www.meshy.ai/compare/meshy-vs-hunyuan3d).
Format: [glTF 2.0 specification (Khronos)](https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html).
Retopology: [Blender manual — Remeshing](https://docs.blender.org/manual/en/latest/modeling/meshes/retopology.html),
[Quad Remesher](https://quadremesher.com/landing).
