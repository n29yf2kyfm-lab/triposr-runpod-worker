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
| 5 | SEAT | swept + rendered 2026-08-08 — 415 swept, filtered to 42, **40 sheets** in `audit/seat`, 24 clean / 16 suspect. **Awaiting the owner's eye review.** |
| 6 | MINI | swept + rendered 2026-08-08 — 432 swept, filtered to 50, **48 sheets** in `audit/mini`, 9 clean / 39 suspect. **Awaiting the owner's eye review.** |
| 7 | Kia | swept + rendered 2026-08-08 — 287 swept, 81 candidates, **70 sheets** in `audit/kia`, 18 clean / 52 suspect. **Awaiting the owner's eye review.** |
| 8 | Toyota | swept + rendered 2026-08-08 — 672 swept, 373 UK nameplates, capped to 168, **158 sheets** in `audit/toyota`, 67 clean / 91 suspect. **Awaiting the owner's eye review.** |
| 9 | Mercedes-Benz | IN PROGRESS 2026-08-08 — 453 swept, 309 after filtering, capped to 211, rendering to `audit/mercedes` |
| 10 | Renault | PART-DONE 2026-08-10 — 598 swept, 194 candidates, 107 rows after filtering. gpu_wave CIRCUIT-BROKE at row 21/107 on 6 consecutive Sketchfab 429s (shared token pool with the concurrent Nissan/Land Rover/Ford waves). **11 sheets** in `audit/renault`, all 11 eye-audited: 4 pass / 7 fail. Manifest is committed at `pipeline/ingest/renault_sweep_manifest.json` and the wave is resumable — rerun the same gpu_wave command when Sketchfab quota recovers; it re-checks the bucket and skips the 11 done. |
| 11 | — | next marque not yet set |

## Mercedes: a marque that names half its range by engine size (2026-08-08)

453 swept. The nameplate filter kept only 167 on the first pass and the drop
bucket was full of real cars — because Mercedes labels much of its range
`<class letter><displacement>`: C43, A45, E63, S500, G500, SL600, SL63. Those
titles contain no nameplate word at all.

Chasing them one at a time is whack-a-mole. **Generate the convention instead:**
23 class prefixes x 24 displacements = 552 tokens, fed in alongside the 50 real
nameplates. Every token is whole-word matched, so a combination that never
existed simply matches nothing and costs nothing. 167 -> 309 kept.

**Short tokens are not automatically unsafe.** SL, CL, ML and GL were left out
of the first list as too short. Measured against the real pool they match 14, 3,
4 and 2 rows and every one is a genuine Mercedes — excluding them was discarding
23 cars from nameplates with nothing live. `AMG` is the one that genuinely must
stay out: 92 rows, because it is a trim on everything. **Test the token against
the pool; do not assume from its length.**

A caution about how that was tested: the first check used an ad-hoc regex rather
than `nameplate_filter`'s own `norm()`, which folds "S-Class" and "S Class"
together. The filter was right and the test was wrong. Import the filter and
call `classify()` — never re-implement its matching to check it.

**Cap by CLASS, not by matched token.** With generated designations the `plate`
field holds "C43", so capping on it would treat C43, C63 and C-Class as three
separate nameplates and defeat the cap. Mapping the designation back to its
class first gives the real distribution: E-Class had 44 in the pool, C-Class 32,
SL 21, S-Class 20, while the gaps were single figures. 309 -> 211.

## Toyota: a big marque needs a cap, not just a filter (2026-08-08)

Toyota is not a homonym, so the nameplate filter had little to remove on that
score — but the sweep still returned **672** candidates and rendering them all
would have been roughly 2,700 GPU views against an $8.70 balance.

Two cuts, in order:

1. **UK nameplates only.** 277 rows carried no UK-market Toyota name at all:
   Century, Crown, Tundra, Tacoma, 4Runner, Sienna, Venza, Alphard, Harrier,
   Kijang Innova, Mega Cruiser, Dyna. None can be reached by a UK registration.
   672 -> 373.
2. **Cap 12 per nameplate, highest face count first.** The pool was
   grotesquely lopsided — 91 Supras, 46 Land Cruisers, 39 Corollas, 38 Hiluxes,
   36 Hiaces — all nameplates already live, while the actual gaps (Aygo 2,
   Verso 2, MR2 4, Celica 7, Starlet 1, Carina 1, Corona 1, iQ 1, Mirai 1)
   were single figures. The cap keeps every gap whole and trims only the
   well-covered. 373 -> 168.

Everything in the pool is already inside the serving face band, so "highest
face count first" selects for detail rather than for a browser problem.

**Outcome:** 158 of 168 rendered; the 10 that did not are all oversized past
`gpu_wave`'s 48 MB ceiling. Split 67 clean / 91 suspect.

