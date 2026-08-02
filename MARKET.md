# Market, Integration and Build-vs-Buy Research

Companion to [`COMPETITORS.md`](./COMPETITORS.md) (direct scan/measure competitors) and
[`PLAN.md`](./PLAN.md) (the build). This document covers the **construction software market we
sit next to**, the **open-source code we can legally ship**, and the **commercial reality of UK
material prices**.

Researched 2 August 2026. Figures are ex-VAT unless stated. Anything unverified is marked.

---

# Part 1 — The finding that matters most

**Every product in the construction-management category starts from a drawing that already
exists. Not one of them can produce one.**

```
[physical building] → ??? → [drawing/model] → takeoff → estimate → job → invoice
                       ↑
              NOBODY IN THE CATEGORY
```

- **Procore, Autodesk Forma/ACC, Fieldwire, Bluebeam, Countfire, Kreo, Autodesk Takeoff** — all
  require a PDF or a Revit/IFC model as input.
- **Buildertrend, Contractor Foreman, JobTread, Buildxact** — PDF in, 2D takeoff out.
- **Houzz Pro** — scans, but interior rooms only, and the output is a floor plan for *design*,
  never quantities.
- **Powered Now, Tradify, JobLogic, Simpro, Payaca** — the entire UK trade tier — have **no
  measurement capability of any kind.**

The gap is structurally worst exactly where the UK market is. **UK small-builder work is
overwhelmingly existing housing stock** — extensions, lofts, refurb, retrofit, repair. For that
work there is no drawing. The builder measures with a tape, sketches on a pad, and guesses.

The whole category is optimised for new-build-from-drawings, which is the *minority* of UK
small-builder revenue.

## The secondary gap that follows from it

**Quantities never reach a supplier.** Countfire's terminal output is an Excel file. Bluebeam's
is Quantity Link to Excel. There is no self-serve builders-merchant API in the UK. The last mile
— measurement to a priced, ordered basket — is unbuilt.

---

# Part 2 — What the market will actually pay

## 2.1 The UK price ceiling is real and it is low

| Product | Price | Note |
|---|---|---|
| Elec-Mate | **£6.99/user/mo** | Narrow wedge (certs) — proof that £7 works |
| ServiceM8 | **£0** ≤30 jobs, then £25/mo flat | Job-volume, not seats |
| YourTradebase | **£29** flat + £15/extra user | Single tier, no gates |
| Powered Now | **£28–£40** ⚠ conflicting sources | CIS + UK certificates |
| Tradify | **£34 / £37 / £44** | Owned by Access Group since Oct 2024 |
| JobLogic | **£45** Standard | Birmingham-based, incidentally |
| Buildxact | **£89–£262/mo** | Estimating-first, unlimited users |
| Payaca | **£299/mo minimum** | Has left this market — see below |

**Anything sold as a subscription must live under ~£50/user/month.**

## 2.2 But per-job pricing breaks that ceiling

| Product | Model | Price |
|---|---|---|
| **Hover** | per building | **$999/yr + $29–139 per project** |
| **EagleView** | per report | **$15–38, premium to $87** — and **already trading in the UK** |
| **Countfire** | prices on estimator-days saved | claims £18,000/yr saved per estimator |

**A sole trader who will not pay £50/month will pay £40 for a measured, priced survey of the
specific house he is quoting on Tuesday.** That is the pricing model this product should use.

## 2.3 Where the money actually goes

A UK sole-trader builder's real monthly spend:

| Line | Typical |
|---|---|
| Job management | £29 |
| Accounting / MTD | £16 (free with NatWest/RBS/Mettle via FreeAgent) |
| **Software subtotal** | **~£45–55** |
| **Lead generation** | **£100–150** (Checkatrade £60–120, £300–500 in cities) |
| **All-in** | **£150–300** |

**Lead generation is 60–80% of the wallet.** A builder who winces at £29/mo for software is
simultaneously paying Checkatrade £150. That tells you what he values: **work coming in and
money going out — not admin.**

