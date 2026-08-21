# BLENDER_COST — what hand-building premium cars actually costs

Research date **2026-08-21**. Every price below was fetched from the vendor or a named
authorised reseller on that date unless marked **NOT ESTABLISHED**. Nothing here is
recalled from memory. Licence terms are recorded as a plain field, not as a gate
(standing owner instruction).

---

## 1. THE BILL, AND THE RECOMMENDATION

### The one-line answer

**The tools are free, and for the first time they are actually good enough. The entire
bill is labour: about £9,000–£12,000 and ~1 month of a skilled modeller per car body.
At 1,043 catalogue entries that is roughly £10 million and ~100 person-years, so
hand-building is a HEROES-ONLY strategy — 5 to 20 cars, never a catalogue.**

### The bill

| Line | What | Cost | Status |
|---|---|---:|---|
| **Blender** | GPL-2.0-or-later; Cycles Apache-2.0; "free to sell your work" | **£0** | verified |
| **Renderer / denoiser** | Cycles + OpenImageDenoise ship with official builds | **£0** | verified |
| **Class-A surfacing add-ons** | Surface Mesh, Surface Psycho, Surface Diagnostics, Hardflow, PolyQuilt, PDT — all GPL on extensions.blender.org | **£0** | verified |
| **Blender upgrade 4.0.2 → 4.5/5.2** | mandatory to install any of the above | **£0 cash**, ~1 engineer-day to re-validate the render rig | verified |
| **Optional paid add-ons** | Hard Ops/Boxcutter $37 · MESHmachine $44.99 · PUNCHit $10 · Quad Remesher $109.90 | **≤ $202 one-off, total** | verified |
| **Optional true-NURBS seat** | Plasticity **Studio** (only verified sub-$1k tool that states Class-A surfacing) | **$299 one-off** | verified |
| **REFERENCES — the high-ROI line** | ccvision CAR-SPECIAL, true-to-scale **5-view** vector templates, 1:1 DXF/CDR | **€24/car**, or **€299 yr-1 / €159 yr-2+** for up to 60 cars per month | verified |
| **Base starting geometry** | none exists free at premium bar for the cars that matter | **no free equivalent** | measured |
| **THE HUMAN** | 1 body to this project's own rubric | **£9,000–£12,000 per car** | derived, see §5 |

**Total to hand-build ONE premium car body, realistically:**
£0 tools + £24-worth of reference + **£9,000–£12,000 of labour** ≈ **£9,000–£12,000**.
Tooling is under 4% of the first car and ~0% of every car after it.

### The recommendation, in order

**1. Before you spend the first £9,000, spend €129.**
The project has proven, exhaustively, that *free* sourced meshes fail — 1,043 entries,
119 scrapped on opaque glazing alone, a Ford wave of 256 candidates yielding 1 keeper.
It has **never once tested a paid studio model against its own gates.** Squir sells
production car models at a verified **€129**, and its catalogue is current to MY2027.
Buy one car this project genuinely cannot source — a Ford Puma or a Nissan Qashqai — and
run it through the existing stack: `glass_probe` **paired with glass-area retention**,
the red/blue respray control, the tyre check, `gltf-transform validate`. That experiment
costs €129 and one afternoon. If it passes, the hand-build question is moot for most of
the catalogue. **It is the cheapest unrun experiment in the entire programme.**

**2. Buy the reference layer regardless — €299.**
`LANDMARK_SPEC.md` records that every lateral position more than ~300 mm from the number
plate is UNRELIABLE, because three independent camera-recovery routes failed
(negative f², inconsistent vanishing points, a homography whose scale runs the wrong
way). That is exactly and only a missing-orthographic-view problem. ccvision sells
true-to-scale **5-view** templates and **has every nameplate this project has failed to
source** (measured today: Puma 5 · Qashqai 7 · Golf 55 · Corsa 29 · Kuga 7 ·
Sportage 11). €299 in year one buys up to 720 of them. This is the single highest-value
purchase on the list and it helps the sourced route as much as the hand-built one.

**3. Upgrade Blender. It is free and it is currently blocking the free tier.**
This container runs **4.0.2** (April 2024 binary). The extensions platform arrived in
**4.2 LTS**; current stable is **5.2**. Every add-on that would help a body shell
declares `blender_version_min` of 4.2, 4.5, 5.1 or 5.2. **Today the project cannot
install a single one of them.** Cost is zero cash and about a day to re-validate the
rig against the documented control (0.22 world → sRGB 130, Standard view transform).

