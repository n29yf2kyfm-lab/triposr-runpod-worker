# UK compliance knowledge base

Learned from primary sources on 2026-08-14. Every fact below carries its
source. Where the codebase already implements a rule, the cross-check
says so; where the source contradicts the code, it is listed under
**Corrections** at the bottom — the point of this file is that the code
never argues with the document it was derived from.

Official PDFs read directly (downloaded from gov.uk assets):
Approved Documents O (2021), F Vol 1 (2026 edition), L Vol 1 (2021+2023
amendments), B Vol 1 (2019 + 2020/2022/2025 amendments, collated with
2026 and 2029 amendments).

---

## 1. The Approved Documents (England) — current editions

Source: https://www.gov.uk/government/collections/approved-documents

| AD | Subject | Latest shown |
|----|---------|--------------|
| A | Structure | 2013 |
| B | Fire safety (2 volumes) | 11 Mar 2025 (collated 2026/2029 amendments exist) |
| C | Site prep, contaminants, moisture | 2013 |
| D | Toxic substances | 2010 |
| E | Resistance to sound | 2015 |
| F | Ventilation | **2026 edition** (F1 dwellings) |
| G | Sanitation, hot water, water efficiency | Oct 2024 |
| H | Drainage and waste | 2010 |
| J | Combustion appliances | 2022 |
| K | Falling, collision, impact | 2013 |
| L | Fuel and power | 2021 ed. + 2023 amendments |
| M | Access | Oct 2024 |
| O | Overheating | 2021 (in force Jun 2022) |
| P | Electrical safety | 2013 |
| Q | Security | Nov 2024 |
| R | Electronic communications | 2022 |
| S | EV charging | 2023 |
| 7 | Materials and workmanship | 2018 |

## 2. Part K — stairs (private) — VERIFIED, code matches

Sources: AD K; https://www.stairplan.co.uk/regulations.htm et al.

- Max rise 220 mm, min going 220 mm, max pitch 42°. ✅ `buildable.py`
- 2R + G between 550 and 700 mm. ✅
- Headroom 2.0 m over the pitch line. ✅
- Landings top and bottom at least the stair width. (partially modelled)
- Handrail 900–1000 mm, at least one side. ❌ not modelled yet.

## 3. Part B Vol 1 — escape (para 2.10) — VERIFIED, code matches

Source: AD B Vol 1 PDF (gov.uk assets, 2019+2025 collated edition).

- Escape windows: unobstructed openable area ≥ 0.33 m², min 450 mm high
  AND 450 mm wide, bottom of openable area ≤ 1100 mm above floor.
  ✅ `buildable.escape()`
- Inner rooms permitted only as kitchen/laundry/dressing/bath/WC, or any
  room ≤ 4.5 m above ground WITH an escape window, or compliant gallery.
- Storeys > 4.5 m: protected stairway or alternative escape. ✅ (4.5 m
  limit modelled)
- Fire detection (Section 1): **minimum Grade D2 Category LD3** to
  BS 5839-6 (smoke alarms in circulation spaces forming escape routes).
  Large dwellinghouse of 3+ storeys: Grade A Category LD2. Heat alarms
  to BS 5446-2, mains with standby supply. ⚠️ see Corrections — our
  kitchen heat alarm is ABOVE the AD B dwelling minimum (good practice
  from BS 5839-6 LD2), and must be labelled as such, not as the minimum.

## 4. Part F Vol 1 (2026 edition) — VERIFIED, code matches

Source: ADF1_2026.pdf (gov.uk assets).

- Intermittent extract (Table 1.1): kitchen 30 l/s with hood to
  outside / 60 l/s otherwise; utility 30; bathroom 15; sanitary 6.
  ✅ `ventilation.py`
- Whole dwelling (Table 1.3): 1 bed 19, 2/25, 3/31, 4/37, 5/43 l/s,
  +6 l/s per extra bedroom, AND ≥ 0.3 l/s·m² of internal floor area —
  both conditions (i.e. the max governs). Single-habitable-room
  dwelling: 13 l/s. ✅ (the +6 rule and 13 l/s special case now known)
- Fans as high as practicable, ≤ 400 mm below ceiling; cooker hood
  650–750 mm above hob if unspecified.
- Background ventilators ≥ 1700 mm above floor (draughts).
- Internal doors: free area equivalent to a 10 mm undercut in a 760 mm
  door.
- Habitable room without openable window may ventilate through another
  room: permanent opening ≥ 1/20 of combined floor area + 10,000 mm²
  background ventilator in the outer room.

