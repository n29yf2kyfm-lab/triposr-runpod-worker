# Damage Scanner — RunPod serverless worker

AI vehicle-damage inspection: photos in, an appraiser-grade report out —
condition score, per-finding evidence, hidden-damage probabilities,
model-specific risks, a region-aware repair range, capture-quality gating, and
**findings pinned onto the 3D car model this platform already builds**
(`trellis2/`). The teardown that shaped the feature set is in
[`DAMAGE_APPS.md`](./DAMAGE_APPS.md).

## Isolation

Self-contained, per PLAN.md §2.3. Own image (`alamk123/damage-scan:*`), own CI
(`damage/**` only), own bucket (`damage-scans`), own output dir
(`DAMAGE_OUTPUT_DIR`). Nothing here imports from `trellis2/` or `building/`, and
neither is edited — so this directory cannot rebuild another product's image.

## Modes

| Mode | Input | Output |
|---|---|---|
| `inspect` | photos (or a `findings` array) + optional vehicle, region, `glb_url` | full report: score, findings, repair, coverage, 3D pins |
| `compare` | current capture + a baseline (`baseline_findings`) | new / worsened / resolved diff; only the delta is priced |
| `report` | a `findings` array | re-render score/price/report (no vision stage) |

## Input

```json
{
  "input": {
    "mode": "inspect",
    "vehicle": {"make": "Tesla", "model": "Model 3", "year": 2022, "market": "us"},
    "region": "us",
    "image_urls": ["https://.../front.jpg", "https://.../left.jpg"],
    "glb_url": "https://.../this-cars-3d-model.glb",
    "want_html": true,
    "want_fusion": true
  }
}
```

- **`market`** on the vehicle resolves driver/passenger → left/right (RHD vs
  LHD). **`region`** selects the repair-price market (`us`, `uk`, `eu`, `asia`,
  `mena`, `au`); it falls back to the vehicle market, then to `us`.
- **`glb_url`** is this vehicle's model from the `trellis2` worker — pass it to
  bind the 3D pins. Findings are valid without it (they attach to any model of
  the same car).
- **`findings`** may be supplied in place of images. Then the vision stage is
  skipped and the deterministic pipeline (score → price → fuse → report) runs
  with **no GPU** — the same move the building worker makes with `quantities`.
  It is also how a caller who ran detection elsewhere reuses this scoring/report.
- **`image_b64s`** — base64 images instead of URLs. All URLs are SSRF-checked.

## Output

```json
{
  "status": "success",
  "mode": "inspect",
  "condition": {"score": 35, "grade": "F", "descriptor": "severe",
                "structural_concern": true},
  "findings": [ ... ],
  "repair": {"currency": "USD", "total_low": 850, "total_high": 2800,
             "hidden_contingency_high": 1550, "lines": [ ... ]},
  "completeness": {"overall_coverage": 0.25, "guidance": ["Add rear views ..."]},
  "quality": {"reliable": true, "blocking_tags": []},
  "fusion": {"count": 5, "fused": true, "pins": [ ... ], "frame": { ... }},
  "report": { ... full report object ... },
  "artifacts": {"<job>.report.json": {"url": ...},
                "<job>.report.html": {"url": ..., "html_b64": ...}}
}
```

The HTML report is self-contained (print-to-PDF ready). The 3D `pins` carry an
anchor + normal in a normalised car frame — see `fusion.FRAME` for how the app
aligns them to the loaded GLB.

## The vision backend

The backend is injected (`analyze.analyze(..., vision_fn=)`) and selected by
`DAMAGE_BACKEND`, so swapping the model is one env var and tests/the
findings-only path load nothing.

**`DAMAGE_BACKEND=anthropic` — recommended.** A frontier **Claude** vision model
via the Anthropic API (`DAMAGE_VLM_MODEL`, default `claude-opus-5`). Needs
`ANTHROPIC_API_KEY`; **no GPU**. This is the accurate path. On a live test the
small local model scored a car with a *shattered windshield* **99/100 ("minor
bumper scratch")** — it pattern-matched "car inspection" instead of reading the
image; a frontier model reads the same photo correctly (`windshield` /
`shattered_glass` / severe) and doesn't invent damage on clean panels. Choosing
this backend also makes the worker an API proxy that scales to zero cheaply —
it removes the GPU cold-start entirely (the whole reason for a warm worker).

**`DAMAGE_BACKEND=qwen` (default) — cheap fallback.** A local **Qwen2.5-VL**
(Apache-2.0), lazy-loaded on first photo job. Self-hosted, but **unreliable at
the actual assessment** (see above) — use it as a cost/latency fallback, not as
the product's judgement. Swap the checkpoint with `DAMAGE_VLM_MODEL`.

## Tests

```bash
python damage/test_handler.py     # 98 checks, GPU-free, network-free, deps-free
```

Same discipline as the other workers: the vision model is never loaded (a fake
`vision_fn` returns canned JSON), and the deterministic core — taxonomy,
scoring, pricing, quality, fusion, compare, report, validation, routing — is
pinned hard, because a wrong result costs a user money.

## Deploy

CI (`.github/workflows/damage-docker-build.yml`) runs the tests, then builds and
pushes `alamk123/damage-scan:<sha>` (and `:v1`/`:latest` on `main`). Stand up a
new RunPod endpoint on that image with its own volume and the `damage-scans`
bucket configured (`SUPABASE_URL`/`KEY`/`BUCKET`). Set `DAMAGE_OUTPUT_DIR` only
if a network volume is attached.
