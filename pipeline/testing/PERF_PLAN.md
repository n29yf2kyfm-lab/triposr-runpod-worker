# Mobile performance test plan — ExpertCarCheck 3D viewer

All tools free/open-source. The 3D viewer must **not** wreck the main page's
performance, so it is measured both in isolation and embedded.

## Budgets (fail the build if exceeded)

| Metric | Target (mid mobile) | Hard fail |
|---|---|---|
| GLB transfer (Draco+WebP) | ≤ 1.5 MB | > 2.5 MB |
| Time to first interactive spin | ≤ 2.5 s on 4G | > 5 s |
| Largest Contentful Paint (page) | ≤ 2.5 s | > 4 s |
| Interaction to Next Paint | ≤ 200 ms | > 500 ms |
| Cumulative Layout Shift | ≤ 0.05 | > 0.1 |
| JS added by viewer (gzipped) | ≤ 180 KB | > 300 KB |
| Sustained frame rate while orbiting | ≥ 45 fps | < 30 fps |
| Draw calls per frame | ≤ 60 | > 120 |

## 1. Lighthouse (page-level) — Apache-2.0
```bash
# viewer served at :8080; run against the embedding page, mobile preset
npx --yes lighthouse "http://localhost:8080/viewer/index.html" \
  --preset=perf --form-factor=mobile --throttling-method=simulate \
  --output=json --output-path=pipeline/reports/lh_viewer.json --quiet --chrome-flags="--headless=new"
# gate: read categories.performance.score and the LCP/INP/CLS audits
node -e "const r=require('./pipeline/reports/lh_viewer.json');const a=r.audits;\
console.log('perf',r.categories.performance.score,'LCP',a['largest-contentful-paint'].displayValue,\
'CLS',a['cumulative-layout-shift'].displayValue,'TBT',a['total-blocking-time'].displayValue)"
```

## 2. Frame rate + draw calls — Playwright + WebGL stats
Sample `renderer.info.render.calls` and rAF delta over a scripted 360° drag;
assert median fps ≥ 45 and draw calls ≤ 60 (hook exposed on `window.__viewer`).

## 3. Spector.js (GPU frame capture) — MIT
Load the viewer with the Spector.js browser extension (or the injected script),
capture one frame while orbiting, and inspect for: excessive draw calls,
duplicate texture binds, redundant render passes, oversized textures. Export the
capture to `pipeline/reports/spector_golf.json` and attach to the release.

## 4. Device matrix
Run §1–2 headless-emulated for: **desktop**, **iPhone 13** (mid), **Moto G Power / Pixel 4a** (low-memory). Produce one 2K/1K/512 KTX2 (or WebP) texture tier per class once `toktx` is installed; low-memory tier must stay < 40 MB GPU texture memory.

## 5. Regression gate (CI)
`node pipeline/validate.js` (0 errors) **and** Lighthouse perf ≥ 0.85 **and**
Playwright acceptance green → allow release. Any red = block.
