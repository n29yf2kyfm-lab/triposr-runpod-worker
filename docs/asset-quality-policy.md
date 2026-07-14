# Asset quality policy (Phase 1)

Non-negotiable product rules, enforced in code:

| Rule | Enforced by |
|---|---|
| Never show a clearly wrong generation | `vehicle-resolver.ts`: generation conflict / year-out-of-range → immediate rejection; score <75 → unavailable |
| Missing model beats misleading model | resolver returns `unavailable` + honest disclosure instead of nearest make/model |
| Never claim exact trim on representative assets | `exact` band requires `exactTrim` + derivative match; generated assets are capped at `approximate` |
| DVLA colour is a family, not a paint | `normaliseColourFamily`; `oemPaintVerified` requires `oemPaintCode` (schema + audit + tests) |
| No openable parts without real geometry | schema + audit + tests: `supportsOpenableParts` requires separate-door/bonnet/boot flags |
| Generated (TRELLIS) assets are a fallback class | provenance `generated-from-reference`, accuracy `approximate`, −15 score penalty, AI disclosure mandatory |
| HTTP 200 ≠ valid asset | `technicalStatus`/`visualStatus` are separate, `pending` until real QC runs; audit warns on pending |
| Registration never persisted | identity type documents transience; no registration field in catalogue/schema/assets/reports |
| Claims backed by stored metadata | v2 schema: `sourceTitle` verbatim (required), provenance, licence, quarantine reasons, notes |

## Resolver bands
- **90–100** → `generation-correct` (or `exact` when exactTrim + derivative match)
- **75–89** → `representative`, disclosure shown
- **<75** → `unavailable`, disclosure shown; no asset returned

## Disclosures (verbatim, shown near viewer)
- exact: "3D model matched to this vehicle specification."
- generation-correct: "3D model matched to this vehicle generation. Some trim details may differ."
- representative: "Representative 3D model. Year, trim, wheels and styling details may differ."
- approximate-generated: "AI-generated representative model. Exterior details may differ from the real vehicle."
- unavailable: "A reliable 3D model is not currently available for this vehicle."

## Quarantine (2026-07-14 migration)
Stubs (rejected quality): Dacia Logan 86 KB, Kia Ceed 147 KB, Mini Countryman 113 KB,
Skoda Octavia 61 KB, Suzuki Jimny 44 KB. Removed from the serving catalogue.
Damaged/unverifiable: Discovery Sport ("Crushed" scan), Mercedes GLB ("2027 Lite"). Removed.
Heavy (>5 MB): Ioniq, i20, Accord, 2008, 407, Stinger — quarantined in v2, being optimised;
re-approve once under the 3 MB mobile budget.
Needs review: VW Golf — mesh generation unconfirmed (source title says 2021 GTI, body
resembles Mk7.5); kept serving in v1 by owner decision, blocked from `exact`/`generation-correct`
claims in v2 until confirmed.

## Rollback
Serving v1 backup: `car-renders/backups/catalogue.2026-07-14.json` and
`backups/catalogue.v1.2026-07-14.json` in-repo. Restoring = re-upload backup to
`car-renders/catalogue.json`.
