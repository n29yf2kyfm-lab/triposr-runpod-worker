# Corpus — real 3D human `.glb`

A real, properly-modeled 3D human in binary glTF format, ready to open in any
glTF viewer or drop into the Corpus avatar.

## Files

| File | What it is |
|---|---|
| `human.glb` | The model — a realistic rigged human (T-pose), 16,340 verts / 28,106 faces, textured, ~3.2 MB, ~1.66 m tall. Valid binary glTF (`glTF` magic verified). |
| `viewer.html` | three.js viewer — orbit / zoom, auto-frames the model. |
| `human_preview.png` | Front / side silhouette render. |
| `ATTRIBUTION.md` | Source and license of `human.glb` — read this before redistributing. |
| `make_human_glb.py` | Optional: a from-scratch procedural generator (skin/muscle/skeleton layers, fully license-free) if you'd rather build a mesh than ship a downloaded one. |

## Source & license (important)

`human.glb` is the **"Michelle"** character from the three.js example assets,
originally from Adobe Mixamo. It is free to *use* in projects; redistributing the
raw file has caveats — see **`ATTRIBUTION.md`**. If you need a model with a clean
redistribution license, either:

- run `python make_human_glb.py` (produces a fully license-free procedural human
  with skin/muscle/skeleton layers), or
- swap in a **Ready Player Me** avatar (`https://models.readyplayer.me/<id>.glb`)
  or the CC-BY **CesiumMan** model.

## View it

- **Fastest:** drag `human.glb` onto <https://gltf-viewer.donmccurdy.com/>.
- **Local viewer:**
  ```bash
  python -m http.server 8080     # from this folder
  # open http://localhost:8080/viewer.html
  ```
  (`viewer.html` pulls three.js from a CDN, so serve over http rather than
  opening the file directly.)

## Note on anatomy layers

This realistic model is a single skin mesh — it has **no** separate
skin/fat/muscle/skeleton layers. Those layers exist only in the procedural
`make_human_glb.py` output, or in a real photo→3D anatomy pipeline
(the `phase0/` SAM 3D Body route, which needs a GPU + your own accounts).
