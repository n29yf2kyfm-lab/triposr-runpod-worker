# Catalogue identity: the fix plan (2026-08-25)

Written after the Yaris 12-plate investigation (see CLAUDE.md "IDENTITY, NOT
MATERIALS, IS THE UNGATED FAILURE"). Reviewed by two external models; their
findings verified before inclusion. This is the plan of record.

## What is broken, in one paragraph

Asset year windows were stamped by a NAMEPLATE JOIN (`enrich_spec.py` copying
`build_index.py` tables by model name), so a 2001 Yaris carries 2020-2026.
The fabricated windows fail both ways: they REFUSE owners the correct asset
(a 2003 Yaris owner is denied the good 2001 XP10 we own) and PROMOTE wrong
assets (that same 2001 car scores 85 against a 2021 lookup, one stable-sort
tie-break — i.e. catalogue order — from being served). `yearEnd: null` is read
as 9999, so a 1967 Fiat 600 van matches a 2024 Fiat 600e with a year boost.
211 live entries have no yearStart, so no year gate fires for them at all.
Measured wrong-identity rate on live posters: 4/48 (8.3%). Drive side is not
recorded anywhere and our best approved Yaris is left-hand drive. Meanwhile
`generationConfirmed` is true on 1 of 760 and the resolver's generation
machinery — `inferGeneration(make, family, year)` + hard reject on conflict —
already exists and sits idle for want of data (alias table covers 12 families).

The principle for the whole plan: **wrong data -> no data -> verified data.**
Never leave confident fiction in a gating field; nulling it degrades honestly
to "representative + disclosure", which is the documented operating point.

## Phase 0 — resolver hardening (code only, hours)

1. **Kill `yearEnd ?? 9999`.** An open-ended window must not grant the +30
   year boost, and the year gate on an open window caps at a sane span
   (generation reference span, else yearStart+10). The 600-van case dies.
2. **Deterministic tie-break.** Score ties break by (generationConfirmed,
   qualityGrade, poster present, verification recency) — never by catalogue
   order. Today a 2001 car and a GR Yaris tie at 85 and array order decides.
3. **Quarantine the PROVEN-WRONG year fields** (data surgery, owner sign-off):
   null yearStart/yearEnd on the 14 live self-contradicting entries (title
   year outside stamped window; list in scratchpad audit/FINDINGS.json,
   includes toyota-yaris-2001-v1, volkswagen-beetle-v1, nissan-note-v1,
   jaguar-xf-v1...). Removes both false boosts and false rejections on the
   entries we can already prove are wrong. Everything else keeps its window
   until Phase 1 evidence arrives — no mass nulling on suspicion.
4. Extend the existing resolver test suite (34/34) to cover all three.

## Phase 1 — the identity audit (overnight GPU + one day of owner eyes)

Both reviewers converged on this independently; it reuses tooling we have.

1. **Batch-render all 1,044 live v2 entries** on the render worker: front34,
   side, rear34, plus HEAD-ON (drive side is only readable head-on with
   `glass_tint` lifted — proven on the Yaris). ~4 frames x ~8s OPTIX; est.
   $10-20 total. Store per-asset under car-renders/audit/identity/.
2. **Vision pass as CANDIDATE FINDER, never verdict** (project doctrine):
   per car — body style, door count, drive side, baked plates/watermarks,
   make/model plausibility, generation guess with confidence. Diff against
   stored fields.
3. **Exceptions only to the owner** as numbered contact sheets
   (`review_sheets.py` pattern). Expected flag rate 10-20% => ~100-200 cars,
   one sitting. Rank sheets by UK parc volume so the commonest cars are
   verified first.
4. Hard mismatches -> quarantine (reversible, `quarantineReason`, standard
   pattern). Everything reviewed gets an identity verdict recorded.

## Phase 2 — schema and data (the real fix, incremental)

1. **Per-asset verified identity**: `generation` + `generationConfirmed=true`
   only from render vs reference; `bodyStyle` from the render, never the
   title; **`driveSide` (new field)**; `identitySource` recording what
   verified it. Titles demoted to hints permanently.
2. **Years become DERIVED, never authored per asset**: yearStart/yearEnd are
   copied from the generation reference table ONLY where generationConfirmed.
   `enrich_spec.py`'s name-join is retired; the join key becomes
   (make, family, generation).
3. **Grow the alias generation table from 12 families to the top ~50 UK
   families.** This is public reference data (generation year bands), allowed
   under the accuracy rule the same way plate-band inference is; each row
   carries its source. This single table simultaneously powers the vehicle
   side (`inferGeneration` from the DVLA year) and the asset side (derived
   windows) — the resolver code needs no change to start hard-rejecting
   wrong generations once it is fed.
4. Where generation cannot be confirmed, the asset serves as representative
   with disclosure and NO year gating — honest, and already the documented
   MIN_SCORE=40 operating point.

## Phase 3 — stop it recurring (publishing gate, half a day)

1. `publish_batch` refuses a new entry without: verified generation,
   bodyStyle-from-render, driveSide, poster, and identitySource. Approval
   becomes approval FOR AN IDENTITY SLOT, not a global boolean.
2. Wave audit rubric gains two tiles: head-on (drive side) and the
   body-style call. Cost per car: one extra render.
3. **One serving file.** The legacy `catalogue.json` (760) misled this very
   investigation — 54% of reality. Mark it deprecated in-place and point all
   tooling at `resolver/catalogue.v2.json`.

## Phase 4 — coverage as a product signal (trivial, permanent)

Log every UNAVAILABLE resolution (make/family/year). Weekly rollup = the
sourcing roadmap, ranked by real demand. The XP130 Yaris — one of the most
common cars on UK roads — is currently a known hole nobody was counting.
Sourcing fills holes by parc volume, not by what Sketchfab happens to surface.

## What this does NOT include

- No generator work. The kill test settled that route (see DECISION.md); the
  machine's tooling serves Phase 1-2 on sourced assets.
- No relitigating owner rulings: opaque glazing and body-coloured tyres stay
  hard fails; material gates stay mandatory — they are downstream of identity,
  not replaced by it.
- ox's claim that the DVLA decode "almost certainly returns body style" is
  UNVERIFIED and looks wrong (VES returns wheelplan, not body style). The
  resolver accepts `bodyStyle` when the app supplies it; whether the app CAN
  is a Lovable-side question. Do not build on it until checked.

## Order and cost

    Phase 0   hours          code + tests, 14-entry surgery needs owner OK
    Phase 1   overnight      ~$10-20 GPU + one owner review sitting
    Phase 2   days, rolling  top-50 families first; each family lands alone
    Phase 3   half a day     then it cannot happen again
    Phase 4   an hour        then we know what to source, forever
