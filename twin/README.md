# Property Digital Twin — platform

Worldwide, source-traceable property data with its own map engine.

    pip install flask requests pillow numpy
    python3 -m twin.api          # http://127.0.0.1:8000

## What is real here

Every real-world value carries a `Provenance` record (provider, dataset,
identifier, licence, retrieval and observation dates, accuracy,
confidence, processing method, and the chain back to the measurement).
Anything absent is an explicit `Missing` rendering as DATA NOT AVAILABLE
with the reason and who was asked. Nothing is defaulted, estimated
silently, or invented.

Geometry is classified `verified` / `derived` / `estimated` / `user` and
coloured accordingly on screen; the four never look alike.

## Data sources (see licences.py for the full registry)

| source | layer | licence |
|---|---|---|
| postcodes.io | UK postcode -> centroid | OGL v3.0 |
| Nominatim (OSM) | worldwide geocoding | ODbL data / endpoint policy |
| Overpass (OSM) | worldwide building footprints | ODbL data / endpoint policy |
| EA National LIDAR | England elevation, 1 m DSM/DTM | OGL v3.0 |

`licences.check()` refuses a use the terms do not grant. Esri World
Imagery is in the registry precisely so it can be refused for export and
commercial use — see STAGE 0.

## Tests

    python3 -m unittest twin.test_twin          # 48 offline
    TWIN_LIVE=1 python3 -m unittest twin.test_twin.TestLive   # 6 live
    node twin/e2e.js                            # 19 browser E2E

## Imagery

Free worldwide house-scale *photographic* imagery does not exist — every
provider that has it pays for it. So:

1. **We render our own** for England from Environment Agency LIDAR (OGL,
   no key, 1 m). Not a photo: a shaded surface model where every pixel
   has a height behind it. Roof planes, ridges, hips, dormers and garden
   levels read directly.
2. **Open photographic sources** where a country publishes them — USGS
   (US, public domain, sub-metre).
3. **Your own key** for the commercial providers, all of which have free
   developer tiers permitting commercial use:

   | env var | provider | resolution |
   |---|---|---|
   | `ARCGIS_API_KEY` | Esri World Imagery | 0.3 m |
   | `MAPBOX_TOKEN` | Mapbox Satellite | 0.3 m |
   | `MAPTILER_KEY` | MapTiler Satellite | 0.5 m |
   | `OS_DATA_HUB_KEY` | Ordnance Survey (GB) | 0.25 m |

Keys live on the server and are never sent to a browser; tiles are
proxied through `/api/tiles/<source>/{z}/{x}/{y}`. Sources whose licence
forbids the use are disabled in the picker with the reason shown.

## Stages 2-5: the editable twin

Tap a building on the map, press **Open digital twin**. One authoritative
model (`model.py`) drives three views; there is no second geometry to
keep in sync.

- **Stage 2 — property engine + the join.** A real footprint becomes a
  `Building`: minimum-area rectangle (not an axis-aligned bbox, which is
  25% too big on a rotated house), storeys from an OSM tag if there is
  one, else derived from LIDAR height, else flagged as a guess that must
  be corrected. `design.py` runs it through the existing building/
  engine for the regulations gate and the bill of quantities.
- **Stage 3 — 3D.** `render3d.js`: our own WebGL, no dependency. Orbit,
  pinch, six standard views, orthographic/perspective, and a real sun
  position (NOAA) for shadow studies. Geometry is coloured by
  classification, so a guessed storey never looks surveyed.
- **Stage 4 — the editor.** Every change is a validated `Command`:
  buttons, a dragged wall, or plain English all produce the same object.
  Undo/redo by REPLAY (not inverse), named versions, and refusals that
  say what is wrong and leave the model untouched.
- **Stage 5 — floor plans.** `plan.js` renders `design.floor_plan()` —
  the same blocks the 3D extrudes. Walls at real thickness, dimension
  strings, a north arrow that knows the building's true bearing, level
  switching, and drag-to-edit that goes through the same command path.

    node twin/e2e_twin.js      # 18 browser tests over stages 2-5
