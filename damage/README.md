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

| `DAMAGE_BACKEND` | Model | Cost/scan | GPU | Limits |
|---|---|---|---|---|
| **`openrouter`** (image default) | Gemma 4 31B (free) | **$0** | none | 20/min · 50/day, or 1,000/day after a one-time $10 credit purchase |
| `anthropic` | frontier Claude | per-scan fee | none | none |
| `qwen` | local Qwen2.5-VL 7B | GPU-hours | **required** | — |

**`DAMAGE_BACKEND=openrouter` — free, and the image default.** A free hosted
open vision model via OpenRouter (`DAMAGE_VLM_MODEL`, default
`google/gemma-4-31b-it:free`). **$0 per scan and no GPU**, traded against a rate
cap. At ~31B it is roughly four times the local 7B fallback — the failure below
was a model-**size** problem, not a self-hosting one. Needs
`OPENROUTER_API_KEY` (the free tier still authenticates). Speaks the OpenAI
chat-completions shape over `requests`, so it adds **no new dependency**. A 429
is an expected operating condition and is reported with the caps spelled out.

**`DAMAGE_BACKEND=anthropic` — most accurate.** A frontier **Claude** vision
model via the Anthropic API (default `claude-opus-5`). Needs
`ANTHROPIC_API_KEY`; **no GPU**. Costs per scan, so the intended use is
per-scan escalation — disputes, high-value claims, or when the free tier
returns low confidence — not every scan.

**`DAMAGE_BACKEND=qwen` (code default) — cheap fallback.** A local
**Qwen2.5-VL** 7B (Apache-2.0), lazy-loaded on first photo job. Self-hosted, but
**unreliable at the actual assessment**: on a live test it scored a car with a
*shattered windshield* **99/100 ("minor bumper scratch")** — it pattern-matched
"car inspection" instead of reading the image. Use it as a latency fallback,
not as the product's judgement.

Both hosted backends make the worker an API proxy that scales to zero — they
remove the GPU cold-start entirely (the whole reason for a warm worker).

## Tests

```bash
python damage/test_handler.py     # 110 checks, GPU-free, network-free, deps-free
```

Same discipline as the other workers: the vision model is never loaded (a fake
`vision_fn` returns canned JSON), and the deterministic core — taxonomy,
scoring, pricing, quality, fusion, compare, report, validation, routing — is
pinned hard, because a wrong result costs a user money.

## Deploy

Two image variants:

| File | Base | Size | Backend | GPU |
|---|---|---|---|---|
| **`Dockerfile`** (default) | `python:3.11-slim` | ~150 MB | `openrouter` (free) | **none** |
| `Dockerfile.gpu` | `nvidia/cuda:*-runtime` | ~4.7 GB | `qwen` | required |

**Recommended: the no-GPU proxy (`Dockerfile`).** CI
(`.github/workflows/damage-docker-build.yml`) runs the tests, then builds and
pushes `alamk123/damage-scan:<sha>` (and `:v1`/`:latest` on `main`). Stand up a
RunPod endpoint on that image with `workersMin=0` — it scales to zero, cold
starts in seconds, and needs **no network volume and no object storage**
(reports inline in the response). The one required endpoint env var is
**`OPENROUTER_API_KEY`** (or `ANTHROPIC_API_KEY` if you switch
`DAMAGE_BACKEND`); optionally `DAMAGE_VLM_MODEL` to pick the model. With the
free backend the only recurring cost is RunPod's per-second CPU worker time.

⚠️ On endpoint creation RunPod defaults `workersStandby` to 1 (an always-warm,
always-billed worker) and it is **not** settable via the REST API — set it to 0
in the console, or the "scale to zero" property above doesn't hold.

The GPU variant (`Dockerfile.gpu`, `DAMAGE_BACKEND=qwen`) is only for running
the local model; it needs a GPU worker and a network volume for the weight
cache, and is documented as less accurate. Build it explicitly (it is not the
CI default).
