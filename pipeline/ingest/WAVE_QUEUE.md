# Sourcing wave queue

Owner-set order. Record the instruction here the moment it is given — this
container has rolled back repeatedly and anything held only in session context
is lost.

| # | marque | status |
|---|---|---|
| 1 | Range Rover | done — 4 sourced, 1 scrapped on owner review, 3 live |
| 2 | Audi | done — 1,055 swept, 129 judged, 20 live |
| 3 | BMW | review done — 902 swept, 206 eye-reviewed, 26 keeps (13 live, 13 pending publish) |
| 4 | Skoda | swept + rendered 2026-08-08 — 58 candidates, 54 sheets in `audit/skoda`, 20 clean / 34 suspect. **Awaiting the owner's eye review.** |
| 5 | SEAT | swept + rendered 2026-08-08 — 415 swept, filtered to 38, **36 sheets** in `audit/seat`, 21 clean / 15 suspect. **Awaiting the owner's eye review.** |
| 6 | — | next marque not yet set |

## SEAT: a marque whose name is an English word (2026-08-08)

`marque_sweep.py` fires a bare-marque query alongside the per-nameplate ones.
For SEAT that query returned **1,425** results against 22 for `SEAT Ibiza`, and
the `class_gates` title filter rejected only **20** of them — it rejects a title
by what it looks like (`scan`, `train`, `bus`), and "Leather Car Seat" looks like
nothing in particular. 415 rows reached the manifest and **372 were not SEATs**:
airline rows, ejection seats, sofas, a seated Bodhisattva, other marques'
interior seats.

Rendering that manifest would have been ~1,660 GPU views for a real yield of 38.

**The fix, and when to reach for it:** `pipeline/ingest/nameplate_filter.py`
inverts the test — require a nameplate in the title rather than enumerating
every wrong thing — and additionally drops component titles (`headlight`,
`enginebay`), scale/print artefacts, and same-title-same-facecount re-uploads.
415 → 38. The gate is proven against 11 must-keep and 14 must-drop titles.

**The tell that a marque needs it:** compare the bare-marque result count against
the nameplate queries. A ratio anywhere near SEAT's 1425:22 means the bare query
is dominating with homonyms. Candidates still to come: Smart, Lotus, Born,
possibly Jaguar. Run the filter on any of them before spending GPU.

**Outcome:** 36 of the 38 rendered. The two that did not are size, not sourcing —
`Seat Mii Electric` (75 MB) and `Car Seat Leon` (53 MB) both exceed `gpu_wave`'s
48 MB `MAX_OBJ` ceiling. The split came out **21 clean / 15 suspect**, a far
better ratio than Skoda's 20/34, because the junk that drags a pool down was
removed before rendering rather than after.

## Review pages

`pipeline/qc/wave_review_page.py` builds the numbered eye-review page for any
wave from its triage JSON — every sheet at native width, ordered clean-first then
suspect by body share, with an index mapping each number to its uid. It shows the
material split but deliberately does not rank or pre-judge the cars: a car can be
amber and excellent, or green and junk, and putting a thumb on that scale would
corrupt the review it exists to serve.

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
