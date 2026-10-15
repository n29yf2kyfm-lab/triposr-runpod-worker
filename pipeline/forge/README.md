# Forge — photographs in, an interactive car GLB out, no Blender

```
python3 pipeline/forge/forge.py JOB_DIR [--out car.glb] [--skin]
```

`JOB_DIR` holds `dims.json` (the manufacturer's figures in mm: name, style,
length, width, height, wheelbase, track, wheel_d, tyre_w) and background-removed
RGBA cut-outs `side*.png`, `front*.png`, `rear*.png`. Backgrounds come off
offline with `rembg` (U²-Net, 176 MB, CPU, about a second a photo).

| stage | file | what it measures |
|---|---|---|
| trace | `trace.py` | side: roofline, sill, wheel centres, beltline, window outlines, door shut lines. Front/rear: tumblehome and roof width (ratios, which survive a camera held above eye level). Scale from the published length and width; the dims are hard limits. |
| shape | `shape.py` | `PhotoCar`: the authoring loft (`pipeline/authoring`) driven by those curves instead of style constants. Anything not measured falls back to the style default and the report says which. |
| build | `forge.py` | the structured GLB (named panels, glass, wheels, plates) via `structured_car.build_structured`; `--skin` bakes the side photo on as paint. |
| check | `forge.py` | the loft projected back onto each photo: intersection-over-union per view in `forge_report.json`. Side under 0.90 means photo and model disagree. End views are flagged `elevated` when the photo was taken from above (every phone photo of a nose is). |

Proof car: 2021 Golf Mk8 from four CC BY-SA / CC BY photos on Wikimedia
Commons (authors recorded in the job's `refs.json`). Side overlap 0.908 with
the sill at typical rocker height (the cut-out kept the car's ground shadow;
with the shadow counted the overlap is 0.97). Three seconds end to end; rigs in
the Strip Bay rigger with four doors, bonnet and tailgate.

Not yet: plan-view nose and tail shape (no top view; a generic round corner),
lamps and grille from the end photos, interior kit, engine family, animation
clips, the headless preview sheet. Those are phases 2–4 of the design agreed
on 2026-10-15.
