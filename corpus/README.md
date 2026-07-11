# Corpus — real 3D human `.glb`

A genuine, license-free 3D human model in binary glTF format, generated with no
GPU, no accounts, and no gated checkpoints. This is the avatar the Corpus app
needs — an actual mesh you can open in any 3D viewer, not a 2D placeholder.

## Files

| File | What it is |
|---|---|
| `human.glb` | The model. A three-layer scene: **skin**, **muscle**, **skeleton**. ~15.6k verts / 31k faces, ~550 KB. Skin layer is watertight. |
| `make_human_glb.py` | The generator. Builds the body from anatomically placed volumes → marching cubes → smooth watertight surface → GLB. |
| `viewer.html` | A three.js viewer with skin/muscle/skeleton toggles. |
| `human_preview.png` | Front / side / skeleton silhouette render. |

## How it's built (honest description)

`human.glb` is **procedurally generated**, not a photogrammetry scan. The body is
described as a set of capsules (limbs, torso) and ellipsoids (head, shoulder and
hip masses) sharing one skeleton of joint centres. Those are sampled onto a
signed-distance field, fused with a smooth-minimum, and turned into a watertight
surface with marching cubes (`skimage.measure.marching_cubes`), then Taubin-smoothed.
The muscle layer is the same body description shrunk inward; the skeleton is
cylinders + joint spheres on the same joint centres, so all three layers align.

It's a clean, neutral standing adult (~1.75 m). It is not a scan of a specific
person — that requires the photo→3D pipeline in `phase0/` (SAM 3D Body on RunPod),
which needs a GPU and your own accounts.

## Generate / regenerate

```bash
pip install numpy scipy scikit-image trimesh
python make_human_glb.py                      # -> human.glb (skin+muscle+skeleton)
python make_human_glb.py --res 200            # smoother (slower)
python make_human_glb.py --layers skin        # skin only
python make_human_glb.py --out avatar.glb
```

## View it

- **Drag-and-drop the fastest way:** open `human.glb` at <https://gltf-viewer.donmccurdy.com/>.
- **Local viewer with layer toggles:**
  ```bash
  python -m http.server 8080     # from this folder
  # open http://localhost:8080/viewer.html
  ```
  (`viewer.html` pulls three.js from a CDN, so serve it over http rather than
  opening the file directly.)

## Validity

`human.glb` starts with the `glTF` binary magic, loads back cleanly in trimesh as
a 3-geometry scene, and the skin layer reports `is_watertight = True`. Verified in
this repo before commit.