**The review page had to be split in two.** 158 sheets at a legible quality is
~25 MB of base64 and the artifact ceiling is 16 MB. Dropping the JPEG quality
far enough to fit one page destroys exactly what the review is looking for --
grille depth, headlight internals, shut lines. Two pages at full width beat one
page nobody can judge from. Any wave over ~110 sheets needs the same treatment.

## MINI: generic nameplates, and a marque no nameplate can recover (2026-08-08)

Two problems SEAT did not have.

**MINI's own range is made of generic words.** One, Coupé, Convertible, Roadster,
Hatch and Traveller are all real MINI names and all useless as filter tokens —
feeding them in would admit any marque's convertible. The sweep did pull in a
Dodge Mini Ram Van, a Geely Mini Panda and a Wuling Hongguang Mini EV, so the
contamination is real. Pass only marque-specific tokens (Cooper, Clubman,
Countryman, Paceman, JCW, Moke, Marcos) and accept losing a bare-titled car.

**A classic Mini is often titled just "Mini".** 383 of the 432 candidates matched
`\bmini\b` while being mini skirts, mini golf, DJI Mavic Minis, Mac Minis and
about twenty Poppy Playtime "Mini Huggy" characters. No title rule recovers the
real ones. `--allow-uid` exists for this: force the genuinely ambiguous rows
through so a render settles them, because a sheet costs seconds and a title guess
costs a car.

**MINI splits badly**: 9 clean of 48, against SEAT's 24 of 40. Mini models tend
to carry one material over the whole shell, so a recolour would paint the glass
and lights with the body.

## Two filter bugs that silently ate real cars (2026-08-08)

Both found by testing the gate against cases it must catch, not by reading it.

1. **Diacritics were deleted, not folded.** `norm()` stripped every non-ASCII
   character, so "SEAT León MK2" became "seat le n mk2" and failed to match the
   nameplate "Leon". Uploaders write Citroën, Škoda, Río and Cee'd — an
   ASCII-only filter discards exactly the rows a native speaker uploads.
2. **Multi-word nameplates never matched anything.** The pattern was built as
   `re.escape(name).replace(" ", r"\s+")`; `re.escape` escapes the space to
   backslash-space, so the replace leaves the backslash behind and produces a
   pattern matching a literal backslash. "Leon ST", "John Cooper Works",
   "Morris Mini" and "Cee'd" matched nothing.

Cost: 4 real SEATs (León MK1, León MK2 ×2, Córdoba WRC) and 1 MINI (Morris Mini)
were thrown away as junk, and the first SEAT review page shipped to the owner
without them. This is the same failure class as the `\b`-inside-a-raw-string gate
already recorded in CLAUDE.md — written again eight hours later. **Prove a gate
fires against inputs it must catch AND inputs it must not, every time.**

## Triage

`pipeline/ingest/wave_triage.py` turns `gpu_wave` render logs into the triage
JSON the review page consumes. The material figures exist only in the log, so
this is the only way to recover them. Note the trap it guards: the index in
`[27/38]` is an offset into *the manifest that run was given*, so a wave rendered
in two passes has two index spaces and joining a top-up log to the original
manifest mislabels every row.

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

## Renault: bare-number nameplates collide with everything (2026-08-10)

Renault names a third of its historic range with bare numbers (4, 5, 8, 11, 12,
16, 18, 19, 21, 25), which is the numeric-collision trap CLAUDE.md already
records for "Peugeot 307 2008". Measured on this sweep, the damage is real but
not where it was expected:

- Years are SAFE. `\b` anchoring means `\b5\b` does not match inside "1984", and
  `\b4\b` does not match inside "4x4". No year was ever mislabelled as a plate.
- **Model designations are NOT safe.** The bare token `17` matched **seven WW1
  Renault FT-17 tanks**; `18` matched the `R.S.18` F1 car; `25` matched the 2005
  `R25` F1 chassis. All nine reached the manifest with a valid-looking plate and
  would have been downloaded and rendered. They are removed by an explicit
  out-of-scope pass, not by the nameplate filter.
- Renault is exceptionally dense in F1/racing uploads (R23, R24, R26, R28, R29,
  R202, RE40, RS19, A442) and in trucks/tanks/tractors (Magnum, Premium, Saviem,
  FT-17, AMC 35). Most are caught by `no-nameplate`; only the numeric ones slip.

**Two genuine cars were lost to token spelling and recovered by hand:**
- `4L` — the Renault 4 is almost always titled "Renault 4L", and `\b4\b` cannot
  match `4l`. **Six** rows were being dropped as no-nameplate. Add "4L".
- `Megan-E Tech` — a misspelt Mégane E-Tech normalises to `megan e`, which
  `\bmegane\b` cannot match. Add "Megan".
- `Renault Master2017` — digits glued straight onto the nameplate defeat `\b`
  entirely. No token fixes this class; it needs `--allow-uid`.

The `\s*` hyphen fix from the Honda wave works here as expected (A110/A-110,
R5/R-5 both match).