**4. Hand-build heroes only, and cost them honestly.**
Twenty hand-built bodies ≈ **£184,000**. Twenty bought Squir models ≈ **€2,580**.
Hand-building is 70–90× the price of buying the same car. It is justified only where no
purchasable model exists, or where a specific car is worth £9k of brand value on its own.

**5. Do not expect a parametric shortcut. There isn't one.** See §6.

---

## 2. FREE — with verified terms

Terms are stated because "free" means two different things here; neither is a gate.

### 2.1 Blender itself and its renderers — confirmed zero cost

Fetched from `blender.org/about/license/`:

* Blender source is **GNU GPL v2-or-later**; binaries distribute under **GPL v3-or-later**.
* **Cycles is Apache-2.0** — a permissive licence, not copyleft.
* blender.org states plainly: *"Free to Use. Free to Change. Free to Share. **Free to Sell
  Your Work**."* There is no royalty, no per-seat fee, no commercial tier.
* Add-ons written in Python "if published" must be GPL-compliant; **you may sell them, and
  you may keep private ones private.** Nothing about this project's use is restricted.

**The two container limitations the brief flagged are NOT cost items.**

* **OpenImageDenoise is missing here but is free and standard.** The Blender manual
  (4.2 and 5.2, fetched today) documents OIDN as a built-in Cycles denoiser and the
  *default* choice. I verified this container has **no OIDN library anywhere on disk**
  and that `compute_device_type` enumerates **empty** (CPU-only, no CUDA/OptiX/HIP).
  That is a property of this stripped 4.0.2 binary, not of Blender. Installing the
  official blender.org build restores it at **£0**.
* **EEVEE failing on EGL is a headless-container problem, not a renderer problem.**
  A paid renderer would not fix it, and would not change output quality: Cycles is a
  full unbiased path tracer and is already the right engine for a final studio frame.
  **Confidence ~90%** that no paid renderer would materially change the delivered image.

**Verdict: £0, and no paid renderer or denoiser is worth buying.**

### 2.2 Free add-ons that are genuinely on-target for a car body

All from the official `extensions.blender.org` platform (queried its API: **1,383
extensions, 1,124 add-ons**). Every one below is **GPL**, free, and hosted by the Blender
Foundation. The `min` column is the load-bearing one.

| Add-on | Version | Min Blender | What it does for a car body |
|---|---|---|---|
| **Surface Mesh** | 1.0.3 | **4.2** | *"Car body modeling from Bezier curves"* — **Coons-patch panel surfacing from a 4-curve network.** Live auto-update, named panels with C0/C1/D0/D1 boundary roles, split/merge, shared-curve handling, mirror with clipping. This is the actual Class-A *workflow* (curve network → patch), free. |
| **Surface Diagnostics** | 1.4.5 | **4.5** | **Zebra** stripes, **isoangle** bands, **draft angle**, live **sections**, **proximity** gradients. Its own description names *Automotive* first. This is the Class-A *inspection* toolkit, and it is the thing that turns "looks smooth" into a measured verdict. |
| **Surface Psycho** | 0.10.3 | **5.2** | **A real NURBS editor inside Blender** via Geometry Nodes — trim, project, interpolate, connect **with continuity control**; **STEP/IGES import, STEP export**. Author warns it is **ALPHA**: "expect instabilities, breaking changes". Output is vanilla Blender data, so files survive without it. |
| **E Topology Smooth** | 2.7.8 | **5.1** | Mesh topology smoothing with **G0–G4 continuity analysis**. |
| **Hardflow** | 1.21.0 | 4.2 | Open-source hard-surface boolean toolkit — the free analogue of Hard Ops/Boxcutter. |
| **PolyQuilt** | 1.46.7 | 4.5 | Interactive retopology (free analogue of RetopoFlow). |
| **Bsurfaces GPL Edition** | 1.8.4 | 4.3 | Draw-strokes retopology / surface building. |
| **EdgeFlow / EdgeFlowDraw** | 1.1.2 / 2.1.2 | 4.2 | Set edge loop flow to follow curved surfaces — panel-crease control. |
| **Precision Drawing Tools (PDT)** | 1.5.3 | 4.2 | Numeric/precision placement — building to a landmark table instead of by eye. |
| **tinyCAD Mesh tools** | 1.3.3 | 4.2 | Edge intersect/project/bisect — CAD-style construction. |
| **Curve Tools** | 0.4.6 | 4.2 | Bezier/NURBS curve+surface utilities. |
| **Bool Tool** / **Booltron** | 2.1.0 / 3.3.4 | 4.5 | Boolean workflow (shut lines, apertures). |
| **Blueprints** | 1.0.3 | 4.2 | Background/reference image management. |
| **References Overlays** | 3.0.1 | 4.2 | PureRef-style reference boards in the viewport. |
| **STEPper Reborn** | 2.3.0 | 5.1 | STEP/CAD import — the door for any purchased CAD surface data. |