## 5. Part O (2021) — simplified method — READ IN FULL

Source: ADO.pdf (gov.uk assets), Tables 1.1–1.4.

Risk category: 'high risk' = defined parts of London (+ guidance for
central Manchester, Appendix C); 'moderate risk' = rest of England
(Birmingham is moderate). Cross-ventilation = openings on OPPOSITE
facades (corner-only does not count). Orientation is taken from the
facade with the LARGEST glazing area, for the whole building.

Table 1.1 — max glazing, % of floor area, WITH cross-ventilation:

| Orientation | High: dwelling / worst room | Moderate: dwelling / worst room |
|---|---|---|
| North | 15 / 37 | 18 / 37 |
| East  | 18 / 37 | 18 / 37 |
| South | 15 / 22 | 15 / 30 |
| West  | 18 / 37 | 11 / 22 |

Table 1.2 — WITHOUT cross-ventilation (moderate): N 18/26, E 18/26,
S 15/15, W 11/11. (High: N 15/26, E 11/18, S 11/11, W 11/18.)

Removing excess heat — minimum FREE AREAS:
- Cross-vent (Table 1.3): moderate = greater of 9% floor area or 55% of
  glazing area; bedrooms ≥ 4% of room floor area. (High risk: 6% / 70%,
  bedrooms 13%.)
- No cross-vent (Table 1.4): moderate = greater of 12% / 80%; bedrooms
  4%. (High: 10% / 95%, 13%.)
- High-risk locations additionally need shading (shutters, g ≤ 0.4
  glass, or 50° overhangs due south).

⚠️ Code gap (see Corrections): `buildable.overheating()` implements the
whole-dwelling moderate cross-vent percentages correctly (18/18/15/11)
but not the most-glazed-room check, the cross-ventilation test, the
free-area tables, orientation-by-largest-facade, or high-risk shading.

## 6. Part L Vol 1 (2021+2023) — VERIFIED, code matches

Source: ADL1 PDF (gov.uk assets), Tables 1.1 and 4.1.

Notional dwelling (target-setting) values — what `heatloss.py` uses:
wall 0.18, floor 0.13, roof 0.11, windows/glazed doors 1.2, opaque and
semi-glazed doors 1.0 W/m²K; party wall U = 0; openings capped at 25%
of total floor area; air permeability 5 m³/(h·m²)@50Pa; PV sized at 40%
of ground-floor area / 6.5 kWp for houses. ✅ all five U-values match.

Limiting (worst allowable) values, Table 4.1: roof 0.16, wall 0.26,
floor 0.18, party wall 0.20, window 1.6, doors 1.6, air permeability
8 m³/(h·m²)@50Pa.

## 7. Part M + electrics — VERIFIED with one wording fix

- AD M: switches, sockets, controls between 450 and 1200 mm above floor
  in new dwellings. ✅ `electrics.py` (450 sockets / 1100 switches).
- BS 7671 522.6.202 safe zones for concealed cables (horizontal/vertical
  from accessories, 150 mm zones at corners) — as documented in
  `electrics.py`. ✅
- Detection minimum is AD B's D2/LD3, not "Grade D1" — see Corrections.

## 8. Space — Nationally Described Space Standard

Sources: gov.uk NDSS PDF; designingbuildings.co.uk; urbanistarchitecture.co.uk

- Single bedroom ≥ 7.5 m², ≥ 2.15 m wide.
- Double/twin ≥ 11.5 m²; principal double ≥ 2.75 m wide, other doubles
  ≥ 2.55 m.
- Minimum GIA examples: 1b1p 37 m² (with shower), 1b2p 50 m²,
  2b3p 70 m²; storage counted: headroom < 900 mm not counted,
  900–1500 mm at 50% (storage only).
- NDSS applies only where the local plan adopts it (it's a planning
  standard, not a Building Regulation). Birmingham: check local plan.
- Cross-check our 3-bed demo: Bed 2 13.6 ✅, Bed 3 11.76 ✅ doubles;
  Master 17.92 ✅.

## 9. Planning — GPDO Class A (householder extensions)

Sources: gov.uk Technical Guide for householders (2019); Planning Portal.

- Single-storey rear: ≤ 4 m beyond rear wall (detached) / 3 m (other);
  ≤ 4 m high; with prior approval ("larger home extensions", not on
  designated land): 8 m / 6 m.
- Within 2 m of a boundary: eaves ≤ 3 m.
- Two-storey rear: ≤ 3 m beyond rear wall, ≥ 7 m from the rear boundary,
  roof pitch matching, upper windows side-facing obscure-glazed.
