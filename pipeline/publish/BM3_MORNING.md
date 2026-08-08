# BMW batch three — ready to fire (prepared overnight 2026-08-07)

## State when you read this
- **Review 100% COMPLETE**: all 470 manifest rows judged (G6 206, flagged 22, heavy-flag 242). 36 keeps total.
- **Batch two (13 cars) is LIVE with paint**: 8 variants each, recolour stamp PASS on the live catalogue. Library 653, BMW 63.
  Missing only POSTERS (make_posters never ran) — the /check page shows no hero image for the 13 until it does.
- **Batch three staged**: 10 keeps, hashes verified, manifests committed (BMW_KEEP_3.csv / BMW_LICENCES_3.csv).
  i8 Coupé · M2 G87 · X5 M F95 · M235i Coupé F22 · Isetta 300 · X6 M F86 · 318ti Compact · +3 CONDITIONAL: M5 G99 Touring (cov .525), i7 (cov .749), 5 Series E34 (cov .544) — over the clean-coverage ceiling; ship only if their recolour stamp passes, else quarantine.

## Morning sequence (GPU, ~40-60 min total)
```
set -a; . /root/.alam3d_env; set +a; export RP_KEY="$RUNPOD_API_KEY"
python3 pipeline/publish/make_posters.py --wave bm2                    # finish batch two
python3 pipeline/publish/publish_batch.py --keep pipeline/publish/BMW_KEEP_3.csv \
  --licences pipeline/publish/BMW_LICENCES_3.csv --wave bm3 --staging-prefix staging/bmw
python3 pipeline/publish/colour_variants.py --wave bm3
python3 pipeline/qc/recolour_audit.py --stamp                          # judges the 3 conditionals
python3 pipeline/publish/make_posters.py --wave bm3
```
End state if all pass: library 663, BMW 73.

## Re-source list (13 gaps, no clean copy in 902 swept)
507 · Baur 2002 cabrio · UK F30 saloon · E90 saloon · E36 saloon · E34 Touring · G31 5 Touring · E38 · E28 · E24 635CSi · G11/G70 7 Series · E63 M6 coupé (pending bmw-m6-v1 bodyStyle-vs-title fix) · 3 Series convertible (any gen) · Z4 E89

## Executed 2026-08-08 — end state

All five morning commands ran. Result:

- **29 cars published tonight** (bm2 13 + bm3 10 + ib1 6), 8 colour variants each,
  every variant render-verified. Library **642 → 671 approved** (789 total, 118
  quarantined). BMW **73** and now the largest marque.
- The 3 conditional bm3 rows all cleared their recolour stamp and shipped:
  M5 G99 Touring (Δ 0.501), i7 (Δ 0.335), 5 Series E34 (Δ 0.377). The
  clean-coverage ceiling flagged them; the render did not.
- Both catalogue paths served and in sync; gate PASS at 648/648.
- Morning data sheet: https://claude.ai/code/artifact/f7ba9291-618b-493c-b7d5-5d1584eff6dd

### Left for the owner (nothing blocking)

1. `bmw-m235i-2014-bm3-v1` — PASS at Δ 0.128, weakest of the 29 by a distance
   (next-lowest 0.268); its "blue" renders reddish. Keep or quarantine is an eyeball call.
2. `bmw-m6-v1` — `bodyStyle: coupe` vs source title "BMW M6 [Gran Coupe]".
   `vehicle-resolver.ts:71` hard-rejects on a body-style conflict, so one is wrong.
3. `bmw-m440i-gran-coupe-2022-bm1-v1` — tagged `hatchback`; `body-style-aliases.json`
   maps `gran coupe -> saloon`.
4. Eight batch-one BMWs unreachable by lookup (chassis-suffixed `model`). Alias
   backfill only — no re-render, no GPU spend.
5. `trellis2-v2` still holds `workersMin: 1` (~$0.058/hr idle). Approved for 0 but
   the PATCH was interrupted before it applied.