**THE BLOCKER, and it is free to clear:** the extensions platform shipped in
**Blender 4.2 LTS (16 July 2024)**. This container is on **4.0.2**. Extension archives
carry a `blender_manifest.toml` that pre-4.2 Blender cannot read, and every add-on above
declares a 4.2+ minimum anyway. **Zero of these are installable today.** Upgrading is
free; re-validating the render rig afterwards is the real cost, in hours.

### 2.3 Supporting toolchain already in use — all confirmed still free

| Tool | Licence | Verified |
|---|---|---|
| `@gltf-transform/cli` **4.4.2** | **MIT** | npm registry |
| `gltf-validator` (Khronos) **2.0.0-dev.3.10** | **Apache-2.0** | npm registry |
| `draco3d` **1.5.7** | **Apache-2.0** | npm registry |
| `@google/model-viewer` **4.3.1** | **Apache-2.0** | npm registry |
| **Poly Haven** — 989 HDRIs, 521 models | **CC0**, explicitly commercial-use, no attribution required | polyhaven.com/license |

Nothing in the shipping toolchain has moved to a paid tier. **Confidence 95%.**

### 2.4 Free reference material — real, but not sufficient

* **drawingdatabase.com** — free raster blueprints, 110 pages of cars. Free download.
* **the-blueprints.com** — a large free raster "blueprints" section (Ford 1883,
  Chevrolet 1284, Citroën 514, Honda 581, BMW 627 drawings listed) alongside a paid
  vector store.
* **getoutlines.com** — free raster blueprints with an account; paid vectors.

**The honest limitation:** these are artist-traced raster images with no stated scale
and no dimensional certification. They fix *proportion*, they do not fix *dimension*.
For the exact failure `LANDMARK_SPEC.md` documents — lateral positions beyond ±300 mm —
a free traced blueprint is only as good as whoever traced it, and none of them publish
an error budget. **Use free blueprints for silhouette; buy true-to-scale for landmarks.**

---

## 3. PAID — with verified prices

Prices fetched 2026-08-21. Currency as quoted by the vendor.

### 3.1 Blender add-ons (all one-off, all optional)

| Product | Price | Source verified | Note |
|---|---:|---|---|
| **Hard Ops / Boxcutter Ultimate Bundle** | **$37.00** | developer's Gumroad (`price_cents 3700`) | Superhive/Blender Market is Cloudflare-blocked from here; the developer's own store is the authority. |
| **MESHmachine** | **$44.99** | machin3.gumroad.com | Fuses/unfuses bevels, refits surfaces, unbevel — real hard-surface repair. |
| **DECALmachine** | **$54.99** | machin3.gumroad.com | Mesh decals — shut lines and panel gaps *as decals*, not cuts. |
| **PUNCHit** | **$10.00** | machin3.gumroad.com | N-gon manifold extrude. |
| **MACHIN3tools** | **$0** (pay-what-you-want, suggested $2) | machin3.gumroad.com | Free. |
| **Quad Remesher (Exoside)** | **$109.90** Pro perpetual, single software (Blender) · **$139.90** all-software · $59.90 indie non-commercial · $15.99/3mo sub. VAT excluded. | exoside.com/quadremesher/quadremesher-buy | Auto-retopology. The paid upgrade over PolyQuilt/Blender's own remesh. |
| **RetopoFlow** | **NOT ESTABLISHED** | Superhive 403 | Sold on Superhive only; price not retrievable. PolyQuilt is the free substitute. |