- Total coverage: ≤ 50% of curtilage (excluding original house).
- Side extensions: single storey, ≤ half the width of the original house.
- Materials to be similar in appearance.

## 10. Planning process, fees, councils

- Fees from 1 April 2025: householder application £528 (was £258);
  full application, new dwellings £578 per dwelling; annual CPI
  indexation (capped 10%) each 1 April thereafter.
  Source: lichfields.uk (Jan 2025) + council notices.
- Validation: national requirements (form, fee, location plan at
  1:1250/1:2500 with red line, site/block plan, existing+proposed
  drawings) + each LPA's LOCAL validation list — they differ per council.
- Birmingham City Council: publishes per-type checklists at
  birmingham.gov.uk/planningchecklists; CIL Additional Information
  Requirement Form for any new dwelling or 100 m²+ of new floorspace
  (Birmingham charges CIL). Local list revised via consultation
  (birminghambeheard.org.uk).
- Decision targets: 8 weeks householder/minor, 13 weeks major.

## 11. Future Homes Standard — the deadline that shapes everything

Sources: pinsentmasons.com, solarpowerportal.co.uk, kensa.co.uk (2025-26
reporting).

- Published; regulations phase in from 24 March 2027, full effect
  ~March 2028.
- ~75–80% CO2 reduction vs 2013 baseline; effectively no new gas
  boilers (low-carbon heating, mostly heat pumps); rooftop solar
  expected ≈ 40% of ground-floor area equivalent; higher fabric +
  ventilation standards.
- Consequence for this codebase: `heatloss.py` already notes emitters
  must be resized for low flow temperatures — under FHS that becomes the
  DEFAULT (design flow ~45 °C or lower, bigger radiators or UFH), and a
  gas-boiler assumption in any pricing model dates fast.

## 12. How architects actually deliver — RIBA Plan of Work 2020

Sources: riba.org PDFs; architectureforlondon.com; urbanistarchitecture.co.uk

Stages: 0 Strategic Definition · 1 Preparation & Briefing · 2 Concept
Design · 3 Spatial Coordination · 4 Technical Design · 5 Manufacturing &
Construction · 6 Handover · 7 Use.

- Planning application is normally submitted at the END of Stage 3
  (spatial coordination frozen); the pause for determination sits
  between 3 and 4.
- Building Regulations submission comes out of Stage 4 (technical
  design); Stage 4 often overlaps Stage 5 on small jobs.
- Small domestic jobs usually skip 0 and 7.
- Mapping for our pipeline: scan→model = Stage 1 survey; propose/regs
  gate = Stage 2–3; heatloss/ventilation/electrics packs = Stage 4
  content; pricing = tender support.

## 13. What a council judges design against — National Design Guide

Source: assets.publishing.service.gov.uk National_design_guide.pdf (2019/2021)

Ten characteristics: Context · Identity · Built form · Movement ·
Nature · Public spaces · Uses · Homes & buildings · Resources ·
Lifespan. Officers cite these (plus local design codes) in committee
reports; a proposal that can say "matching eaves line, matching brick,
window heads aligned with neighbours" is speaking their language.

---

## CORRECTIONS — where our code/docs must change (build phase)

1. **Part O is only one-third implemented.** `buildable.overheating()`
   has the correct moderate-risk cross-vent whole-dwelling percentages
   but is missing: most-glazed-ROOM limits (37/37/30/22), the
   cross-ventilation determination (opposite facades), Tables 1.2–1.4
   (non-cross-vent + free areas for heat removal), orientation taken
   from the largest-glazed facade (whole building, not per-facade), and
   high-risk shading. Free-area check also interacts with Part F purge.
2. **`electrics.py` docstring says "Grade D1"** — AD B's minimum for new
   dwellings is **Grade D2 Category LD3**; our kitchen heat alarm is
   above-minimum practice (BS 5839-6 LD2 direction), not the required
   baseline. Wording fixed; logic can stay (exceeding minimum is fine,
   claiming the minimum wrongly is not).
3. **Planning fee figures**: any pricing/summary output quoting £258
   for a householder application is out of date — £528 from 1 Apr 2025,
   CPI-indexed annually.
4. **Part F edition**: cite the 2026 edition (rates unchanged from 2021
   for our tables, verified line by line).
5. **Handrails** (Part K) are not modelled on the fitted stair.
6. **Whole-dwelling vent**: add the "+6 l/s per bedroom above five" and
   the single-habitable-room 13 l/s special case to `ventilation.py`.
