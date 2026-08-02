# Building Scanner — RunPod Serverless Worker

Scan a real building. Reconstruct it 1:1 inside and out, including the pipes and cables
behind the walls. Price the job at live local material prices and order the materials.
Audit its condition. Design the extension.

Full spec: [`../PLAN.md`](../PLAN.md) · Competitor teardown: [`../COMPETITORS.md`](../COMPETITORS.md)

## Isolation — read this first

This worker shares **nothing at runtime** with the live vehicle worker in `trellis2/`.

| | Vehicle (live — do not touch) | Building (this) |
|---|---|---|
| Endpoint | `nd0fagqlr5z2ur` (`trellis2-v2`) · `ng8oiz4p2l0xa0` (`render-v2`) | its own, not yet created |
| Image | `alamk123/ai-mechanic:trellis2-*` | `alamk123/building-scan:*` |
| CI trigger | `trellis2/**` | `building/**` |
| HF cache | `/runpod-volume/hf_cache` | `/runpod-volume/building_hf_cache` |
| Outputs | `/runpod-volume/outputs` | `/runpod-volume/building-outputs` |
| Bucket | existing | `building-scans` |

`validation.py` and `delivery.py` duplicate patterns from `trellis2/handler.py` **on
purpose**. Extracting them into a shared module would mean editing the vehicle worker,
which would rebuild and redeploy its production image. A few hundred duplicated lines cost
far less than breaking a product that is earning. A test asserts this isolation holds.

## Job contract

```json
{
  "input": {
    "mode": "reconstruct",
    "project_id": "12-acacia-avenue",
    "scan_id": "kitchen-first-fix",
    "stage": "open",
    "quality": "survey",
    "video_url": "https://.../walkaround.mp4",
    "roomplan_url": "https://.../kitchen.usdz",
    "depth_url": "https://.../depth.bin"
  }
}
```

### Modes

| Mode | Does | Phase |
|---|---|---|
| `reconstruct` | capture → registered metric point cloud | 1 |
| `register` | align two scans (open↔closed, room↔room) | 1 / 4 |
| `roof` | address → open LIDAR → planes, pitch, true sloped areas | 1b |
| `price` | measured quantities → rate card → priced quote | 2 |
| `supply` | price list → matched products → basket, supplier comparison | 2b |
| `valuation` | address → Land Registry + EPC + UKHPI → value, extension uplift | 2c |
| `planning` | address → site designations → is this permitted development? | 2d |
| `structure` | point cloud → walls, slabs, storeys → IFC | 3 |
| `model` | drawing's figured dimensions → walls, storeys, roof → OBJ + IFC | 3b |
| `services` | open-scan cloud → pipe and cable runs, BS 7671 zones | 4 |
| `drawing` | 2D PDF → confirmed scale → measured quantities | 7 |
| `condition` | imagery + thermal → 3D-located, costed defects | 5 |
| `design` | footprint + rules → massing + planning checks | 6 |

`price` takes quantities directly, or a whole `roof` result. It does **not** yet parse
RoomPlan or IFC — `structure` writes IFC but nothing reads one back in.

`structure` emits IFC walls and storey slabs with real placements and swept solids. It does
**not** emit openings or spaces: nothing in the segmentation detects a door, a window or a
room boundary, so there is nothing honest to write for them.

`model` runs the opposite way to `structure`: a plan in, a building out. It takes the
**figured dimensions** off a drawing — never the linework — because every UK sheet carries
"do not scale from this drawing" and means it: the dimension string is the contract and the
printed geometry illustrates it. Give it rooms and it returns walls with real thickness,
storeys, a pitched roof, an OBJ and an IFC, and a take-off.

A footprint too deep to span in one go becomes several parallel **ranges** with valley gutters
between them, which is what a double-pile roof is and why a Victorian pub reads as an M from
the end. Roofing 14 m in a single hip put the ridge 5 m above the wall head on a building with
2.75 m storeys — a roof nearly two storeys tall — and left the valley gutter off the quote
entirely.

Two things make it trustworthy rather than merely plausible. It **checks itself against the
drawing's own room schedule** — the areas the architect printed in each room, which the model
never saw — so a dimension read wrong shows up as a percentage rather than propagating
silently. And it measures the roof on the **true slope**: at 35° that is 22% more covering
than the footprint, and ordering off the footprint is how a re-roof comes up a fifth short on
a job already priced.

What it refuses to do is invent a dimension. A room with no stated size is reported missing,
not modelled at a guess. Rooms are rectangles; a bay or a splay is not in the model. And a
width outside 0.3–200 m is refused rather than clamped, because a drawing is figured in
millimetres and `4570` typed straight across is the commonest mistake there is.

Unimplemented modes return `status: "not_implemented"` with the implementing phase and a
validated manifest — never a bare 500.

### Key fields

- **`stage`** — `open` (first fix, services exposed) or `closed` (finished). Pairing the two
  is what produces the X-ray. An `open` scan on `quality: "fast"` warns: thin services sit
  near the resolution limit and **the wall cannot be recaptured once boarded**.
