# Competitor Teardown — Stage 1

Full capability audit of every product in this space, turned into a build spec.

**Ground rule:** we build our own implementation of each capability from the open stack
(see `PLAN.md` §4). We do not copy anyone's code, assets, branding or scraped data — we
have no access to it and it would be infringement. Matching and beating a competitor's
*capabilities* is just competing, and that is what this document specifies.

---

## 1. The roster

### 1.1 magicplan — the closest overall rival

| | |
|---|---|
| **What** | Mobile-first field documentation and remodelling estimator |
| **Capture** | AR/LiDAR room scan, laser-assisted floor plans, photos, 360° media, **moisture readings**, structured notes |
| **Output** | 2D/3D plans, PDF reports, estimates, **ESX export to Xactimate**, FML to Cotality |
| **Estimating** | Material + labour estimates from the floor plan, tied to a **customisable price list**; quantities auto-link to detected room dimensions and tagged objects |
| **Price** | Sketch $12.99/mo ($129.99/yr); Report $39.99/mo ($399.99/yr); ~$30–40/project over quota |
| **Weakness** | Static price list maintained by hand. No services model. No live merchant pricing. No ordering. |

**Verdict:** owns scan → plan → takeoff → estimate. This is the product to beat, and
Supply Mode is how.

### 1.2 iGUIDE — owns the "see behind the walls" story

| | |
|---|---|
| **What** | Dedicated camera system (PLANIX R1) + processing service |
| **Capture** | 360° **time-of-flight LiDAR**, thousands of measurements/sec |
| **Accuracy** | **0.5% or better** on distance, **1%** on square footage, **~1 cm at up to 40 m** |
| **Speed** | 2,500 sq ft in **under 15 minutes** |
| **Output** | PDF, SVG, JPG; **CAD: DXF, DWG, RVT**; Xactimate Sketch |
| **Model** | Pay-per-project by square footage; unlimited free hosting, no subscription |
| **The pitch** | *"Scanning a property at every stage of a renovation creates 3D records of what's behind your walls, floors and ceilings"* |
| **Weakness** | **Requires their hardware.** Output is a panoramic photo record — not a measured, classified MEP model, and no AR overlay on the finished wall. |

**Verdict:** occupies our headline concept, but stops at photo documentation. Their
accuracy figures are the bar we must hit: **0.5% / 1 cm** is what "1:1" has to mean.

### 1.3 Matterport — the AI and data giant

| | |
|---|---|
| **Cortex AI** | Trained on **33 billion sq ft** of digitised space |
| **Property Intelligence** | Auto-measures rooms, labels them, calculates areas, **flags features like lighting and plumbing** |
| **Defurnish** | Generative removal of furniture and clutter |
| **Output** | 4K photos, schematic floor plans, guided video tours from one scan |
| **Weakness** | Real-estate marketing focus. Not trade, not estimating, not services. |

**Verdict:** we cannot match that training corpus and should not try. Their feature
flagging is shallow ("there is plumbing here"); ours is a measured pipe run.

### 1.4 Polycam / Canvas — the capture layer

| | Polycam | Canvas (Occipital) |
|---|---|---|
| **Capture** | LiDAR + photogrammetry + 360 | LiDAR |
| **Output** | OBJ, GLTF, FBX, STL, USDZ, **DXF, PLY, LAS, XYZ**; floor plans, as-builts, estimates, roof and claims files | **Scan-to-CAD from $0.14/sq ft** |
| **Price** | Free / $27 mo / $400 yr | Per-square-foot service |
| **Weakness** | Generic capture tool; no trade workflow, no pricing intelligence | It's a service with turnaround, not instant |

### 1.5 OpenSpace / Buildots / Cupix — progress capture

