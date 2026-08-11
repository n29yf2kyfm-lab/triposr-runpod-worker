# AI Car-Damage Scanners — Teardown, and the Hybrid That Beats Them

Eight shipping apps were reviewed to answer one question: what does the best
possible AI vehicle-damage scanner look like, and what can this platform build
that none of them can? This is the spec that shaped the `damage/` worker.

**Ground rule (same as the building product's `COMPETITORS.md`):** we build
our own implementation of each capability. We do not copy anyone's code,
assets, branding or data — we have none of it. Matching and beating a
competitor's *capabilities* is just competing.

---

## 1. The roster

| App | Author | Core idea | The one thing it does best |
|---|---|---|---|
| **FairMoto** | Dmytro Mosnenko | Photo → detailed findings | **Evidence + hidden-damage probabilities + model-specific risks.** The bar. |
| **DAMAGE iD** | DAMAGE iD LLC | Fleet check-in/out | **Guided panel-by-panel capture, before/after, signed sign-off.** |
| **AutoScan** | Furkan Kucuk | Buyer inspection | **One headline condition score (46/100) + paint analysis + repair line items.** |
| **Detect Damage AI** | Mike Thorby | Trader scans | **Scan history / records, VIN + plate, credits.** |
| **Car Damage Scanner** | Alem Hodzic | Repair estimates | **Region-aware pricing ("local market prices") + VIN decode.** |
| **CarMark** | My Fortuna LLC | Inspection camera | **Fast capture + auto vehicle ID.** |
| **Inspectrai** | Kazim Caner Cam | Buyer decision | **Dead-simple 3-step onboarding + severity guidance.** |
| **Detect/Carmark/AutoScan** share | — | credits / IAP | monetization pattern: per-scan credits. |

### What each is really selling
- **FairMoto** sells *appraiser-grade reasoning*. Its screenshots show, per
  finding: panel + damage + `sev N`, an **Evidences** list ("visible panel
  deformation above wheel arch"), **Hidden damage** with probabilities ("ADAS
  camera/sensor damage · p=60%", "airbag sensor impact · p=25%"),
  **Model-specific risks** ("autopilot camera recalibration required"), a
  **repair range** ("700–1700 USD"), and **image-quality tags** ("water
  droplets", "reflection on panels", "good lighting"). Plus PDF export. This is
  the most sophisticated product in the set by a wide margin.
- **DAMAGE iD** sells *process and proof*. It is not really an AI product — it
  is a disciplined **guided capture grid** (Dashboard, Front, Pass-Front,
  Pass-Rear, Driver-Front…), a **going-out vs return** comparison, and a
  **signature acknowledgement** ("ACCEPT VEHICLE CONDITION"). It owns the
  fleet/rental/delivery workflow.
- **AutoScan** sells a *decision number*. The 46/100 gauge, paint tone/fade
  analysis, chronic-issue research %, and per-issue repair costs turn a scan
  into a buy/no-buy.
- **Car Damage Scanner** sells *a locally-accurate price*. Region select
  (US/EU/Asia), VIN decode, 1–5 photos → cost breakdown.
- The rest sell *convenience and records*: fast capture, auto ID, scan history,
  a credits wall.

### The universal gaps (every one of them)
1. **The result is 2D.** A box on a photo, a list, a PDF. None place the damage
   on a model of the car.
2. **Findings don't reconcile to a canonical panel taxonomy** across capture,
   pricing and reporting — so "Pass-Front" in one screen isn't the same object
   as "front left fender" in another.
3. **Capture completeness is manual** (DAMAGE iD) or **absent** (the AI ones
   accept a single photo and score it as if it were the whole car).
4. **Pricing is a black box** — a single number, no decomposition, no honest
   range, hidden-damage cost either omitted or folded in as if certain.

---

## 2. The winning feature set — the hybrid

Take the best column from each and make them share one model:

| Capability | Best-in-class source | In `damage/` |
|---|---|---|
| Evidence-based findings | FairMoto | `analyze.py` — evidence mandatory, enforced by the parser |
| Hidden-damage w/ probability | FairMoto | `analyze.py` + `repair.hidden_contingency` (risk-weighted, **separate** from the firm total) |
| Model-specific risks | FairMoto | `analyze.py` prompt; carried to report |
| 1–10 severity | FairMoto (`sev N`) | `taxonomy.SEVERITY_BANDS` — one scale everywhere |
| Headline condition score | AutoScan (46/100) | `severity.condition_score` — damage-subtracted, worst-capped, never averaged |
| Region-aware repair range | Car Damage Scanner | `repair.py` — parts + paint/labour × regional rate, honest low–high |
| Guided capture + gaps | DAMAGE iD | `quality.completeness` — tells the app which angles are still missing |
| Image-quality tags | FairMoto | `quality.py` — blocking vs qualifying, + optional pixel checks |
| Before/after diff | DAMAGE iD | `compare.py` — new / worsened / resolved, only the delta is chargeable |
| PDF-ready report | FairMoto, magicplan | `report.render_html` — self-contained, print-to-PDF |
| Records / VIN / credits | Detect Damage AI, CarMark | app-side (this is the analysis worker; the app owns accounts & billing) |

### The thing none of them have — 3D
This platform already turns a car photo into a **real 3D model**
(`trellis2/`). `fusion.py` pins every finding onto that model in a normalised
car frame, so the app shows a **rotatable car with the damage marked on it** —
the same object, inspected. A fleet manager, an insurer triaging a claim, and a
buyer 300 miles away all read a 3D map faster than a photo stack. That is the
premium wedge: not "another scanner", but *the scanner whose output is a 3D
condition twin*.

---

## 3. Design lines we hold (and they blur)

- **A guess is never presented as an observation.** Visible damage carries
  evidence; inferred sub-surface damage carries a probability and lives in a
  separate list; the report renders them differently. (Same principle the
  building product holds for measured-vs-inferred services.)
- **The worst finding caps the headline.** One shattered-windshield /
  bent-rail item cannot be averaged away by twenty clean panels — the failure
  mode of any mean-based score.
- **Coverage gaps are surfaced, not hidden.** A one-photo "inspection" reports
  25% coverage and asks for the missing angles, rather than scoring a quarter
  of a car as the whole.
- **Repair is a decomposable range, never false precision.** Every line shows
  its low/high method assumption; hidden-damage cost is a risk-weighted
  contingency shown apart from the firm estimate.
- **Before/after never over-charges.** A baseline panel not re-photographed
  reads as *resolved*, not *repaired*, and is never billed.

---

## 4. What this worker deliberately does NOT do

- **It is not the app.** Accounts, credits/IAP, VIN decode UI, scan history and
  the signature/e-sign flow (DAMAGE iD) belong in the product surface; this is
  the analysis + scoring + pricing + 3D-fusion + reporting engine behind it.
- **It does not fabricate condition records.** The signed "Accept Vehicle
  Condition" step is a legal artifact of the app, not something an AI should
  auto-approve. This worker reports condition; a human accepts it.
- **It does not claim pixel-exact 3D placement** — pins are panel-accurate and
  labelled `precision: "panel"`. Photo-to-mesh pixel registration is a later,
  heavier step, and the honest floor is stated rather than over-sold.

---

## 5. One-line verdict per app

- **FairMoto** — closest to right. We match its reasoning and add 3D, a
  worst-capped score, coverage gating, and a decomposable price.
- **DAMAGE iD** — best workflow, thinnest AI. We take its capture discipline
  and before/after, and put real detection behind them.
- **AutoScan** — good score, opaque method. We keep the gauge and make the
  number defensible.
- **Car Damage Scanner** — right instinct on regional pricing; we generalise it
  into a transparent parts+labour model.
- **The rest** — convenience layers. Fine features, not a moat.
