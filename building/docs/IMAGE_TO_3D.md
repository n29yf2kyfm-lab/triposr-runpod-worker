# Pictures into 3D — what the tools do, and what we take from them

Studied 2026-08-14 from the workflows the owner sent (Vizcom Make 3D,
SAM 3D + Blender, 2D photo → building in Blender, SketchUp → GLB,
drawing → 3D print) plus the current literature. Sources inline.

## 1. The one sentence that governs all of it

**Every one of these tools turns pictures into APPEARANCE. Not one of
them returns a dimension you may trust.** Vizcom, SAM 3D, TripoSR,
TRELLIS, Hunyuan3D, photogrammetry and gaussian splats all output
geometry in arbitrary units with invented back faces. That is not a
criticism — it is what they are for. It is also exactly why this
project's rule exists: measured never imagined.

So the correct architecture is not "pick the best image-to-3D model".
It is a **fusion**:

| Source | Gives | Never gives |
|---|---|---|
| Vizcom / SAM 3D / TripoSR / TRELLIS / Hunyuan3D | plausible shape + texture | true metres |
| Photogrammetry / gaussian splat | photoreal look of a REAL house | measurable dimensions |
| Camera projection (Blender/fSpy) | photoreal skin on YOUR geometry | any geometry — you supply it |
| LiDAR · OS/LIDAR heights · RoomPlan · figured dims | metres | looks |

We already own the right half (model3d, scale.py, roomplan, osgb) and
most of the left (reconstruct.py, splat.py, the TripoSR/TRELLIS
endpoints). The gap is the JOIN.

## 2. Vizcom Make 3D — multi-view is the professional standard

Sources: docs.vizcom.com/2D-to-3D; vizcom.com/resources/docs/types-of-3d-generations;
meshy.ai multi-view tutorial.

- Select **2–5 views** of the same object; front view REQUIRED; the
  panel exposes Front / Left / Back / Right slots explicitly.
- Advice given: overlapping angles, consistent soft lighting, cover the
  object completely; harsh shadows bake into the mesh.
- Modes trade mesh detail (Low Poly / Balanced / Highest) and
  "Detailed Sharp" preserves fine surface detail in mesh AND texture.

**What this confirms:** the pipeline order the owner has insisted on
from the start — *search the house → front pic → side pic → back pic →
THEN generate* — is precisely the professional requirement. Single-view
generation invents the sides; multi-view constrains them. Our capture
guidance should REFUSE to generate from one photo of a house, or label
the result as illustrative only.

## 3. SAM 3D (Meta, Nov 2025) — the new single-image baseline

Sources: ai.meta.com/blog/sam-3d; arxiv 2511.16624;
github.com/facebookresearch/sam-3d-objects.

- Two models: **SAM 3D Objects** (objects/scenes) and SAM 3D Body.
- Single image → full geometry, texture and layout, robust to occlusion
  and clutter; internally decodes to voxels, meshes AND gaussian splats
  with pose/scale attributes.
- Trained via a human-and-model-in-the-loop annotation pipeline
  (synthetic pretraining → real-world alignment) to break the 3D data
  barrier; reports ≥ 5:1 human preference over prior single-image work.
- **Open weights + inference code.**

Relevance: a candidate third engine beside TripoSR and TRELLIS on the
endpoint, particularly for CLUTTER — a real front garden has bins, cars
and hedges in shot, which is where object-level models earn their keep.
Same caveat as everything else in this section: no metric scale.

## 4. Image-to-3D state of the art (2026)

Sources: triposr.org Hunyuan3D-vs-TRELLIS-vs-TripoSR; trellis2.com
comparison; 3daistudio API comparison.

- **TRELLIS 2** — structured 3D latents, representation resolutions up
  to 1536³, explicit voxel-resolution and sampling controls. (This is
  the family the untouched `trellis2/` endpoint serves.)
- **Hunyuan3D 2.5 / 3.1** — high-fidelity detail; hosted endpoint takes
  MULTIPLE reference views, target face counts, optional PBR, and
  geometry-only output — the most "production" feature set.
- **TripoSR / Tripo 2.5** — fastest; best speed/quality for previews.
- Common complaint across all: fine detail goes fuzzy at low output
  resolution, and textures bake in the lighting of the input photo.

## 5. Camera projection — the technique we should steal outright

Sources: yelzkizi.org camera-mapping-blender; docs.blender.org UV Project
modifier; whatmakeart.com Blender + fSpy; Perspective Plotter.

