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