**A serious paid Blender kit is ≤ $202 one-off, forever.** That is a rounding error
against one day of the modeller.

### 3.2 The genuine Class-A tier — where the real money is

| Product | Price | Class-A? | Verified from |
|---|---:|---|---|
| **Plasticity Indie** | **$175** one-off | **No** — vendor's own comparison table says "Class-A surfacing: No" | plasticity.xyz/buy |
| **Plasticity Studio** | **$299** one-off | **YES** — vendor states "Class-A surfacing: Yes (xNurbs, Square, Align, Explicit Control)" + **PolySplines G2 mesh-to-NURBS** + **Blender bridge** + STEP/IGES/Parasolid | plasticity.xyz/buy |
| **Rhino 8** commercial single user | **$995** | Not marketed as Class-A; VSR/other plugins extra | rhino3d.com sales page |
| **Autodesk Alias AutoStudio**, 1-yr subscription | **$19,135 / year** | Yes — the automotive industry standard | Novedge (authorised Autodesk reseller). Autodesk's own page returns 403 from here. |
| **ICEM Surf** (Dassault) | **NOT ESTABLISHED** | Yes | No public price. |

**This is the most important price on the page.** The gap between the free/cheap tier
and the industry Class-A tier is **$299 vs $19,135 per year — 64×.** Plasticity Studio at
$299 one-off, with a Blender bridge and G2 mesh-to-NURBS conversion, is the only verified
product that claims Class-A capability at hobby money. Whether it *delivers* Alias-grade
surfaces is the vendor's claim, not a measured fact — **but it has a 30-day free trial, so
testing that claim costs £0 and one day.** That test is worth running before anyone
contemplates a £19k licence.

### 3.3 Reference material — the €24 that removes the landmark problem

| Product | Price | What you get | Verified |
|---|---:|---|---|
| **ccvision CAR-SPECIAL**, single vehicle | **€24.00** | **"True to scale vehicle templates in 5 views"** — AI, EPS, CDR, DXF; **CDR also 1:1** | ccvision.de |
| ccvision single vehicle + 3D | €49.00 | as above plus CAR-3D | ccvision.de |
| **ccvision CAR-SPECIAL Online subscription** | **€299 first year, then €159/yr** | 14,000+ templates / 68,000+ individual drawings; **up to 10 vehicles/day, max 60/month** | ccvision.de |
| **getoutlines.com** | **$24.00** per drawing | Vector wrap/3D blueprints; catalogue runs to 2022–2026 model years | getoutlines.com |
| the-blueprints.com vector store | **NOT ESTABLISHED** (credit-based; price behind a JS/account wall) | 15,000 car vector drawings | the-blueprints.com |

**Why this line matters more than its price suggests.** These are **car-wrap templates**.
They exist so a printer can output vinyl at 1:1 and have it fit a real car — which is a
dimensional-accuracy requirement, not an artistic one. ccvision states "true to scale"
and ships 1:1 CDR. That is a materially stronger accuracy claim than any traced blueprint.

**Coverage measured today against this project's own known gaps** (ccvision search,
vehicle outlines): **Ford Puma 5 · Nissan Qashqai 7 · VW Golf 55 · Vauxhall Corsa 29 ·
Ford Kuga 7 · Kia Sportage 11.** The cars Sketchfab cannot supply as meshes *are* supplied
here as dimensioned drawings.

*Caveat, stated plainly:* I have not bought one, so ccvision's accuracy is a **vendor
claim, not a measurement**. €24 buys the test. **Confidence that a 5-view true-to-scale
template resolves the ±20% lateral disagreement in `LANDMARK_SPEC.md` §5: ~80%.**

*(One line for the other researcher's ground: these 5-view 1:1 templates are also a
candidate dimensional source in their own right — worth a mention in their report, not
pursued here.)*

### 3.4 Buying the car instead of building it

| Source | Price | Verified |
|---|---:|---|
| **Squir** | **€129.00** per model, catalogue current to MY2026/2027 | squir.com |
| Hum3D | **NOT ESTABLISHED** — Cloudflare 403 | — |
| TurboSquid | **NOT ESTABLISHED** — 403 | — |
| CGTrader | **NOT ESTABLISHED** — HTTP 202 bot wall | — |
| BlenderKit / Blendkit | free tier 23,019 models; Full **$9.90/month** | blenderkit.com |

