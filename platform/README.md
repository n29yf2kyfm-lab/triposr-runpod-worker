# ExpertCarCheck — 3D Vehicle Platform (Phase 1 MVP)

Turn a UK registration into a premium, near-instant, interactive 3D car.
This directory is the **serving + catalogue layer**; the GPU render worker that
builds the assets lives in [`../render`](../render).

## Architecture (two tiers)

- **Tier A — hero interactive models** (future): real-time WebGL with openable
  doors / lights / interior. Licensed or commissioned. Not in the MVP.
- **Tier B — cinematic turntables** (this MVP): a material-separated GLB is
  rendered on the GPU into a 36–48 frame clean-studio 360, stored in Supabase,
  and streamed to a drag-to-spin viewer. Recolour + re-wheel one base model to
  cover many variants.

**Hard rule:** AI generation never sits on the user's request path. Lookups are
served from the pre-built library; missing variants fall back to the nearest
match instantly and are built offline for the next visitor.

## Pieces

| File | What it is |
|------|-----------|
| `schema.sql` | Normalised Postgres/Supabase catalogue (manufacturers → models → generations → trims → variants), asset registry, render sets, VRM index, and the `variant_resolved` materialised view. Run once in the SQL editor. |
| `resolver/index.ts` | Supabase Edge Function `resolve-vehicle`: decoded spec (or hashed VRM) → best-matching asset + frame manifest. Scores make/model/year/trim/colour; never triggers AI on the hot path. |
| `catalogue/build_catalogue.py` | Builds the storage-backed catalogue: uploads turntable frames + per-car `manifest.json`, publishes `catalogue.json`. Idempotent. |
| `catalogue/catalogue.json` | The generated MVP catalogue index (4 cars). |
| `viewer.html` | The drag-to-spin showroom viewer. Reads `window.__CARS__` (inlined for the artifact demo) or, in the app, fetches manifests from Supabase. |

## MVP library (live in Supabase `car-renders`)

| Reg (demo) | Vehicle | Colour | Frames |
|-----------|---------|--------|--------|
| PO24 RSC | Porsche 911 GT3 Touring (2024) | Pearl White | 48 |
| AK19 VRM | Audi A1 S line (2019) | Floret Silver | 36 |
| AV08 CBK | Audi A3 S line (2008) | Ibis Silver | 36 |
| MN19 CPR | Mini Cooper S (2019) | Electric Blue (native) | 36 |

Catalogue index: `…/storage/v1/object/public/car-renders/catalogue.json`

## Flow

```
reg → (app decodes VRM: make/model/year/trim/colour)
    → resolve-vehicle edge fn → variant_resolved lookup
    → exact? serve asset + manifest  |  nearest? serve closest + enqueue build
    → viewer streams frames → drag-to-spin in <1s
```

## Wiring into the Lovable app (next)

1. Run `schema.sql` in the app's Supabase project.
2. Deploy `resolver/index.ts` as the `resolve-vehicle` Edge Function
   (secrets: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `VRM_PEPPER`).
3. On the reg-check result page, call the function with the decoded vehicle and
   mount the viewer against the returned manifest URL.

## Extending the library

Render a new car: upload a material-separated GLB to `car-meshes`, run the
turntable render (see `../render`), then re-run `build_catalogue.py`. Audit the
frame montage before publishing — only clean recolours ship.
