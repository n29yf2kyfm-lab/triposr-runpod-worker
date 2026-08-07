# Active RunPod pods — CHECK THIS AFTER ANY ROLLBACK

A running pod bills continuously. This container has rolled back repeatedly and
loses local state each time, so any pod started here is recorded immediately.

| pod id | name | gpu | $/hr | started | purpose | stop when |
|---|---|---|---|---|---|---|
| ~~`lizpcgib9tyv8p`~~ | 3daigc-partfield-trial | RTX A5000 24GB | 0.27 | TERMINATED 2026-08-07 ~21:20 UTC | Never got a host: 30 min queued in EU-SE-1 with `runtime: none` and an empty `machine` while billing. Killed at a cost of ~$0.14. Retry with wider gpuTypeIds and any datacenter. | — |

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

## Endpoint config changes (2026-08-07)

- `nd0fagqlr5z2ur` (trellis2-v2): **workersMin 1 -> 0** (owner-approved). The
  pinned minimum worker billed ~$0.06/hr (~$42/month) around the clock for an
  endpoint the architecture only uses offline. Revert with
  `PATCH /v1/endpoints/nd0fagqlr5z2ur {"workersMin":1}` if instant TRELLIS
  response is ever needed again.
- `ng8oiz4p2l0xa0` (render-v2): gpuTypeIds widened from 4090-only to
  [4090, A40, RTX A6000, RTX A5000, L40S] during the billing incident.
  Original recorded in render_endpoint_original.json. KEPT after review —
  single-GPU pinning left the endpoint unable to allocate when 4090 supply
  tightened.
