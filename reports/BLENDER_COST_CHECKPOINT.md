# CHECKPOINT — Blender hand-build cost research (2026-08-21) — COMPLETE

Agent: BLENDER COST RESEARCH. Branch `claude/lovable-connection-ki7jch`.

**I deliberately did NOT touch the repo-root `CHECKPOINT.md`** — it is owned by an
in-flight SIX-GATE MERGE agent (`build_golf.py`). Overwriting it would have destroyed
live coordination state. This file is my checkpoint instead.

## STATUS: DONE. Deliverable is durable in both surviving places.

* `reports/BLENDER_COST.md` (this repo, committed)
* `car-meshes/staging/research/BLENDER_COST.md` — uploaded, **round-trip verified**:
  local and remote sha256 both `58f1f7c7d89774ac…`, 28,633 bytes, prefix listed.

## THE ANSWER, one line

Tools are £0 and finally good enough. The whole bill is labour: **£9,000–£12,000 and
~1 month per car body**. At 1,043 entries that is ~£10M / ~100 person-years — heroes
only, never a catalogue. **Before spending the first £9,000, spend €129** on one paid
Squir model of a gap car and run it through the existing gate stack; that experiment
has never been run and it decides the strategy.

## MEASURED THIS SESSION (not recalled)

* Container Blender is **4.0.2**; current stable is **5.2**. Extensions platform starts
  at **4.2 LTS**, so **zero** of the useful free add-ons are installable today.
* No OIDN library anywhere on disk; `compute_device_type` enum is **empty** (CPU only).
  OIDN is the documented Cycles default in official builds → this is a stripped binary,
  not a cost item.
* Sketchfab API, CC0 + downloadable: **0 models** each for Ford Puma / Nissan Qashqai /
  VW Golf / Vauxhall Corsa / Ford Kuga. Whole CC0 "car" pool = 122.
* ccvision has 1:1 true-to-scale **5-view** templates for every one of those nameplates
  (Puma 5 · Qashqai 7 · Golf 55 · Corsa 29 · Kuga 7 · Sportage 11) at **€24 each** or
  **€299 first year** (60/month). This is the fix for `LANDMARK_SPEC.md` §5.
* Verified prices: Plasticity Studio **$299** (states Class-A) vs Alias AutoStudio
  **$19,135/yr**. Squir car models **€129**. Hard Ops/Boxcutter **$37**.
* UK rates, ITJobsWatch 6mo to 21 Aug 2026: contract 3D Modelling median **£438/day**
  (n=13); contract Automotive median **£550/day** (n=84); permanent 3D Modelling median
  **£43,000** (n=40).

## THREE FREE ADD-ONS THAT CHANGE THE PICTURE (all GPL, extensions.blender.org)

* **Surface Mesh** (4.2+) — "Car body modeling from Bezier curves", Coons patches.
* **Surface Diagnostics** (4.5+) — zebra / isoangle / draft / sections; names Automotive.
* **Surface Psycho** (5.2+, **ALPHA**) — real NURBS with continuity control + STEP I/O.

## NEGATIVE RESULT WORTH KEEPING

**No dimension-driven parametric car-body generator exists, free or paid** (~85%
confidence). Curve-network surfacing exists and is free; nothing takes length/width/
wheelbase and returns a body. Do not go looking again without new information.

## NOTHING LEFT IN FLIGHT

No pods rented, no money spent, no customer-visible change, nothing published.