Also: **many pay nothing at all.** Construction has ~748,000 UK self-employed (Q4 2025), the
most of any industry, and ~885,000 SMEs. The modal sole trader runs on paper, WhatsApp and a
Word template. We compete with *nothing*, which is harder than competing with Tradify.

## 2.4 Two market signals worth acting on

**Payaca vacated this segment.** It repositioned from general trades to solar/heat-pump
installers at **£299–£3,199/mo plus £1,500 onboarding**. Tradify was absorbed by Access, which
will optimise for cross-sell into its enterprise stack. **The independent small-builder end of
this market is thinner than it was three years ago.**

**Houzz proved the behaviour and left the value on the table.** Houzz Pro ships **Apple RoomPlan
LiDAR scanning** — a builder will scan a room with a phone, that is settled. They stopped at
interior floor plans for design and never connected it to quantities, materials or regs. Note
the pricing inversion: their **3D Floor Planner is in the FREE tier, and Mobile Room Scan is in
the top-priced Custom tier.**

---

# Part 3 — Open source we can legally ship

Licences were checked against actual `LICENSE` files, and the critical pieces were **installed
and executed on Linux/Python 3.11**, not merely read about.

## 3.1 The backbone: IfcOpenShell

| | |
|---|---|
| Licence | **LGPL-3.0-or-later** (the GPL parts are the Blender add-ons only) |
| Maturity | 2.7k stars, ~21,235 commits, v0.8.5 (Apr 2026), very active |
| Install | `pip install ifcopenshell` — manylinux wheels cp310–cp314, no compilation |
| Headless | **Verified: zero GL/X11 dependencies**, runs with `DISPLAY` unset |
| Size | 186 MB |

**Commercial use is fine.** The maintainers state explicitly that a proprietary product may ship
IfcOpenShell binaries. The condition: keep it an **unmodified pip dependency**, ship the LGPL
notice, and let users replace the `.so`. **Never vendor or patch it** — if we ever must patch,
that patch has to be published.

Nothing else is close. Everything else either wraps it (Cloud2BIM, Bonsai), or is the wrong
runtime (xBIM is .NET, web-ifc is JS).

### Two gotchas that will each cost a day

1. **Default units are MILLIMETRES.** `assign_unit(m)` with no arguments emits `.MILLI.`. For a
   metric point-cloud pipeline that silently scales the building by 1000×. Pass
   `prefix=None` explicitly.
2. **`IfcSpace` needs `aggregate`, not `assign_container`** — spaces are spatial *structure*,
   so `spatial.assign_container()` raises `AttributeError`.

## 3.2 Cloud2BIM is MIT — fork it

**Verified against the LICENSE file: MIT, not GPL as several sources claim.** That is the single
most commercially valuable finding here — MIT means we can fork, close, and ship.