The Blender workflow is: match a camera to the photo's perspective
(fSpy / Perspective Plotter), then **Project From View** or a **UV
Project modifier** to drape the photo over geometry — a slide projector
onto a model. Caveat noted in the manual: perspective UV projection onto
coarse geometry produces artifacts; subdivide.

**We can do it better, and more honestly.** fSpy exists to GUESS the
camera because the modeller has no true dimensions. We do: our elevation
is a measured rectangle in metres. Given the four facade corners located
in a photograph, an 8-parameter **homography** maps that photo directly
to a rectified, scaled orthophoto of the elevation — no camera guess, no
perspective artifacts, no subdivision.

That single step unlocks three things at once:
1. **Photoreal skin on measured geometry** — the honest way to reach
   "a homeowner cannot tell it from a photo" for an EXISTING house.
2. **Elevation survey underlay** — tracing openings off a rectified
   photo is standard practice for existing-building surveys.
3. **Measurable openings** — on a rectified elevation, window and door
   rectangles are axis-aligned and IN METRES, so they can be measured
   rather than estimated. Cross-check against `scale.py`'s brick-course
   anchor (a course is 75 mm; four courses rise exactly 300 mm) which
   already exists and is the best ruler in any British photograph.

## 6. Interop — where our exports actually land

Sources: cadinterop.com SketchUp + Revit format pages; archdaily
DWG/IFC/RVT/PLN; injarch 3D file types guide.

- **IFC** is the neutral BIM exchange every discipline exports to; Revit
  (since 2025) writes IFC 2x3 / IFC4 / STEP AP214; SketchUp Pro imports
  DWG/DXF/IFC, Studio adds native .rvt import.
- **SketchUp 2025+ has built-in glTF/GLB and USDZ import AND export with
  PBR materials.**

So: `write_glb` already opens natively in SketchUp — the tool most
architects model in — and `write_ifc` already lands in Revit and
ArchiCAD. That is the "replace the architect" interop story mostly
solved already. What is missing:
- **DXF** — the 2D drawing exchange every CAD user expects (our plans
  exist as geometry; nothing writes DXF yet).
- **USDZ** — iPhone/Vision AR. A builder standing in the client's garden
  showing the extension at 1:1 on their phone is the demo that sells the
  job; SketchUp and Apple both consume USDZ natively.

## 7. Drawing → 3D print — a physical model from the same geometry

Sources: raise3d, formlabs, bigrep, fictiv wall-thickness guides;
fixie3d optimisation guide.

- FDM/PLA: **1.5 mm minimum wall**; supported walls can go to 0.8 mm,
  unsupported want ≥ 1.2 mm; size walls in multiples of the nozzle
  (0.4 → 0.8 / 1.2 / 1.6 mm).
- STL must be **watertight, manifold, outward normals**.
- Scaling is the whole risk: detail that is fine at full size becomes
  unprintably thin when shrunk.

Run our numbers: at **1:100**, a 300 mm external wall prints at 3.0 mm
(comfortable) but a 100 mm partition prints at **1.0 mm — under the
1.5 mm floor**; at 1:50 the partition is 2.0 mm (fine). So a print
export must either be 1:50, or thicken partitions and SAY it did.

Good news for implementation: `write_obj` already builds **solid boxes**
per wall with `_split_for_openings`, plus slabs, caps and pitched roof
planes — the exact solid geometry an STL needs. A binary-STL writer is a
short, dependency-free hop from there (the roof planes must be closed
into a solid, and the print-thickness rule applied).

---

## Work order this study creates

1. **`facade.py`** — homography rectification: photo + 4 measured facade
   corners → scaled orthophoto; outputs a texture for the model, a
   drawing underlay, and measurable opening rectangles. The join between
   the photo half and the measured half of this project.
2. **`printable.py`** — binary STL at a chosen scale, watertight solids
   reusing the write_obj box logic, minimum-thickness rule (1.5 mm PLA)
   with an honest report of anything thickened.
3. **Capture rules** — require front + at least one side before any
   generative reconstruction of a real house; label single-view output
   as illustrative, never measurable (matches the Vizcom standard).
4. **USDZ + DXF exporters** — AR on the phone; 2D CAD for the trade.
5. **Engine bench** — SAM 3D vs TRELLIS 2 vs TripoSR on the same UK
   street photos, scored on facade fidelity after our own scale
   anchoring, not on how pretty the mesh looks unscaled.
