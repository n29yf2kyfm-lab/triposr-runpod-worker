# tutorials/ — on-demand tutorial video assembler (CPU, pennies per video)

Turns a request like *"how to change front brake pads, for a 2020 Golf R"*
into a finished, narrated, subtitled tutorial video in **16:9 (YouTube) and
9:16 (TikTok/Shorts)** — for a marginal cost of a few pence.

## The economic architecture (read this before changing anything)

The 20p-per-video ceiling at 200k-video scale only holds because of a hard
split, enforced by which code lives in which worker:

| | `wan/` (GPU) | `tutorials/` (this, CPU) |
|---|---|---|
| Runs | batch, off-peak | in the request path |
| Does | generates b-roll clips ONCE into a shared library | assembles existing clips + TTS + cards |
| Cost | one-time (~4p/clip, amortized to ~0p) | ~2–4p per unique video, ~0p cached |

**Rule 1: no diffusion in the request path.** A step whose b-roll clip is
missing renders as a text card — the video still ships, and the response's
`timings.missing_broll` lists what to queue for the nightly `wan/` batch.

**Rule 2: cache at every level.** Videos are content-addressed
(template bytes + vehicle + voice + format + pipeline version); a repeat
request returns the stored MP4 URL with zero compute. B-roll clips cache on
local disk between requests.

**Rule 3: assembly is CPU-only.** The Dockerfile has no CUDA on purpose.

## The accuracy contract

The AI never invents mechanical facts. Every procedure is a human-verified
YAML template (`procedures/*.yaml`) — steps, warnings, order, torque notes.
The pipeline words it (optional LLM polish that must preserve every fact),
voices it (Kokoro TTS, British voice by default), and illustrates it
(library b-roll + rendered step cards). Safety-critical templates
automatically get a disclaimer card. **A human reviews every new template
before it ships** — that's the whole safety/liability position.

## Pipeline

```
procedure.yaml ──> script (deterministic; optional LLM polish)
                     ├─> Kokoro TTS per step (CPU, free)
                     ├─> b-roll fetch from library (Supabase, disk-cached)
                     └─> ffmpeg: title/disclaimer/tools cards + steps with
                         lower-thirds + narration + burned subtitles + outro
                           ├─> 1280x720 MP4  (YouTube)
                           └─> 1080x1920 MP4 (TikTok/Shorts)
                     └─> upload to Supabase; optional publish
```

## API

```json
{"input": {
  "procedure": "brake_pads_front",
  "vehicle": "a 2020 Golf R",          // optional, personalizes narration+title
  "formats": ["landscape", "portrait"], // default both
  "voice": "bf_emma",                   // optional Kokoro voice
  "subtitles": true,
  "force": false,                       // true = re-render despite cache
  "publish": false                      // true = push to YouTube/TikTok
}}
```

→ `{"outputs": {"landscape": {"video_url": ..., "cached": false, ...},
"portrait": {...}}, "timings": {...}}`.

`{"input": {"mode": "list"}}` lists available procedures. Local dev without
RunPod: `python handler.py --local '{"procedure": "brake_pads_front"}'`
(set `ALLOW_SILENT=1` to run without the Kokoro model files).

## Publishing (off by default)

- **YouTube**: set `YT_TOKEN_JSON` (OAuth refresh-token JSON). Mind the
  quota: an upload costs 1600 of the default 10k daily units ≈ 6 uploads/day
  — request a quota extension before launch. Uploads are `unlisted` by
  default (`YT_PRIVACY`), and the synthetic-media disclosure flag is set.
- **TikTok**: stub until the Content Posting API audit is granted
  (unaudited apps can only post private drafts).

## Env reference

| Var | Default | Notes |
|---|---|---|
| `SUPABASE_URL/KEY/BUCKET` | — / — / `car-videos` | storage + cache backend |
| `LLM_PROVIDER` | empty (off) | `anthropic` or `gemini` narration polish |
| `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` | — | for the above |
| `TTS_VOICE` / `TTS_SPEED` | `bf_emma` / `1.0` | Kokoro voice |
| `ALLOW_SILENT` | off | dev only: silence instead of TTS |
| `OUTRO_TEXT` | `ExpertCarCheck` | branding on cards |
| `BROLL_CACHE_DIR` | `/tmp/broll_cache` | persistent disk speeds repeats |
| `YT_TOKEN_JSON`, `TIKTOK_ACCESS_TOKEN` | — | publishing credentials |

## Adding a procedure

1. Copy `procedures/brake_pads_front.yaml`, write the steps — narration in
   plain language, `broll` keys from the library (`wan/shots.py`), card
   bullets for the on-screen text. Get it reviewed by someone who knows the
   job.
2. If it needs new b-roll shots, add them to `wan/shots.py::BROLL_LIBRARY`
   and run a `mode: "broll"` batch on the wan worker.
3. Deploy — the first request renders and caches each variant.

## Status

- [x] Deterministic script gen + LLM polish hooks, Kokoro TTS, ffmpeg
      assembly (both formats, subtitles, card fallbacks), content-addressed
      cache, YouTube upload, unit tests
- [ ] End-to-end render validation in the built image (ffmpeg/libass paths)
- [ ] TikTok Content Posting API flow (blocked on app audit)
- [ ] More procedure templates (human-verified)