- ~4,700 LOC, published in *Automation in Construction* (2025), [arXiv:2503.11498](https://arxiv.org/abs/2503.11498)
- Density-analysis + morphological segmentation, **deliberately avoids RANSAC**, handles
  non-orthogonal geometry
- **Verified end to end**: a synthetic 259,680-point room produced a structurally complete IFC4
  in **5.98 seconds** — 4 walls, 2 slabs, an opening with a working boolean cut, a space, a door

### Three blockers for containerising it

1. `requirements.txt` **cannot pip-install on Linux** — it pins `pywin32==310`. Strip it.
2. **Hard-crashes headless on LaTeX** — six sites set `plt.rc('text', usetex=True)`, and it
   fails *after* segmentation completes, losing the whole run. Patch to `usetex=False`,
   `MPLBACKEND=Agg`.
3. `import e57` is unconditional even when E57 input is disabled.

**Do not adopt its `generate_ifc.py`** (1,526 LOC of hand-rolled IFC). Keep its segmentation,
write the export against the maintained `ifcopenshell.api`.

Note the authors sell an automated "Cloud2BIM-AI" commercially — **the open version is
deliberately the weaker one**, and opening extents came out visibly wrong in testing (door Z
extent 0.00–2.94 against a true 0–2.1). Treat openings as approximate.

## 3.3 The rest

| Project | Licence | Verdict |
|---|---|---|
| **laspy** 2.7.0 | BSD-2 | Ship it. Pure Python, 0.7 MB, LAS/LAZ |
| **pye57** 0.4.19 | MIT | Ship it. E57 from terrestrial scanners, 32 MB |
| **PDAL** 3.5.5 | BSD-3 | For huge/tiled clouds and reprojection |
| **web-ifc / ThatOpen** | MPL-2.0 | Viewer only. File-level copyleft — fine unmodified |
| **Speckle** (`specklepy`) | Apache-2.0 | Clean, but server has proprietary EE modules |
| **Open3D** 0.19.0 | MIT | **Works headless but costs 1,066 MB** and needs `libgl1`, `libx11-6`, `libxcb1` on a slim image. No wheels past cp312. Use sparingly |
| **xBIM** | CDDL | .NET. Wrong runtime. Ignore |
| **Bonsai / BlenderBIM** | **GPL-3.0+** | **Do not link.** Its useful logic is a thin layer over the LGPL API we already call. Trap: `pip install bonsai` installs an unrelated LDAP library |

## 3.4 The ML weights trap — important

**Mask3D's code is MIT. Its checkpoints are not usable.** They are trained on **ScanNet**
(non-commercial Terms of Use) and **S3DIS** (separate signed agreement). ScanNet++ states
commercial use is "strictly prohibited" and **binds your employer** if you are a for-profit
entity. **An MIT code licence does not launder the weights.**

This is the same trap already caught once on this project with MapAnything, where
`facebook/map-anything` is CC-BY-NC and only `facebook/map-anything-apache` is commercial.

**Conclusion: there is no commercially-usable pretrained 3D indoor segmentation model.** Any ML
component must be trained on data we own or on permissive synthetic data — or we stay geometric.

## 3.5 What has NO open-source option — build from scratch

1. **Roof geometry from LIDAR → IFC.** Cloud2BIM is strictly indoor; a pitched roof breaks its
   density-band model. Our `roof.py` is already ahead of the open-source state of the art here.
2. **Phone-scan cleanup.** Everything open source assumes clean, gravity-aligned, metrically
   scaled terrestrial scans. Drift, scale validation and ARKit noise are entirely ours — and
   likely where most of the engineering goes.
3. **Accurate openings.** Robust door/window extraction is unsolved in open source.
4. **MEP/pipe/cable inference.** `ifcopenshell.api.system` can *represent* systems; nothing
   open-source *infers* topology from a cloud. **The X-ray is fully greenfield** — which is
   exactly why it is the wedge.
5. **Room semantics.** You get `IfcSpace` polygons; naming and classifying them is unsolved.

---

# Part 4 — UK material prices: the commercial reality

## 4.1 There is no public merchant API. None.

| Merchant | Public API |
|---|---|
| Travis Perkins | **No.** Internal GraphQL exists; `robots.txt` explicitly `Disallow: /resourceapi` |
| Jewson (STARK) | No |
| Selco, Wickes, Screwfix, Toolstation, B&Q | No |

The Travis Perkins **app** is the tell: it lets a customer "check and order stock at their
personal trade prices in real time." A per-customer pricing endpoint exists behind mobile auth.
That is the only path to real trade prices, and it is private.

## 4.2 Affiliate feeds do not solve it

Screwfix's programme is **closed to new applicants** (1%, 14-day cookie). B&Q runs on impact.com
(≥2%), Travis Perkins and Wickes on Awin (TP 3%). Joining Awin is free.

**Three killers:**
1. **They are retail prices, not trade prices** — useless for a builder on account terms.
2. **Awin publisher terms require feeds be used to promote that advertiser via affiliate links.**
   Using a feed as a cost database inside a paid estimating tool is outside the grant and is a
   plausible breach.
3. **Coverage is wrong** — no Jewson, Selco, Buildbase, Keyline or MP Moran, which is what a
   Birmingham builder actually buys heavy side from.

*This corrects the earlier assumption in this project that affiliate feeds were the bulk-price
answer. They are not. They are retail, and the terms do not permit the use we wanted.*

## 4.3 How UK trade pricing actually works

```
LIST PRICE
  → TRADE DISCOUNT      ~5–20%  automatic on account opening
  → DISCOUNT MATRIX     per product group, per customer — NOT a single %
                        heavy/aggregates 15–25% · plumbing/electrical 20–35%
                        timber 15–30% · tools 10–20%
  → VOLUME/SPEND TIER   +3–5% (£2–5k/mo) · +5–10% (£5–20k/mo)
  → PROJECT PRICE       quoted per job >£5–10k, locked for the duration
  → ANNUAL REBATE       3–8% of spend, paid as credit
```

**It is bespoke, not "X% off list."** Two builders in the same Birmingham branch pay different
prices for the same block. Net effective discount runs **15–40%** off retail.

**The product consequence:** any generic price database is wrong for every individual user, and
wrong in a direction they can feel. The builder knows his own blocks price. Show him a list
price and you lose credibility on the first screen. **This is why the price-list importer and
invoice ingestion are the right architecture** — they learn *his* matrix from *his* paperwork.

## 4.4 The one route that works

**Per-customer trade-account integration, brokered with merchant consent.** Proven in production:
**Simplementary/Nexana** deliver Travis Perkins, Wolseley, Rexel, Screwfix and Toolstation
catalogues into Simpro with daily price updates reflecting **the customer's own active discount
matrix**, at **£12.50–15/month per supplier**. **Trimble Luckins** does the same at industrial
scale for MEP — 1m+ SKUs, live API, ETIM-classified, 50 years of relationships.

Requirements:
1. **A commercial agreement with each merchant group.** ~8 matter for Birmingham: Travis Perkins
   Group, STARK UK (Jewson), Selco, Wickes, Kingfisher (Screwfix/B&Q), Toolstation,
   Wolseley/City Plumbing, Huws Gray/Buildbase. **This is BD work, not engineering, and it is
   the moat.**
2. **The builder's own account credentials, with his explicit authorisation** — structurally
   identical to open banking. The customer consents; we act as his agent. Clean legal basis.
3. **Cross-merchant product normalisation.** Lean on **ETIM** and the **BMF/NMBS Industry Data
   Pool** (JV announced Apr 2025, non-profit, shareholder model **open to software providers**).
   NMBS already pushes price changes to 1,150+ merchants in one update. **Becoming a shareholder
   in that JV is the highest-leverage single move available in this space.**

**Scraping stays off the table**, and now for a second reason: *Ryanair v PR Aviation* (CJEU)
established that even where no database right subsists, a site owner can enforce browse-wrap
terms contractually, with injunction and damages. Add TP's explicit `robots.txt` disallow, and
the fact that scraped prices are **retail, not trade** — all the legal risk for data that is
wrong anyway.

## 4.5 Free UK open data — and its hard limit

| Source | Cadence | Licence |
|---|---|---|
| **DBT Construction Material Price Indices** | Monthly, ~09:30 first working day, data 2 months prior | **OGL v3.0** |
| **ONS Construction Output Price Indices** | Quarterly | **OGL v3.0** |
| **BCIS (RICS)** | The real dataset | **£67,500/yr** (verified, TfL 2025–26) |

Latest CMPI movement: All Work **+5.4% YoY to May 2026**; New Housing +3.9%; R&M +4.6%.

**The hard limit:** CMPIs derive from BCIS PAFI, which derives from ONS Producer Price Indices —
**factory-gate prices from manufacturers.** They are indices with **no £/unit at all**. Useful to
*escalate* a price we already have; useless to price a job.

**There is no free source of £/unit UK material prices. Not one.**

---

# Part 4b — The 2D drawing gap, and whether Togal's moat is real

This was named in `PLAN.md` as our biggest capability gap. The answer splits cleanly in two, and
the halves have opposite verdicts.

## Assisted takeoff — buildable in weeks

**OpenTakeoff** — https://github.com/Kentucky-ai/opentakeoff — **Apache-2.0**, and the single
most relevant find in this whole research pass. React + pdf.js, entirely client-side.

Already implements: one-click flood-fill room tracing, manual trace with 45°/90° lock, linear
measure, counts, **per-sheet scale with auto-detect from drawing notes or manual calibration**,
multi-page plan sets, and a scanned-plan fallback via adaptive thresholding. Exports CSV, JSON,
XLSX and marked-up PDFs. **Ships an MCP server**, so an agent can load a plan, read the title
block and set scale.

Caveat, stated plainly: 46 stars, single-author velocity, strongly AI-authored style, snap
flagged beta. **Read the geometry core before adopting.** But it was being committed to on the
day of this research, and as a starting point it beats every research repo below.

**Supporting libraries:**

| Library | Licence | Verdict |
|---|---|---|
| **pdfplumber** | **MIT** | The Python workhorse. Exposes `.lines`, `.rects`, `.curves`, `.chars` with coordinates. Machine-generated PDFs only, no OCR |
| **ezdxf** | **MIT** | DXF read/write, full entity model, actively maintained. **Cannot read DWG** |
| **PyMuPDF** | **AGPL-3.0** | 10–50× faster — but AGPL means a hosted SaaS must open-source or buy a commercial licence. **Default to pdfplumber** |
| **LibreDWG** | **GPL-3.0+** | Reads DWG, but viral. Only viable behind a process boundary. Avoid |
| **dxfgrabber** | — | **Dead** — deprecated 2023, author says use ezdxf |
| Tesseract / PaddleOCR | Apache-2.0 | Both fine commercially |

## Full automation — a real moat, but not an algorithmic one

**Every high-quality floor-plan dataset is non-commercial.** That is the actual barrier.

| Dataset | Licence | Usable? |
|---|---|---|
| **CubiCasa5K** | **CC BY-NC 4.0** | ❌ Dataset *and* reference model |
| **FloorPlanCAD** | **CC BY-NC 4.0**, and authors don't own the drawings' copyright | ❌ Worst of both worlds |
| **LIFULL HOME'S** (Raster-to-Graph) | Academic application via NII | ❌ |
| **ResPlan** | **data CC BY 4.0, code MIT** | ✅ **The only large commercially-licensable corpus found** — 17,000 plans, vector geometry + room graphs, metric scale |

The published accuracy numbers are damning for anyone hoping to call a frontier model:

- **AECV-Bench** (Jan 2026, 120 real floor plans, tested across Gemini/GPT/Claude/Grok/Qwen):
  OCR reaches **0.95**, but **symbol understanding and counting sit at 0.40–0.55** — doors and
  windows specifically. Authors recommend **human-augmented workflows, not full automation.**
- **DrawingVQA** (CVPR-F 2026, Issued-for-Construction drawings): **GPT-4o 48.9%** — from models
  that pass construction certification exams at ~90%.

**Togal's own "98%" does not survive contact with its source.** It traces to a University of
Kansas study limited at the time to *architectural* drawings, structural out of scope. The
peer-reviewed comparison against On-Screen Takeoff reports **~70% time saving with accuracy
within a 5% margin** — a different and far more honest claim. A GC reports Togal at **~85% on
residential floors and ~60% on retail podium levels.**

**Their moat is proprietary labelled drawings, a review UX estimators trust, and insurer
relationships — not a secret algorithm.** We do not need to replicate it. We need assisted
measurement that saves an hour a job.

## Honest accuracy expectations

| Scenario | Realistic |
|---|---|
| **DXF/DWG** with layers intact | Near-exact. Errors are interpretation, not measurement |
| **Vector PDF**, correct scale, operator clicks rooms | **Sub-1%.** This is arithmetic, not AI |
| Vector PDF, **auto**-detected scale, unconfirmed | **Bimodal and dangerous** — right, or 100% wrong |
| Vector PDF, auto room detection, residential | **~80–90%** of rooms |
| Scanned/photographed PDF, auto | Promise nothing. Route to manual trace |
| **Counting** doors/windows automatically | **40–55%.** Unusable unattended |

**Scale calibration is the highest-leverage single feature.** A wrong scale is a 100% error on
every quantity; a wrong wall detection is 2%. OCR the title block, cross-check against a
dimension string, **and always show the operator the derived scale before applying it.**

**Market it as time saved (60–70%), never accuracy (98%).** That is what the peer-reviewed
evidence actually supports.

## Before any of this — measure the inbound

**What fraction of real jobs arrive as vector PDF versus flattened scans?** UK Planning Portal
downloads are frequently raster, which destroys the vector path entirely. That single
measurement decides whether this is a geometry product or a CV product — very different budgets
— and it is a day's work.

## Xactimate ESX — a dead end, and probably the wrong requirement

- The container is a ZIP, but the payload `XACTDOC.ZIPXML` uses a **non-standard compression
  wrapper that 7-Zip/WinZip cannot read.** "It's just a zip of XML" is half true and the wrong
  half.
- **No public schema. No working open implementation.** A GitHub-wide search for "xactimate esx"
  returns two repos, one of which is an empty 2018 repo titled *"Anyone know how to make .esx
  files without the software xactimate?"*
- magicplan, DocuSketch, Hover and Matterport all generate ESX under **signed Verisk
  agreements** with keycode-level enablement. DocuSketch signed a *multi-year* deal in March 2026
  specifically for this.
- **Verisk does publish UK pricing** (quarterly, 9 UK regions, 32 trades, 50,000+ items) so
  Xactimate exists here — but the ESX ecosystem is North American and **no evidence of a broad UK
  carrier mandate was found.**

**Three routes, in order of sanity:** buy it per-report (**1ESX at $10.99**) and pass through at
cost; apply to Verisk's third-party programme; or reverse-engineer it — weeks of work,
unverifiable without a keycode, obsolete the moment Verisk changes the format.

**Do first: ask three UK insurance/restoration clients whether they need `.esx` or would accept
a structured PDF schedule.** That may delete the workstream entirely.

## UK cost data — the £185 route

| Source | Cost | Usable in product? |
|---|---|---|
| **BCIS** | £67,500/yr verified (TfL) | ❌ No redistribution licence |
| **Spon's 2026** | **£185** | ❌ Reference for your own team only — ingesting the rates is copyright + database-right infringement |
| **NSR** (Gordian) | Commercial | ❌ Same |
| **Uniclass 2015** | **Free, CC BY-ND 4.0** | ✅ **Explicitly permits commercial projects.** Use as the classification spine |
| **ONS COPI / DBT indices** | **Free, OGL v3** | ✅ Indexation only |
| **RICS Data Standard** | **MIT** | ✅ But 24 stars, near-dormant since 2022 |

**CWICR** (55k work items, advertises a GBP track) deserves a specific warning: **CC BY-NC**,
and its GBP figures are **World Bank PPP repricing of Russian/Chinese/Vietnamese/Brazilian
norms.** No UK client should ever see those numbers. The *structural* idea — separate the
invariant labour/material norm from the volatile money — is good and worth copying. The numbers
are not.

**NRM2 has no official machine-readable schema.** Encode the work-section hierarchy ourselves,
keep the copyrighted rules text out of the product, map to Uniclass. Days, not a project.

**Recommended: £185 total.** Own norms from completed jobs + live trade prices + ONS/DBT
indexation + Uniclass classification. One copy of Spon's as a sanity check for our eyes only. A
builder-specific library built from his own history beats a generic national average — and it is
defensible when a client challenges a price.

---

# Part 5 — Integration targets

Ranked by tractability. The lesson from **OpenSpace** is the template: be the reality-capture
layer that syncs *into* the incumbent, and let the incumbent keep the workflow.

| Target | Why | Gate |
|---|---|---|
| **Procore** | Free dev account, **auto-provisioned sandbox with seed data**, OAuth 2.0, mature REST, real marketplace distribution. **UK is their #2 market.** They bought Novorender/FlyPaper for coordination — **not capture** | Marketplace approval |
| **Fieldwire** | Documented REST, plan-upload endpoints, and **ships an `llms.txt` + OpenAPI spec** — agent-integrable in an afternoon. **Has a BIM viewer but no way to create a model** — we fill their exact hole | API access needs a sales call |
| **Autodesk Platform Services** | For output: emit IFC/RVT into a client's ACC account | **Metered.** 0.5 tokens/complex conversion; free tier hard-stops **17 Aug 2026** |
| **Xero** | Not in the category, but the actual centre of gravity — the *only* integration Powered Now lists | Open |
| **JobLogic / Simpro** | Public REST + OAuth2, zero measurement, no intent to build it | JobLogic needs IP allowlisting — awkward for serverless |
| **Bluebeam Studio** | Asymmetric in our favour: we can push measurements in as markups; **they have no public API to pull takeoff out** | Devs need Core+ licences |

**Do not bother:** Tradify (no public API, no webhooks, no Zapier), Contractor Foreman (Zapier
limited to customers/leads), Countfire (Excel only), Houzz Pro (closed), Payaca, Buildertrend
(claimed but undocumented).

**Compete, don't integrate:** Hover and **EagleView, which already has a UK operation**.

---

# Part 6 — What to give away

1. **Takeoff itself.** Buildertrend gates it above entry tier; Bluebeam gates count/volume behind
   **$330/yr**; Autodesk charges **$1,250/user/yr**; Kreo **£125/user/mo**. **If quantities fall
   out of reconstruction as a by-product, the marginal cost is ~zero and we give away what four
   companies charge four figures for.**
2. **The 3D model.** Houzz has it backwards — free planner, paid scan. **Give away the scan and
   the model; charge for what the model lets you do.** A free 3D model of your own house is the
   most shareable acquisition asset in this market.
3. **API access with no sales call.** Fieldwire gates it behind sales; Kreo at Enterprise only.
   **A free, documented API with an `llms.txt` costs nothing and is how other people's agents
   integrate you in 2026.**
4. **Data export.** *"Once your information is inside their system, retrieving it later is a
   massive challenge"* is a verbatim Buildertrend review; PlanGrid users have **no automated
   migration path at all**. One-click IFC/glTF/CSV/PDF export is a weapon in a category with a
   documented lock-in reputation. Say it on the pricing page.
5. **No per-seat pricing.** A small builder's "team" is his mate and his son-in-law. **Price per
   building scanned.**
6. **No onboarding fee.** Procore charges **$50k–150k** in year one; Premier **$25,000**; Payaca
   **£1,500**; Simpro **£6k–12k**. *"Scan a house in ten minutes, no onboarding, no setup call"*
   is a positioning statement half this category structurally cannot make.

---

# Part 7 — Regulation: the wedge is not the one everyone talks about

## The Building Safety Act mostly does not apply to our customer

- **Golden thread / Gateways** bind **higher-risk buildings only** (≥18m or ≥7 storeys, ≥2
  dwellings). Our builder will never touch one. That demand accrues to PlanRadar/Zutec/Asite
  selling to tier-1s.
- **Building Safety Levy** starts 1 Oct 2026 but **exempts sites under 10 dwellings.**

**The one real hook is Part 2A** (SI 2023/911, in force 1 Oct 2023): dutyholder and competence
duties on **all building work requiring building regulations approval in England** — ordinary
extensions and lofts. The contractor must plan, manage and monitor for compliance and
**evidence competence**. Nobody sells a small builder a tool that produces that evidence pack,
and **a scan-based product generates dated, dimensioned as-built evidence as a by-product**.

But be honest: enforcement is currently light, so felt pain is low. **Treat compliance as a
retention feature and a trust signal, not the acquisition wedge.**

## The wedge that is actually live: MTD for Income Tax

- **6 April 2026:** mandatory for sole traders with gross income **>£50,000** — quarterly digital
  filing. **This is live now.**
- **April 2027: £30,000. April 2028: £20,000** — which captures effectively the entire trade.

Dated, unavoidable, hits precisely our customer, and is causing them to buy software *this tax
year*. **None of the four UK job-management products lead with it.** It argues for clean
Xero/QuickBooks/FreeAgent integration from day one rather than trying to be the accounting
system.

---

# Part 8 — What this changes about our plan

| Finding | Consequence |
|---|---|
| Nobody in the category can capture a building | Our position is not "better takeoff" — it is **the only tool that starts from the building** |
| Per-job pricing beats subscription for sole traders | Price **per building scanned**, not per seat. Hover/EagleView proved £15–140 works |
| Affiliate feeds are retail-only and contractually restricted | **Drop them as the bulk-price plan.** The importer + invoice ingestion is now the primary route, not the fallback |
| Trade pricing is a per-customer matrix | A generic price book is wrong for every user. Learning *his* prices from *his* invoices is the only credible approach |
| Cloud2BIM is MIT and works | Fork it for Phase 3, keep segmentation, rewrite the IFC export |
| IfcOpenShell is LGPL and headless-clean | Backbone confirmed. Keep it an unmodified pip dependency |
| No commercially-usable 3D segmentation weights | Phase 3/4 stay geometric, or we train our own |
| Roof-from-LIDAR has no open-source equivalent | **We are already ahead of the open state of the art here** |
| MEP inference is fully greenfield | Confirms the X-ray as the defensible wedge |
| MTD ITSA is forcing software adoption now | Xero integration is worth more than any BSA feature |
| OpenTakeoff is Apache-2.0 and already works | The 2D drawing gap closes in **weeks**, assisted — not the multi-month project assumed in `PLAN.md` |
| Frontier VLMs count doors at 40–55% | **Do not promise automatic recognition.** Assisted measurement with operator confirmation |
| Togal's "98%" is a limited study; peer review says 70% time saved within 5% | Market **time saved**, never accuracy |
| Every floor-plan dataset except ResPlan is non-commercial | Same trap as MapAnything and ScanNet. **Check dataset licences before any training** |
| ESX needs a Verisk agreement | **Drop it from Phase 7.** Buy per-report at $10.99, and first check UK clients even want it |
| Spon's/BCIS/NSR cannot be ingested at any sane price | Own norms + live trade prices + free indexation. **Total cost £185** |

---

## Verification gaps

Carried forward honestly rather than presented as fact:

- **Powered Now pricing** — Capterra/GetApp UK say £28/£32/£40; the vendor's own indexed page
  suggests £15/£25/£37. powerednow.com returned HTTP 503 on four attempts.
- **Simplementary/Nexana** — the core claim that they deliver *the customer's own negotiated
  matrix pricing* rests on a reseller's marketing copy. Simpro Marketplace pages returned 503.
  **Whether these use official merchant APIs or sanctioned scraping is unverified, and it
  materially affects whether the route is replicable.**
- **Autodesk ACC → "Forma" rename (March 2026)** — reported by two third-party sources, not
  confirmed on autodesk.com.
- **Buildertrend, Tradify, Payaca, Houzz Pro APIs** — no public developer documentation found
  either way.
- **BMF/NMBS Industry Data Pool commercials** — no published prices or software-provider tier.
  Worth a direct approach to BMF.
- **UK trade software market share** — no credible public data exists. The only hard number is
  Tradify's ~20,000 customers across UK/AU/NZ at acquisition. **Disregard any market-share
  percentage you read.**
- Much of the "best UK trade software" search space is **AI-generated affiliate content** —
  25+ such sites were hit during this research, several citing each other. That pollution is
  itself a signal: paid acquisition in this category is expensive and organic discovery is
  broken.