**€129 is the number that decides the strategy.** It is ~1.3% of the labour cost of
hand-building the same car.

---

## 4. NO FREE EQUIVALENT

Four things, honestly:

1. **A skilled automotive modeller.** No substitute at any tier. §5.
2. **A free premium starting shell for the cars that matter.** Measured today via the
   Sketchfab API: **CC0 + downloadable, zero models** for Ford Puma, Nissan Qashqai,
   VW Golf, Vauxhall Corsa and Ford Kuga — *each*. The entire CC0 downloadable pool for
   the query "car" is **122 models**. Widening to any licence: Puma 5, Qashqai 7,
   Corsa 5, Kuga 3, Golf 190 — and this project has already audited that pool to
   destruction (scans, converter-clay at 0.588/0.800, opaque glazing). Poly Haven's 521
   CC0 models contain **no road car** (nearest is `covered_car`). **You cannot start a
   premium build from a free mesh for a modern UK volume car. Measured, not inferred.**
3. **Certified dimensional reference at zero cost.** Free blueprints are traced and
   unscaled. The paid fix is €24.
4. **A production-grade NURBS Class-A seat at zero cost.** Surface Psycho is real and
   free but self-declares **ALPHA** and needs Blender 5.2; Plasticity Studio at $299 is
   the cheapest verified non-alpha claim; Alias is $19,135/yr.

---

## 5. THE HUMAN COST PER CAR BODY

This is 96%+ of the bill, so it gets the most careful treatment.

### 5.1 Rate — UK, cited

**ITJobsWatch, 6 months to 21 August 2026** (fetched today):

| Series | n (rates quoted) | 25th | **Median** | 75th | 90th |
|---|---:|---:|---:|---:|---:|
| Contract, "3D Modelling", UK, per day | 13 | £419 | **£438** | £456 | £512 |
| Contract, "Automotive", UK, per day | 84 | £463 | **£550** | £650 | £788 |
| Permanent, "3D Modelling", UK, per year | 40 | £40,000 | **£43,000** | £58,770 | £70,000 |

**Honest caveats.** ITJobsWatch indexes *IT* vacancies, so "3D Modelling" there skews
engineering/CAD rather than CG car art, and **n=13 daily rates is a very thin sample**.
The "Automotive" series is better-sampled (n=84) but is not modelling-specific. Treat
**£438–£550/day** as the defensible band and £43k–£58.8k as the salaried equivalent
(≈£244–£330/day fully loaded at 220 productive days with ~25% employer on-cost).

### 5.2 Time — two independent anchors

* **FLOOR — 45 hours.** CG Masters' *3D Cars: Inside and Out* (verified: "45 hours |
  Intermediate | Blender 3.6 – 5.x", $60) teaches modelling *an entire vehicle including
  a full interior* start to finish. That is a **taught** build: every decision pre-made,
  no reference recovery, no iteration, no QC. It is a hard floor, not an estimate.
* **PRACTITIONER — about a month.** On the Blender Artists thread *"How long it takes
  professional modelers to model something with precise measurements and shapes"*,
  **Carlos Henrique Ávila**: *"it takes me a month to accurately model a car"* — including
  measurement, assembly, detail, topology fixes and UVs. In the same thread **const**
  gives **2–4 days each** for a *single* component (steering wheel, front bumper, gearbox),
  and notes ~8 efficient hours per working day.

* **THIS PROJECT'S OWN DATA AGREES WITH "const", NOT WITH THE FLOOR.** Gate 3 v7 built
  **20 front components**; the cabin gate **28**; the rear **14**. That is 62 components
  before the body shell exists. At 2–4 days per component nothing about a 45-hour whole
  car is credible for work held to this project's rubric.

### 5.3 Cost per body

| Scenario | Days | Rate | **Cost per car body** |
|---|---:|---:|---:|
| Taught-course floor, salaried in-house | 5.6 | £244 | £1,370 |
| Taught-course floor, contract | 5.6 | £438 | £2,450 |
| **Practitioner month, contract 3D** | **21** | **£438** | **£9,200** |
| **Practitioner month, automotive contract** | **21** | **£550** | **£11,550** |

