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
| `schema.sql` | Normalised Postgres/Supabase catalogue (manufacturers → models → generations → trims → variants), asset registry, render sets, and the `variant_resolved` view. RLS is enabled on every table (public read, writes service-role only). Run once in the SQL editor. **No registration is ever keyed, indexed or stored — there is deliberately no VRM table.** |
| `resolver/index.ts` | Supabase Edge Function `resolve-vehicle`: takes the **decoded spec** (make/model/year/trim/body/fuel — never the reg) → best-matching asset + frame manifest. Self-contained: reads the published `catalogue.v2.json` + `aliases.json` from public storage (no DB, no service-role key). Scores make/model/year/trim/colour; never triggers AI on the hot path. |
| `dvsa-lookup/index.ts` | Supabase Edge Function: **reg → make/model/colour/fuel/year** via the DVSA MOT History API. Reg is read from the POST body only, never logged/stored. |
| `autodev-vin/index.ts` | Supabase Edge Function: **VIN → make/model/year/trim/body/engine/drive** via the auto.dev VIN decode API. Richer than DVSA (adds trim + body + drivetrain); returns a `resolverInput` block ready for `resolve-vehicle`. Needs `AUTODEV_API_KEY`. |
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

1. Run `schema.sql` in the app's Supabase project (enables RLS on all tables).
2. Deploy `resolver/index.ts` as the `resolve-vehicle` Edge Function. It needs
   **no secrets** — it reads the public catalogue from storage. Optional env:
   `RESOLVER_DATA_BASE` (point at a non-prod bucket) and `RESOLVER_MIN_SCORE`
   (defaults to 40). Do **not** give it a service-role key or a VRM pepper —
   it neither writes the DB nor sees the registration.
3. Deploy `dvsa-lookup/index.ts` (secrets: `DVSA_CLIENT_ID`,
   `DVSA_CLIENT_SECRET`, `DVSA_API_KEY`, `DVSA_TOKEN_URL`, `DVSA_SCOPE`). The
   app POSTs `{ reg }` in the body (never the query string) to decode it, then
   passes only the decoded spec on to `resolve-vehicle`.
4. (Optional, richer) Deploy `autodev-vin/index.ts` (secret: `AUTODEV_API_KEY`).
   When the decode yields a VIN, POST `{ vin }` to it for trim/body/drivetrain;
   use its `resolverInput` block (or merge it over the DVSA spec) before calling
   `resolve-vehicle` — the extra trim/body sharpens the resolver's score.
5. On the reg-check result page, call `resolve-vehicle` with the decoded vehicle
   and mount the viewer against the returned manifest URL.

## Extending the library

Render a new car: upload a material-separated GLB to `car-meshes`, run the
turntable render (see `../render`), then re-run `build_catalogue.py`. Audit the
frame montage before publishing — only clean recolours ship.
