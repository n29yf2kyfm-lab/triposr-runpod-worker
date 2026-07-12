# Corpus — Zero-Cost Build Plan (v0.1)

A rewrite of the original Master Build Plan re-optimized around one constraint:
no paid infrastructure, no paid tier. Everything that existed only to support a
£9.99/mo paid tier is cut or reworked.

## 1. What changed and why

The original plan split into a free on-device path and a paid server path
(RunPod GPU inference, Stripe, DEXA calibration, unlimited chat). Remove the
paid tier and everything downstream disappears:

| Cut | Why |
|---|---|
| RunPod serverless GPU inference (paid scans) | No revenue to fund it |
| Stripe + subscription billing | No paid tier |
| DEXA calibration upload | Paid-only feature |
| Self-hosted dedicated LLM pod | Replace with a free-tier hosted model |
| Weekly deep analysis via paid API | Move to a free reasoning model, rate-limited |
| Overage billing | No billing at all |

Every user gets the same experience: on-device reconstruction, all anatomy
layers, the same coach.

## 2. Revised stack (target: £0/month recurring)

| Layer | Component | Cost |
|---|---|---|
| Frontend (prod) | Next.js on Cloudflare Pages | Free |
| 3D viewer | three.js + react-three-fiber | Free (MIT) |
| Reconstruction | SAM 3D Body, on-device (WebGPU/Core ML/TFLite) | £0 |
| Auth + DB | Supabase free tier | £0 to the ceiling |
| Storage | Cloudflare R2 free tier | £0 to the ceiling |
| Coach | Free-tier hosted model, or on-device small model | £0, rate-limited |
| Analytics / errors | PostHog / Sentry free tiers | £0 |
| Payments | None | — |

Unavoidable: a domain (~£10–15/yr), and Apple (£79/yr) / Google (£25 one-off)
if you ship native apps — otherwise ship a PWA first and skip both.

## 3. The one real tradeoff: the coach

LLM inference costs something somewhere. Three options:
1. Free-tier hosted API — simplest, rate-limited.
2. In-browser small model (WebLLM) — genuinely £0, weaker, higher device needs.
3. Drop the always-on coach for v1; ship static summaries from the regressor's
   own output (no LLM). **Recommended for beta.**

## 4. Build phases

- **Phase 0** — verify SAM 3D Body works (1 week)
- **Phase 1** — NHANES regressor + shell (3–4 weeks) ← *regressor done, verified*
- **Phase 2** — on-device WebGPU pipeline (4–6 weeks) — now the only recon path
- **Phase 3** — anatomy viewer (4–5 weeks)
- **Phase 4** — coach, scoped per §3 (1–2 weeks)
- **Phase 5** — trends + comparison (2 weeks)
- **Phase 6** — native apps, optional (a PWA covers most for £0)
- **Phase 7** — compliance foundation, scoped down
- **Phase 8** — beta + launch (4–6 weeks)

Web-only launch, solo/part-time: ~6–9 months.

## 5. Risk register (top items)

- **On-device inference on low-end devices** is now the *only* path — no server
  fallback. Mitigation: a lighter model tier for old devices, be upfront that
  quality scales with the device.
- **The ViT-H memory wall** (see `CORPUS_REVIEW.md` Blind Spot B): a 637M-param
  encoder won't fit mobile WebGPU budgets. Switch to a quantized MobileSAM /
  SAM-tiny ONNX model.
- **Compliance** still applies — you're processing biometric data even for free.
  Privacy policy, a DPIA at scale, and real data-deletion are still needed.

## 6. Open question

If it's free forever, what is it for — a portfolio piece, a public-good tool, a
donation project, or a free front-end for later B2B (gym) licensing? Doesn't
block Phases 0–2, but decide it before launch.
