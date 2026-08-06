# Sourcing wave queue

Owner-set order. Record the instruction here the moment it is given — this
container has rolled back repeatedly and anything held only in session context
is lost.

| # | marque | status |
|---|---|---|
| 1 | Range Rover | done — 4 sourced, 1 scrapped on owner review, 3 live |
| 2 | Audi | done — 1,055 swept, 129 judged, 20 live |
| 3 | BMW | review done — 902 swept, 206 eye-reviewed, 26 keeps (13 live, 13 pending publish) |
| 4 | **Skoda** | **next** (owner instruction 2026-08-06) |

## Carried over into the Skoda wave

- **Bare nameplates in `model`, always.** `publish_batch` builds `modelFamily`
  as `"{make} {model}"` while the vehicle side carries no make prefix, so a
  match only ever succeeds through `modelAliases -> v.model`. A chassis- or
  trim-suffixed model (`m3 e92`, `m4 competition`) never equals the bare model
  a DVLA decode returns, and the entry ships but is unreachable. Eight BMW
  cars from batch one are in that state and still need an alias backfill.
- **Generation goes in the year range, not the model name.** `publish_batch`
  hardcodes `generation: None`, and the resolver hard-rejects an out-of-range
  year, so `yearStart`/`yearEnd` is the only working generation discriminator.
- **Year only where the source states it.** Accuracy rule. An empty range still
  resolves and merely scores lower; a guessed one can falsely hard-reject a
  real lookup.
- **`bodyStyle` is load-bearing** — `vehicle-resolver.ts:71` hard-rejects on a
  conflict and scores +15 on a match, so a body style the library lacks is a
  genuine gap worth filling (this is why the BMW convertibles were kept).
- **Check `workersMax` on `ng8oiz4p2l0xa0` before blaming a 409.** It was found
  at 0 on 2026-08-06 with the other endpoints healthy, so it was a stale
  leftover rather than the low-balance guard. A 409 on the first submit after
  restore is normal settling; retry.
