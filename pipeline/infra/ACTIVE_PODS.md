# Active RunPod pods — CHECK THIS AFTER ANY ROLLBACK

A running pod bills continuously. This container has rolled back repeatedly and
loses local state each time, so any pod started here is recorded immediately.

| pod id | name | gpu | $/hr | started | purpose | stop when |
|---|---|---|---|---|---|---|
| `lizpcgib9tyv8p` | 3daigc-partfield-trial | RTX A5000 24GB | **0.27** | 2026-08-07 20:44 UTC | Trial of 3DAIGC-API (template `bb0j8jta3y`, image `fishwowater/3daigc-api-runpod`) to test whether PartField mesh segmentation can rescue cars scrapped for bad material splits | as soon as the segmentation test is judged |

## Stop / terminate

```
curl -X POST -H "Authorization: Bearer $RUNPOD_API_KEY" \
  https://rest.runpod.io/v1/pods/lizpcgib9tyv8p/stop      # stop (keeps volume, still bills for storage)
curl -X DELETE -H "Authorization: Bearer $RUNPOD_API_KEY" \
  https://rest.runpod.io/v1/pods/lizpcgib9tyv8p           # terminate outright
```

Check what is running and what it costs:

```
curl -s -H "Authorization: Bearer $RUNPOD_API_KEY" https://rest.runpod.io/v1/pods
curl -s -X POST -H "Authorization: Bearer $RUNPOD_API_KEY" -H "Content-Type: application/json" \
  -d '{"query":"query { myself { clientBalance currentSpendPerHr } }"}' https://api.runpod.io/graphql
```

## Why this trial exists

The plan document names the paint defect precisely: on single-mesh models with no
real materials the body/glass/wheel split is a per-polygon geometric guess, so
colour overspills onto trim and wheels. The BMW audit gate says the same thing on
242 rows -- "paint would bleed into trim/glass; fixable by a material split" --
and two scrapped cars (an F90 M5 and an F32 4 Series) render with body-coloured
WHEEL RIMS, which is that defect made visible.

PartField segments a fused mesh into parts, i.e. it creates the real materials
the render pipeline needs. It needs only 4GB VRAM. If it works, the 242-row scrap
pool becomes a rescue queue and library-wide paint quality improves. NOTE this
cuts against the standing "don't fix, just scrap" rule -- it is a policy question
for the owner, which is why this is a measured trial and not a batch run.
