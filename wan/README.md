# wan/ — Wan 2.2 image-to-video worker (cinematic car clips + b-roll library)

RunPod serverless GPU worker around **Wan-AI/Wan2.2-I2V-A14B-Diffusers**
(Apache 2.0, 27B MoE / 14B active). Two jobs:

1. **Car listing clips** — car photo + preset → ~5s cinematic MP4
   (orbit, headlights, scanner sweep, damage pan, interior, ...).
2. **B-roll library builds** (`mode: "broll"`) — batch-generate the shared
   shot library that `tutorials/` assembles videos from. **This worker is
   never in the tutorial request path** — that's the economic contract that
   keeps per-tutorial cost at pennies (see `../tutorials/README.md`).

   Tutorial shots are **animated action clips**: a consistent stylized 3D
   mechanic character actually performing each step (loosening bolts,
   pulling the wheel, pressing the piston — `anim/*` keys in `shots.py`).
   Character consistency across clips comes from three levers used
   together: the shared `CHARACTER`/`ANIM_STYLE` text in every prompt, ONE
   reference frame of the character passed as the batch's `source_image`
   (generate it once with any T2I model or a simple Blender render), and
   fixed per-shot seeds so re-runs reproduce instead of drifting.

   Because action clips *demonstrate* procedure steps, batches default to
   uploading under `broll_pending/`; a human reviews each clip for
   mechanical correctness (right bolts, right order, nothing hallucinated)
   and promotes approved clips to `broll/` — only then does the assembler
   pick them up. Pass `"prefix": "broll"` to skip the gate for shots where
   correctness doesn't apply (pure atmosphere).

## Why this model

Chosen over HunyuanVideo 1.5 (license excludes EU/UK — dealbreaker for a UK
product), LTX-2.x ($10M revenue cap, immature LoRA ecosystem), CogVideoX
(weaker quality), and API models (Veo 3.1 at $0.40/s and Wan 2.5+/Vidu/Luma
are per-clip priced and 10–100x over budget; Wan 2.5+ has no public weights).
Wan 2.2 is Apache 2.0, quality-leading for controllable I2V, and has the most
mature I2V LoRA training ecosystem (musubi-tuner, AI Toolkit, DiffSynth).

## Weights

| Purpose | Repo |
|---|---|
| Main model (diffusers format) | `Wan-AI/Wan2.2-I2V-A14B-Diffusers` |
| 4/8-step distill LoRA (default ON) | `lightx2v/Wan2.2-Distill-Loras` |
| Automotive style LoRA (drop-in when trained) | `STYLE_LORA` env |

The distill LoRA is the cost lever: ~40 sampling steps → 8, i.e. a 720p 5s
clip in well under a minute on L40S/H100 instead of ~9 GPU-minutes. If its
load fails (filenames are env-overridable: `DISTILL_LORA_HIGH/LOW`), the
worker logs the failure and falls back to full 40-step sampling.

## GPU sizing & cost (Aug 2026 RunPod rates)

| GPU | Config | ~time / 5s 720p clip | ~cost / clip |
|---|---|---|---|
| L40S 48GB $0.99/hr | offload on, distill | 1–2 min | **£0.02–0.04** |
| A100 80GB $1.39/hr | offload off, distill | ~1 min | £0.02–0.03 |
| H100 serverless $4.55/hr | offload off, distill | ~40–70s | £0.04–0.07 |
| RTX 4090 24GB $0.69/hr | offload on, 480p | 2–4 min | £0.02–0.05 |

Times are estimates pending live validation on the endpoint — treat the first
deploy as a benchmark run (`generation_s` is reported in every response).

## Setup

1. Create a RunPod network volume (≥100GB), mount at `/runpod-volume`.
2. From any pod with the volume:
   `HF_HOME=/runpod-volume/hf_cache python preload_models.py`
3. Build/push the image, create the serverless endpoint with the volume
   attached and env: `SUPABASE_URL`, `SUPABASE_KEY`, `SUPABASE_BUCKET`.

## API

Single clip:

```json
{"input": {
  "image_url": "https://.../bmw-m4.jpg",
  "preset": "orbit",                  // or free-form "prompt"
  "resolution": "720p",               // or "480p"
  "num_frames": 81,                   // 81 @ 16fps ≈ 5s
  "seed": 42,                         // optional, for reproducibility
  "object_name": "clips/bmw-m4.mp4"   // optional Supabase key
}}
```

→ `{"status": "success", "video_url": "...", "generation_s": 48.2, ...}`
(`video_b64` inline when small or when Supabase isn't configured).

Presets: `orbit`, `orbit_reverse`, `headlights`, `damage_pan`,
`scanner_sweep`, `interior_sweep`, `push_in`, `wheel_detail` (see `shots.py`).

B-roll batch (run overnight on a cheap pod, not serverless):

```json
{"input": {
  "mode": "broll",
  "source_image_url": "https://.../workshop-car.jpg",
  "shots": [{"id": "workshop/wheel_off"}, {"id": "custom/x", "prompt": "..."}]
}}
```

Omitting `shots` builds the full standard library from `shots.BROLL_LIBRARY`.
Each clip uploads to `broll/<id>.mp4` — the key `tutorials/` looks up.

## Env reference

| Var | Default | Notes |
|---|---|---|
| `WAN_MODEL` | `Wan-AI/Wan2.2-I2V-A14B-Diffusers` | |
| `DISTILL` | `1` | 8-step distilled sampling |
| `DISTILL_LORA_REPO/HIGH/LOW` | lightx2v repo + filenames | override if repo layout changes |
| `STYLE_LORA` / `STYLE_LORA_WEIGHT` | empty | automotive LoRA drop-in |
| `CPU_OFFLOAD` | `1` | set `0` on 80GB GPUs for speed |
| `RESOLUTION` / `NUM_FRAMES` / `FPS` | `720p` / `81` / `16` | |
| `SUPABASE_URL/KEY/BUCKET` | — | delivery (bucket default `car-videos`) |

## Status

- [x] Handler, presets, batch mode, Supabase delivery, distill fallback
- [ ] Live GPU validation (distill LoRA filenames + timing benchmarks)
- [ ] Automotive LoRA training (musubi-tuner; needs video clips, not stills)
