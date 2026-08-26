# Can Pixal3D take two views like TRELLIS.2?

**Date:** 2026-08-26
**Answer: NO. Pixal3D is SINGLE-IMAGE ONLY, verified in its own source.**

Checked by cloning `github.com/TencentARC/Pixal3D` and reading it, not by
recalling it:

* `inference.py:288` — `parser.add_argument("--image", type=str, required=True,
  help="Path to input image")`. One image, no `nargs`.
* `pixal3d/pipelines/pixal3d_image_to_3d.py:609` — `def run(self, image:
  Image.Image, camera_params: dict, ...)`. Singular, typed `Image.Image`.
* `grep -rln "run_multi_image\|multi_image"` across the repo → **no hits.**

## Why it matters, measured on a Ford Transit Custom panel van

TRELLIS.2 was given **two** views (front 3/4 + rear 3/4). Pixal3D got **one**
(front 3/4), because it cannot accept two.

| | Pixal3D 1536 (1 view) | TRELLIS.2 (2 views) |
|---|---|---|
| front end | grille slats, real lamp units, Ford badge, plate, spoked wheels | soft, flat disc wheels |
| flanks / rear | **gouged, torn, a hole punched through the cargo panel** | complete but soft/blobby |
| faces | 985,165 | 492,252 |

**So a Pixal-vs-TRELLIS comparison on this van is CONFOUNDED by view count and
must not be reported as a clean win for either.** The observed end is much
better on Pixal; the unobserved end is much worse. This is the same
single-image failure already recorded for Hi3DGen ("each single-view run makes
a car that is only right at its photographed end").

## Why it is worse on a van than on a car

The Yaris went through Pixal from a single front 3/4 and its tail came out
acceptable. A hatchback's tail is small and compact; **a panel van's rear is a
large flat unobserved surface**, so there is far more area for the generator to
invent and nothing constrains it.

## Consequences, within the frozen stack (TRELLIS.2 + machine + Blender 4.5.12)

Not fixable by prompt, seed, token budget or resolution — it is architectural.
The real options are:
1. choose the input photo so the end that matters most is the photographed one,
   and accept the other;
2. use TRELLIS.2 multi-view for a uniformly-soft-but-complete van;
3. run Pixal twice (front 3/4 and rear 3/4) and pick per vehicle — **untested**;
   fusing the two halves is research, not pipeline (already recorded for
   Hi3DGen).

## Run facts, so they are not re-derived

Pod `m9dv5scvamqhp2`, A100 80GB, image `alamk123/ai-mechanic@sha256:5c5b87ed…`.
`INFER_OK mode='--resolution 1536'` **on the first attempt, no low-VRAM
fallback.** deps 2 min, infer ~15 min, ~$0.44. Output 985,165 faces / 38.5 MB.
canon: L=0.933 H=0.386 W=0.439, H/L 0.413 against a real Transit Custom's 0.388
(6% tall — far better than the +33% width bias recorded on the Pixal Golf).
Artefacts: `car-meshes/pixal_van/` and `car-meshes/staging/pixal_van/`.