| | |
|---|---|
| **OpenSpace** | 360° hardhat camera, AI auto-maps images to the floor plan, **25,000 sq ft in 10 minutes**, **BIM Compare**, side-by-side date comparison, progress reports in 24–48 h |
| **Buildots** | 360° helmet cameras, AI compares to BIM **and schedule**, per-trade per-zone completion rates |
| **Cupix** | Digital twins, imports any point cloud source |
| **Weakness** | Enterprise, main-contractor focused. Documents *for the contractor*, not for the trade doing the work. Photo-and-compare, not a measured services model. |

### 1.6 Togal.AI / Hover — estimating

| | Togal.AI | Hover |
|---|---|---|
| **Input** | **2D plans and drawings** | Smartphone photos of a property |
| **Does** | Auto-detects and measures spaces in seconds, AIA measurement standards, **~98% on floor plans** | 3D model with measurements for roof, siding, walls, windows, doors; **Instant Design** (drop materials on the model live in front of the customer) |
| **Integrations** | eTakeoff | **50+** — Xactimate, JobNimbus, CompanyCam, AccuLynx, Beacon Pro+, ABC Supply |
| **Output** | Takeoff | PDF, Excel, **SKP, DXF, DWG** |
| **Price** | $299/user/month | $999/yr + per-project |
| **Weakness** | Reads plans, cannot scan | Exterior-first (interior added 2025); no services, no live pricing |

**Note:** Togal reads existing 2D drawings. **We have no equivalent capability** — a real
gap, since most jobs come with drawings.

### 1.7 uSurv homeSurvey — the free defect app

| | |
|---|---|
| **Price** | **Free** on iOS and Android |
| **Flow** | Quick Scan (10 min, key areas) or Full Survey (room by room) |
| **Detects** | Damp staining, cracking, mould, pointing condition, gutters, windows |
| **Grades** | Severity — urgent vs routine |
| **Scores** | **Property Health Score out of 1,000** |
| **Estimates** | Repair recommendations **with cost estimates** |
| **Monetises** | £24.99 for a shareable PDF report |
| **Weakness** | Photo-only. No 3D, no measured extent, no thermal, no idea what is behind the wall. Cost estimates are generic. |

**Verdict:** their free tier means **defect detection alone cannot be a paid feature.**
Their Health Score and severity grading are good ideas worth matching.

### 1.8 Materials marketplaces

| Product | Model | Weakness |
|---|---|---|
| **BuildBuddy** (UK) | "Skyscanner for building materials" | Starts from typed input |
| **BuyMaterials.com** (UK) | Basket → **1-click RFQ to local merchant network**; Universal Trade Accounts, 30-day terms | Starts from typed input |
| **Materials Market** (UK) | Bulky materials, one contact across suppliers | Narrow range |
| **PriceNailer** (UK) | **Live weekly tracker, 14 merchants** | Published prices, not paid prices; no ordering |
| **Kojo** (US) | **Sourcing Grid** — side-by-side comparison using current *and historical* pricing | US, enterprise |

**None start from a scan.** That is the gap.

### 1.9 Through-wall hardware

| Product | Does | Note |
|---|---|---|
| **Resolv InSite Pro** | Radar wall imaging; annotate and export; builds a "living digital history of hidden structural details" | Closest to our X-ray outcome |
| **Walabot DIY** | ~£100, ~100 mm depth | Consumer |
| Bosch D-tect / Hilti PS | Professional wall scanners | Established |

**Their structural advantage: these work on existing buildings with no prior scan.** Our
open/closed approach cannot serve that case at all.

---

## 2. Master capability matrix

Every capability found across the field, how we build it, and how we beat it.

### Capture

