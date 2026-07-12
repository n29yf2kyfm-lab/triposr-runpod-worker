# Project memory — ExpertCarCheck / triposr-runpod-worker

## Root-cause analysis method (apply whenever investigating a problem)

Saved at the user's request. When something breaks, is slow, is wrong, or
underperforms — do NOT stop at the first plausible explanation. Run this:

**Discipline**
1. Never accept the first explanation. Ask "Why?" at least five times; keep going past five if the answer is still weak.
2. Challenge every assumption (mine and the user's). If the user is wrong, say so and show why — truth over agreement.
3. Separate symptoms from causes; separate facts from opinions.
4. Consider all factor classes: human, technical, financial, operational, legal, process.
5. Build an explicit cause→effect chain. Flag where evidence is missing.
6. Give a confidence level for every conclusion.

**Output format for a problem**
- PROBLEM (exact statement)
- WHY #1 … WHY #5 (continue #6, #7… until the deepest cause is reached)
- Then: Root Cause · Evidence for · Evidence against · Confidence % ·
  Alternative root causes · Immediate actions · Medium-term fixes ·
  Long-term prevention · Risks if ignored · KPIs to monitor ·
  Early-warning indicators · Cost of doing nothing · Highest-ROI solution
- Then challenge it: "What assumptions could still be wrong?" and re-run the
  analysis from other lenses (technical, business, customer, engineering,
  finance, legal, operations, competitor).

Only produce the full template when there is a real problem to investigate —
don't fabricate an RCA when nothing is broken.

## Product context (for fast re-grounding)

- **Goal:** UK reg → premium, near-instant, interactive 3D car.
- **Architecture (two tiers):** Tier A = hand-built/licensed interactive hero
  models (future). Tier B (live) = material-separated GLB → GPU clean-studio
  turntable → frames in Supabase → drag-to-spin viewer. AI (TRELLIS.2) is an
  offline gap-filler only; never on the user's request path.
- **Serving Supabase (renders/catalogue):** `tfkvthprsntexrcuqpyd`, bucket
  `car-renders` (public). Meshes in `car-meshes`. Catalogue index:
  `…/car-renders/catalogue.json`.
- **App:** Lovable project `1736441d-1aa3-495a-b319-584342507036`
  ("Expert Car Check Pro"), its own Supabase `ghglvtwohetcrrswvqhp`. The app
  fetches the public catalogue cross-origin; `VehicleShowroom3D` component is
  wired into `/check` (real reg) and `/3d-generator` (studio gallery).
- **Render worker:** `render/handler.py` → RunPod endpoint `ng8oiz4p2l0xa0`
  (OPTIX, ~5–7s/frame, scale-to-zero). `studio` input = clean dark backdrop
  for any colour.
- **Hard rule learned:** recolour only lands cleanly on models with a real
  body-paint material — audit every new car's render before it ships.
- **Never** hardcode Supabase/RunPod/Docker secrets in the repo (push
  protection blocks them); use env vars.
