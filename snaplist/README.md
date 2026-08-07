# SnapList

**One photo → an SEO-optimized eBay listing → an auto-generated TikTok/Reels promo.**

A working prototype of the wedge identified in the feasibility research: the
market has cross-listing tools *and* video-marketing tools, but nothing that
stitches them together. SnapList does the whole chain from a single photo:

```
photo ─▶ identify ─▶ price ─▶ write listing (SEO) ─▶ promo video ─▶ publish to eBay
```

It runs **end-to-end with zero setup** on realistic demo data, and turns into the
live product as you add API keys — one integration at a time.

---

## Quick start

```bash
cd snaplist
cp .env.example api/.env      # optional — works without it
./run.sh
```

Then open **http://localhost:5173**. (Or run the two halves manually — see below.)

### Run the halves manually

```bash
# API  (http://localhost:8000)
cd api
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Web  (http://localhost:5173)  — in a second terminal
cd web
npm install
npm run dev
```

---

## Demo mode vs. live

Every integration is optional. With no keys, each provider returns realistic
sample data so you can click the whole flow. Add a key in `api/.env` and that
step goes live — the header shows a green dot for each live integration.

| Step | Live provider | Env key | Without it |
|------|---------------|---------|------------|
| Identify item | Anthropic Claude vision | `ANTHROPIC_API_KEY` | Sample identification |
| Market price | SerpApi (Google Shopping) | `SERPAPI_KEY` | Sample comps |
| Listing copy + SEO | Anthropic Claude | `ANTHROPIC_API_KEY` | Assembled from the item |
| Promo video | Creatify / Veo (pluggable) | `VIDEO_PROVIDER` + `VIDEO_API_KEY` | Storyboard + caption only |
| Publish | eBay Sell Inventory API | `EBAY_CLIENT_ID` + `EBAY_USER_TOKEN` | Draft (not sent) |

> **Why eBay first?** It's the only major marketplace with a clean, sanctioned
> listing API for general goods. Amazon is heavy (Pro plan + review), and
> Facebook Marketplace / Poshmark / Mercari have **no public API** — see the
> feasibility brief. eBay Sandbox lets you test real publishing with no fees and
> nothing going live.

### Before your first real publish

eBay enforces several things only at publish time, and it does **not** fall back
to account defaults. To publish you must:

1. **Opt into Business Policies** in eBay Seller Hub, and have one payment, one
   return and one shipping policy. All three IDs are required on every offer —
   the app looks up your first of each kind unless you set `EBAY_*_POLICY_ID`.
2. **Know your category.** eBay's category-suggestion API is not supported in
   Sandbox (it returns boilerplate), so Sandbox runs use
   `EBAY_FALLBACK_CATEGORY_ID`. Production resolves the category from the title.

The app creates the required **inventory location** for you, and uploads the
photo to eBay's own image hosting so you don't need to host images publicly.
If any prerequisite is missing, publish fails with a message naming it rather
than sending a request eBay will reject.

### Tests

```bash
cd api && .venv/bin/python -m pytest tests/ -q
```

The publish path is a multi-call sequence whose requirements eBay only enforces
at the last step, so the tests stand up a fake eBay and assert on the **actual
requests sent** — that policies, location, `GTC` duration, a real condition
enum, an image and a category are all present. That's verifiable without
credentials; a live Sandbox run is not.

---

## How it's built

```
snaplist/
├── api/                     FastAPI backend
│   └── app/
│       ├── main.py          endpoints: /identify /price /listing /video /publish
│       ├── config.py        keys + live/demo flags
│       ├── schemas.py       pydantic models shared across the pipeline
│       └── providers/       one module per step, each with a live + mock path
│           ├── vision.py    photo → item (Claude); refuses to guess a fake SKU
│           ├── pricing.py   comparable prices (SerpApi)
│           ├── listing.py   SEO title/description/item-specifics (Claude)
│           ├── video.py     promo storyboard + caption (+ pluggable render)
│           └── ebay.py      Inventory API: inventory item → offer → publish
└── web/                     React + Vite + TypeScript
    └── src/App.tsx          the step-by-step flow (edit results between steps)
```

**Design notes worth knowing**

- *Identification is human-confirmed.* The vision prompt is told never to invent
  a model number it can't see — a blank + low confidence beats a wrong SKU, which
  would cascade into a wrong price and a bad listing. The UI flags low confidence.
- *Listing generation targets real ranking factors* — a keyword-front-loaded
  title within eBay's 80-char limit and **complete item specifics** (completeness
  lifts Cassini rank more than prose).
- *The marketing brain needs no video API.* The storyboard, hook, caption and
  hashtags are generated regardless; a video key only renders the actual clip.

---

## Roadmap (from the feasibility brief)

- **V2 — real auto-posting** of the promo to TikTok + Instagram/Facebook (via an
  aggregator first to skip the multi-week platform audits).
- **V3 — more channels, honestly labeled**: Etsy via API; Poshmark / Mercari /
  Facebook Marketplace via browser-assisted "one-tap fill" (no public API exists,
  so these are assisted, not magic).

This is a prototype — auth, payments, background jobs and multi-user storage are
intentionally out of scope for the first slice.
