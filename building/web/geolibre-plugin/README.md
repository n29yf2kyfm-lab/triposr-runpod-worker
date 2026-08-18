# Builder — a GeoLibre plugin

Puts a measured building on a GeoLibre map, and adds the two things no
GIS knows: how far Class A permitted development would let a rear
extension go, and where the house throws shade at a given hour and
season.

## Why a plugin and not a fork

GeoLibre is MIT, so vendoring the whole application into this repository
would be legal. It would also be a maintenance trap — 47 MB of somebody
else's app, frozen at the day we copied it, drifting further from
upstream every release.

GeoLibre has two supported seams instead, and this project uses both:

| Seam | Where | What it does |
|---|---|---|
| Project format | `building/siteplan.py` | writes a complete, styled `.json` project — layers, styles, view — that GeoLibre opens live |
| Plugin API | this folder | our domain tools inside GeoLibre's own UI |

GeoLibre draws maps; it does not know what a rear extension may do. That
division is deliberate: we do not reimplement a GIS, and it does not
reimplement the GPDO.

## Install

No build step — `dist/index.js` is already a self-contained ES module,
which is what the manifest contract asks for.

- **Local directory** (desktop app): Settings → Manage Plugins →
  Settings section → add this folder.
- **Manifest URL**: host the folder and point Settings at its
  `plugin.json` (HTTPS, or HTTP on localhost for development).
- **Bundled drop-in**: copy the folder to
  `apps/geolibre-desktop/public/plugins/builder-siteplan/` in a GeoLibre
  build; add `"activeByDefault": true` to the manifest if it should load
  without a trip to the Plugins menu.

## Use

1. **Load** the `model.json` this project exports (`model3d.build` →
   `newbuild*.py` writes one next to the GLB).
2. **Click the map** to set the plan's origin corner, and type the
   bearing of plan north if the plot is rotated.
3. Toggle the **permitted development envelope** and the **shadow**, and
   drag the hour slider or pick a season.

The footprint is traced from the model's external walls, so an L-shaped
house draws as an L, not as its bounding box.

## Keeping the maths honest

The solar geometry, the GPDO depths and the tangent-plane transform exist
twice: here in JavaScript, and in `building/siteplan.py` and
`building/geo.py` in Python. Two implementations of the same geometry is
a promise to keep them equal, so `test_siteplan.py::TestPluginParity`
runs this bundle under node and fails if the two disagree on the
footprint area, the shadow reach, the sun's altitude or the PD depth.
Python is the authority — it is the one with the rest of the tests.

## What it does not claim

The permitted-development envelope is an **envelope, not a permission**.
Article 4 directions remove Class A, it never applied to flats or listed
buildings, and conservation areas, earlier extensions and the 50%
curtilage cap all bite. The plugin says so on its own face, and so does
this file.
