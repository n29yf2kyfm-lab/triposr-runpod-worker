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