**Take £9,000–£12,000 per car body as the planning number.**
**Confidence ~75%** — the rate is well-cited, the time is two practitioner anchors plus
this project's own component counts, and the failure mode is that it is *optimistic*,
because none of those anchors were held to a rubric that fails a car for a 0.986-alpha
windscreen or a body-coloured tyre.

### 5.4 What that means at catalogue scale

| | Hand-build | Buy (Squir €129) |
|---|---:|---:|
| 1 car | £9,200 | ~£110 |
| Top 20 UK gap cars | **£184,000** · 420 days | **~£2,180** |
| Full catalogue, 1,043 entries | **£9.6M–£12.0M** · 21,900 days ≈ **~100 person-years** | ~£113,000 |

**Hand-building is 70–90× the price of buying the same car, and the full catalogue is
arithmetically out of reach — 100 person-years is not a schedule, it is a refutation.**

---

## 6. IS THERE A PARAMETRIC OR KIT-BASED CAR-BODY ROUTE?

**No. That is the honest negative result, and it is worth stating clearly because it is
the missing piece of the proposal.**

Searched the full 1,383-extension official platform, the paid add-on stores, and the
CAD tier. What actually exists:

* **Curve-network-driven, yes** — `Surface Mesh` builds car body panels as **Coons
  patches from four boundary Bezier curves**, with live update, named panels and mirror.
  You shape *curves*; the surface follows. That is genuinely the Class-A workflow shape.
* **Dimension-driven, no.** Nothing found takes "length 4284, width 1789, wheelbase X,
  DLO height Y" and returns a body. `Surface Mesh` has no parameter layer at all; its
  inputs are curve control points.
* **Procedural car generators exist but are the wrong thing** — Superhive lists a
  "Procedural Car Generator" and "Procedural Traffic" (prices **NOT ESTABLISHED**,
  Cloudflare 403). These target background/traffic vehicles and stylised low-poly
  output, not a named production car to a landmark spec. They will not produce a
  Ford Puma a registration decodes to.
* **The nearest real thing is Rhino + Grasshopper** — genuinely parametric NURBS, but
  Rhino is **$995** and Grasshopper does not know what a car is; you would be *building*
  the parametric car system, not buying one.

**However — the bridge does exist, and it is free.** A curve-network surfacer whose
curves are *placed numerically* is a semi-parametric body. `Surface Mesh` (free) +
`Precision Drawing Tools` (free) + a ccvision 1:1 5-view template (€24) + this project's
existing landmark-spec discipline is the buildable route: drive the curve network from
measured landmarks, generate the patches, inspect with `Surface Diagnostics` zebra.
**That does not turn weeks into hours** — it turns "sculpt by eye" into "build to a
table", which is a quality change, not a speed change. **Confidence ~70%** that this is
the right architecture; **confidence ~85%** that no off-the-shelf dimension-driven car
body generator exists to buy today.

---

## 7. WHERE THIS CONTRADICTS THE BRIEF

The brief says the body shell is the thing that cannot be built, and frames the question
as tooling. Two corrections, both evidenced:

1. **The tooling gap is smaller than assumed, and it is currently self-inflicted.**
   Free, GPL, Blender-Foundation-hosted add-ons now cover curve-network panel surfacing
   (`Surface Mesh`), G0–G4 continuity analysis (`E Topology Smooth`), true NURBS with
   continuity control and STEP I/O (`Surface Psycho`), and a proper Class-A inspection
   suite naming *Automotive* first (`Surface Diagnostics` — zebra, isoangle, draft,
   sections). **None of it can be installed on Blender 4.0.2**, because the extensions
   platform starts at 4.2. The single most under-priced item in this report is a free
   version upgrade.

2. **The reference gap is bigger than the tooling gap, and it is the cheapest to close.**
   `LANDMARK_SPEC.md` is a careful document that honestly reports it cannot place a
   headlamp tip laterally — the two references disagree by 20% and one is physically
   impossible. No add-on fixes that. A €24 true-to-scale 5-view template does. Spending
   engineering effort on surfacing tools while the input is two three-quarter
   photographs is optimising the wrong end.