| Capability | Who has it | How we build it | Our upgrade |
|---|---|---|---|
| LiDAR room scan → parametric elements | magicplan, Polycam, Canvas | **Apple RoomPlan** (same free API they use) | Same baseline — no disadvantage |
| Photogrammetry fallback | Polycam | **MapAnything** (Apache 2.0, metric) | Works on non-LiDAR phones |
| 360° capture | OpenSpace, Buildots, iGUIDE | 360 camera support | Optional, not required |
| Dedicated hardware | iGUIDE, Matterport | **Deliberately not built** | Phone-only is a *feature*: no £4k camera |
| Thermal | — (Inspekt AI only) | FLIR One / Seek clip-on | Nobody in the trade segment has this |
| **Open-scan protocol (first fix)** | iGUIDE (photo only) | Dense close-range capture spec | **Measured services, not photos** |

### Geometry and output

| Capability | Who | How we build it | Our upgrade |
|---|---|---|---|
| 2D floor plan | all | RANSAC line vectorization | — |
| CAD export DXF/DWG/RVT | iGUIDE, Hover, Polycam | `ezdxf` + IfcOpenShell | **IFC too** — real BIM, which most lack |
| 3D mesh export | Polycam, Hover | `trimesh` — OBJ/GLB/FBX/STL/USDZ | Parity |
| Measurement tool | all | three.js | Parity |
| **Accuracy target** | **iGUIDE: 0.5%, 1 cm @ 40 m** | Must be validated against ScanNet++ laser ground truth | **This is the bar. Publish our number.** |

### AI and semantics

| Capability | Who | How we build it | Our upgrade |
|---|---|---|---|
| Auto room labelling / areas | Matterport, magicplan | RoomPlan + VLM | Parity |
| Feature flagging (lighting, plumbing) | Matterport | Services model | **Measured pipe runs, not "plumbing present"** |
| Defurnish | Matterport | Generative inpainting | Low priority — not a trade need |
| Defect detection | uSurv, Pointivo, Inspekt | **YOLO → SAM 2** | **3D-located with measured extent** |
| Severity grading | uSurv | Classifier | Match |
| **Health Score /1000** | uSurv | Weighted defect index | Match — good idea, worth copying the *concept* |

### Estimating

| Capability | Who | How we build it | Our upgrade |
|---|---|---|---|
| Takeoff from scan | magicplan | **QTO Buccaneer** on IFC | Parity |
| **Takeoff from 2D drawings** | **Togal.AI (98%)** | **GAP — we cannot do this** | Must add; most jobs arrive with drawings |
| Cost estimating | magicplan, uSurv, Hover | Rate card | **Live local prices, not a static list** |
| **Xactimate ESX export** | magicplan, iGUIDE, Hover | ESX writer | Required for insurance work |
| Integrations | **Hover: 50+** | Long tail | Years of BD — accept the gap |

### Progress and comparison

| Capability | Who | How we build it | Our upgrade |
|---|---|---|---|
| BIM compare | OpenSpace, Buildots | Our IFC model | Parity |
| Date-to-date diff | OpenSpace | Re-scan diff | **Measures change: crack +2 mm, damp +400 mm** |
| Per-trade completion | Buildots | Derived from services model | Parity |

### Materials

| Capability | Who | How we build it | Our upgrade |
|---|---|---|---|
| Price comparison | BuildBuddy, Kojo | RFQ to merchant network | **Driven from the scan** |
| Ordering | BuyMaterials | RFQ + partnerships | **Driven from the scan** |
| Historical price data | Kojo, PriceNailer | **Invoice OCR index** | **Real paid prices, not published list prices** |

### The X-ray — where nobody is

| Capability | Who | Us |
|---|---|---|
| Before-drywall record | iGUIDE (photos) | **Measured, classified MEP model** |
| See inside an existing wall | Radar tools | **Not served** — honest gap |
| AR services overlay | vGIS (civil/underground) | **Domestic, from own scan** |
| Services-aware pricing | **nobody** | **"Moving that soil stack costs £X"** |
| Defect + services correlation | **nobody** | **"Damp here, pipe joint 400 mm behind it"** |

---

## 3. What "combined and upgraded" looks like

One product, one measured model:

```
  CAPTURE          iGUIDE's rigour, on a phone instead of £4k hardware
     │             + thermal, which nobody in the trade segment has
     ▼
  MODEL            Matterport's semantics + real BIM (IFC) + services
     │
     ├──► PLAN     iGUIDE-grade drawings: DXF, DWG, RVT, IFC, PDF
     │
     ├──► PRICE    magicplan's takeoff, but priced live not from a static list
     │             + Togal-style drawing takeoff (gap to close)
     │             + Xactimate ESX for insurance work
     │
     ├──► SUPPLY   BuyMaterials' RFQ model, driven from the scan
     │             + Kojo's price history, from real paid invoices
     │
     ├──► CONDITION uSurv's Health Score and severity grading
     │             + 3D location and measured extent
     │             + thermal
     │             + repair costs at real local prices
     │
     └──► X-RAY    iGUIDE's "behind the walls" promise, actually delivered:
                   measured services, classified, overlaid in AR
```

**The five things no competitor can answer:**

1. "What's behind this wall?" — with a measured model, not a photo or a radar blob.
2. "What does this job cost?" — at live local merchant prices, not a static book.
3. "Order it." — straight from the scan.
4. "What's wrong with this building, and what's it cost to fix?" — defects located in 3D,
   correlated with services, priced locally.
5. "What changed since last time?" — measured, not eyeballed.

---

## 4. Where they beat us — honestly

Worth writing down, because pretending otherwise leads to bad decisions.

| Their advantage | Reality |
|---|---|
| **iGUIDE accuracy** — 0.5%, 1 cm @ 40 m from a dedicated ToF scanner | Phone LiDAR must be *proven* to get close. If it can't, the "1:1" claim is weakened. **Validate early against ScanNet++.** |
| **Matterport's 33bn sq ft corpus** | Unmatchable. Don't compete on generic scene AI. |
| **Hover's 50+ integrations** | Years of business development. Accept the gap; prioritise Xactimate. |
| **uSurv is free** | Defect detection cannot be a standalone paid feature. |
| **Togal reads 2D drawings at 98%** | We have **no** drawing-reading capability. Real gap — most jobs come with plans. |
| **Radar works on existing buildings** | Our X-ray needs a prior open scan. Structural limitation, not a bug to fix. |
| **All of them ship today** | We ship nothing yet. Every comparison above is a plan, not a product. |

---

## 5. Patent intelligence

Patents are the legitimate route to a competitor's actual method. The bargain is public
disclosure in exchange for protection — **reading them is free and intended**. Implementing
a live claim in a jurisdiction where it is granted is not. So they serve two purposes:
free technical education, and a map of what to design around.

### 5.1 Hover — the scaling problem, solved

Hover holds a substantial portfolio on smartphone-photo → 3D building models:

| Patent | Subject |
|---|---|
| **US20160224696A1** | **Scaling in a multi-dimensional building model** |
| US9437033B2 | Generating 3D building models with ground-level and orthogonal images |
| US10713842B2 | Real-time processing of captured building imagery |
| US11721066B2 | 3D building model materials auto-populator |
| US9330504B2 | 3D building model construction tools |

**US20160224696A1 addresses our number-one risk: metric scale from a phone camera with no
LiDAR.** Their claimed method:

1. Detect known architectural elements — **doors, windows, bricks** — by object or line
   detection.
2. Measure each element's **width-to-height ratio in pixels**.
3. Compare against a library of architectural standards within an error tolerance (~±10%).
4. Derive scale from the relative error of the matched ratio.
5. Apply the scale factor to the whole model.
6. A **weighted decision engine** averages multiple elements per image, improving
   statistically over time.

Their cited references are US standards: exterior doors at **36″×80″ (9:20 ratio)**, and
modular/Norman brick dimensions.

**This confirms the approach works** — and it is worth far more to us adapted to the UK,
where the standards are different and, in one case, better:

| UK reference | Dimension | Why it's good |
|---|---|---|
| **Brick coursing** | **4 courses = 300 mm exactly** (215×102.5×65 mm brick + 10 mm joint) | **The best scale reference in Britain.** National standard, on nearly every house, visible from any exterior photo, and self-averaging over many courses |
| Brick coordinating length | 225 mm | Horizontal equivalent |
| Internal door | 762×1981 mm | Near-universal domestic |
| External door | 838×1981 mm | Common |
| **Socket height** | **450 mm from finished floor** | **Building Regs Part M — mandated, so reliable indoors** |
| **Switch height** | **1200 mm** | Also Part M |
| Plasterboard sheet | 2400×1200 mm | On every first-fix site |
| Scaffold tube | 48.3 mm dia | Present on most exteriors mid-job |

Brick coursing is the standout: measuring across **twenty courses** rather than one door
averages out detection error and gives a far tighter scale estimate than any single object.
The socket and switch heights are regs-mandated, which makes them dependable *interior*
references — something the Hover patent, being exterior-focused, does not address.

**Design-around position.** Our primary scale source is **LiDAR depth**, which is metric
directly and touches none of this. The known-object method is only the **non-LiDAR
fallback**, we would implement it against UK standards and multi-course averaging rather
than their US ratio-library method, and "use a known-size object for photogrammetric scale"
has decades of surveying prior art. Even so: **get a patent attorney to clear the fallback
before shipping it commercially.** Note the patent was filed ~2015, so it runs to roughly
2035, and patents are jurisdictional — a US grant does not bind UK operation unless they
also hold UK/EP equivalents. Worth checking.

### 5.2 Matterport — 64 patents

A deep portfolio covering 3D capture, immersive navigation (including orbiting a model and
viewing an orthographic floor plan), and Cortex's deep-learning spatial understanding.

**Implication:** the crowded ground is *real-estate 3D tour presentation*. Our territory —
first-fix services capture, trade pricing, materials ordering — sits outside it. Another
reason not to chase Matterport's game.

### 5.3 Planitar (iGUIDE) — only 3 patents

Thin protection for the company whose concept is closest to ours. Their moat is **hardware
and accuracy**, not patent coverage.

**Business intel worth knowing: REA Group took a majority stake in Planitar in October
2025.** iGUIDE now has major property-group backing, so expect faster movement — and note
that REA is a *property portal* group, which points them further toward real estate rather
than trade work.

### 5.4 What to do with this

1. **Adopt UK brick coursing as the fallback scale anchor** — better than anything in the
   Hover patent, and free.
2. **Use socket/switch heights as interior scale anchors** — regs-mandated, unaddressed by
   their exterior-focused claims.
3. **Keep LiDAR as the primary scale path** so the patented method is never on the critical
   path.
4. **Clear the fallback with an attorney** before commercial launch.
5. **Read the rest of the Hover portfolio** — the materials auto-populator (US11721066B2) is
   relevant to Supply Mode and worth a full read.

---

## 6. Consequences for the build

1. **Accuracy validation moves early.** iGUIDE publishes 0.5% / 1 cm. We need our own
   number, measured against ScanNet++'s sub-millimetre laser ground truth, before making
   any 1:1 claim.
2. **Add 2D drawing takeoff.** Togal proves the demand and most jobs arrive with drawings.
   Currently absent from the plan entirely.
3. **Add Xactimate ESX export.** magicplan, iGUIDE and Hover all have it — it is the price
   of entry for insurance and restoration work.
4. **Adopt the Health Score.** uSurv's /1000 index and urgent-vs-routine grading are good
   product design worth matching.
5. **Never sell defect detection alone.** It is free elsewhere. Sell it bundled with 3D
   location, measured extent and real local repair pricing.
6. **Phone-only is positioning, not compromise.** iGUIDE and Matterport need hardware. Say
   so loudly.
7. **Ship something.** Every advantage listed here is theoretical until Phase 1 runs.