- **`quality`** — `fast` (MapAnything feed-forward), `quality` (+ COLMAP), `survey`
  (+ Gaussian splat).
- **`scale_source`** — defaults to `auto`. LiDAR depth is metric directly and always wins;
  otherwise scale comes from known-object anchors and the response **warns**, because an
  unscaled model is dangerous to quote or cut from.

### Scale anchors (non-LiDAR path)

| Anchor | Dimension | Why |
|---|---|---|
| **Brick coursing** | **4 courses = 300 mm** | Best reference in Britain — national standard, on nearly every house, and averaging across 20 courses beats any single object |
| Socket height | 450 mm | Building Regs Part M — mandated, so reliable indoors |
| Switch height | 1200 mm | Part M |
| Internal door | 762×1981 mm | Near-universal |
| Plasterboard | 2400×1200 mm | On every first-fix site |

## Output

```json
{
  "status": "success",
  "mode": "reconstruct",
  "manifest": { "...how your input was interpreted..." },
  "artifacts": {
    "cloud.ply": { "url": "https://...", "size_bytes": 84000000 }
  },
  "warnings": ["..."]
}
```

**Delivery matters more here than anywhere.** RunPod silently drops oversized outputs — the
vehicle worker hit this live, returning `COMPLETED` with `output=None`. Point clouds and IFC
models are far larger than GLBs, so object storage is the primary channel; inline base64
only under 4 MB; and when neither can deliver, the response says so loudly rather than
claiming success.

## Environment

| Variable | Purpose |
|---|---|
| `SUPABASE_URL` / `SUPABASE_KEY` / `SUPABASE_BUCKET` | Artifact delivery (bucket defaults to `building-scans`) |
| `BUILDING_OUTPUT_DIR` | Local artifact path (default `/runpod-volume/building-outputs`) |
| `HF_HOME` | Model cache — **must** be the building path, not the vehicle one |
| `OFFLINE=1` | Forbid runtime downloads; pair with `preload_models.py` |
| `DEBUG=1` | Include tracebacks in responses (bring-up only — they leak paths) |
| `GOOGLE_SOLAR_API_KEY` | Optional. Enables the Google Solar cross-check on Roof Mode. **Never commit a key** — set it on the endpoint, as with `SUPABASE_KEY` |
| `BUILDING_EPC_API_KEY` | Optional but it changes the answer. Bearer token for the EPC register, free from [get-energy-performance-data.communities.gov.uk](https://get-energy-performance-data.communities.gov.uk). Land Registry publishes what a house **sold for** but not how **big** it was, so without this there is no price per square metre and Valuation Mode falls back to indexing the property's own last sale. With it, a measured scan can be valued against real £/m² — which is the entire advantage over an agent's estimate. **Never commit the token** — set it on the endpoint |
| `FOOTPRINT_CACHE_DIR` | On-disk cache of OSM footprints (Overpass rate-limits and its mirrors time out) |

## Deployment

- **GPU: 48 GB (A6000 / A40)** as the default tier. Feed-forward reconstruction scales VRAM
  with frame count, so `max_frames` is capped and enforced rather than advisory; tile large
  properties instead of reaching for an 80 GB card.
- **Own network volume.** RunPod volumes are region-locked, so the endpoint's GPU pool must
  sit in the same data centre as its volume. It does **not** need to match the vehicle
  worker's region.
- **Retention.** Nothing prunes `building-outputs`, and scans are far larger than GLBs. Set
  a retention policy **before** the first real user, not after.

## Tests

```sh
python building/test_handler.py
```

That file alone carries 221 assertions; the whole suite is **1791 across 18 files** — run
them all with `for f in building/test_*.py; do python "$f"; done`. No GPU. Same approach as
the vehicle worker: stub the heavy modules, then test the contract logic. CI runs these
**before** building the image, so a broken contract never reaches a deployable tag.

Almost network-free: `test_handler.py` makes a handful of live calls to `api.postcodes.io`
while exercising geocoding failure paths. Every other file is offline, and the tests assert
an error is returned either way, so a postcodes.io outage does not fail the build.

CI installs `requests`, `ifcopenshell` and `pdfplumber` before running them. Without that the
runner is a bare interpreter, every lazy third-party import takes its `ImportError` branch,
and the suite validates the degraded path instead of the one that ships — which is exactly
how a broken IFC writer reached the deployed image with 1231 tests green.

## Build

`.github/workflows/building-docker-build.yml` — triggers only on `building/**`, tags
`alamk123/building-scan:{sha,v1,latest}`. Dependencies install before the source `COPY`, so
code edits reuse the cached layers.

**Tests run on every branch and every pull request; the image is built only from `main`** (or
a deliberate `workflow_dispatch`, which produces a SHA tag and never moves `v1` or `latest`).
Gating the whole workflow on `main` meant the suite never ran in CI on the branch the work
happens on — which is the same hole that let a `write_ifc` that had never once executed reach
a deployed image with 1231 tests green.