3. **A third, unasked-for correction.** The evidence that "bought models fail" is
   evidence about **free** models. Every failure mode in project memory —
   converter-clay at 0.588, photogrammetry scans, opaque glazing, flat shells — is a
   property of free uploads. **A €129 Squir model has never been tested here.** Pivoting
   to a £10M hand-build programme without having spent €129 on that test would be the
   most expensive untested assumption in the project's history.

---

## 8. WHAT I COULD NOT ESTABLISH

Recorded rather than guessed.

| Item | Why |
|---|---|
| RetopoFlow price | Superhive/Blender Market returns Cloudflare **403**; sold nowhere else. |
| "Procedural Car Generator" / "Procedural Traffic" prices | Same 403. |
| the-blueprints.com per-drawing / credit price | JS-rendered, price behind an account. |
| Hum3D, TurboSquid, CGTrader per-model prices | 403 / HTTP 202 bot walls. Squir (€129) is the one verified marketplace anchor. |
| Autodesk's own list price for Alias | autodesk.com returns **403**. Used Novedge, an authorised Autodesk reseller: **$19,135/yr**. |
| ICEM Surf price | Not published. |
| Whether ccvision templates actually hit the accuracy needed | Vendor claims "true to scale", 1:1 CDR. **Not independently verified — €24 buys the test.** |
| Whether Plasticity Studio's Class-A claim holds in practice | Vendor claim. **30-day free trial makes the test free.** |
| A dimension-driven parametric car body product | Searched; **none found**. Reported as a negative result at ~85% confidence, not as proof of absence. |
| Real hours-per-body under *this project's* rubric | No project has published it. Estimated from two practitioner anchors plus this repo's own component counts (20 front / 28 cabin / 14 rear). |

---

## 9. SOURCES

All fetched 2026-08-21.

* Blender licence — https://www.blender.org/about/license/
* Blender 4.2 LTS release notes (extensions platform) — https://www.blender.org/download/releases/4-2/
* Cycles denoising / OpenImageDenoise — https://docs.blender.org/manual/en/latest/render/cycles/render_settings/sampling.html
* Blender extensions API (1,383 extensions) — https://extensions.blender.org/api/v1/extensions/
* Surface Mesh — https://extensions.blender.org/add-ons/surface-mesh/
* Surface Psycho — https://extensions.blender.org/add-ons/surfacepsycho/
* Surface Diagnostics — https://extensions.blender.org/add-ons/surface-diagnostics/
* Quad Remesher pricing — https://exoside.com/quadremesher/quadremesher-buy/
* Plasticity pricing — https://www.plasticity.xyz/buy
* Rhino pricing — https://www.rhino3d.com/sales/north-america/United_States/
* Alias AutoStudio pricing (authorised reseller) — https://novedge.com/products/buy-alias-autostudio-subscription
* Hard Ops/Boxcutter — https://masterxeon1001.gumroad.com/l/hopscutter
* MESHmachine / DECALmachine / MACHIN3tools / PUNCHit — https://machin3.gumroad.com/
* ccvision CAR-SPECIAL — https://www.ccvision.de/en/car-special/product-info.html
* getoutlines — https://getoutlines.com/
* the-blueprints — https://www.the-blueprints.com/
* drawingdatabase — https://drawingdatabase.com/category/vehicles/cars/
* Squir — https://www.squir.com/
* Blendkit plans — https://www.blenderkit.com/plans/pricing/
* Poly Haven licence — https://polyhaven.com/license · API — https://api.polyhaven.com/
* ITJobsWatch contract "3D Modelling" — https://www.itjobswatch.co.uk/contracts/uk/3d%20modelling.do
* ITJobsWatch contract "Automotive" — https://www.itjobswatch.co.uk/contracts/uk/automotive.do
* ITJobsWatch permanent "3D Modelling" — https://www.itjobswatch.co.uk/jobs/uk/3d%20modelling.do
* CG Masters *3D Cars: Inside and Out* (45 h, $60) — https://cgmasters.com/3d-cars-inside-and-out-in-blender/
* 3D Cars Academy (team licences) — https://3dcarsacademy.com/
* Blender Artists modelling-time thread — https://blenderartists.org/t/how-long-it-takes-professional-modelers-to-model-something-with-precise-measurements-and-shapes/1575849
* npm registry (licences) — @gltf-transform/cli, gltf-validator, draco3d, @google/model-viewer
* Sketchfab API v3 `/search` — CC0/downloadable counts measured with the project's own token
