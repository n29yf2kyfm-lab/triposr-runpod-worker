# Code review — branch `claude/lovable-connection-ki7jch`

**Reviewed:** 2026-07-26 · **Head:** `f77ac70` · **Base:** `main` (`2d622c2`)
**Scope:** the code surface of the branch (frontend-facing TypeScript, Supabase
edge functions, RunPod worker handlers, ingest/QC/catalogue pipeline). The
~137k lines of generated data (`catalogue.v2.json`, `vehicle_index.json`,
`oem-paints.json`, backups) and the committed 25 MB `render/assets/hdri.hdr`
were **not** line-reviewed.

## What this branch is

`claude/lovable-connection-ki7jch` was the original working branch behind merged
PRs #1–#11, but it has since grown into a **500-commit, ~164k-line standalone
platform** ("Expert Car Check Pro": UK reg → interactive 3D car). It has **not**
been merged into `main` and has **no open PR**. CI (`render`, `trellis`,
`groundedsam`, `hunyuan`, `catalogue-gate`) is wired to build/push Docker
`:latest` images and run gates directly off this branch, so it behaves as a
de-facto second trunk feeding the live RunPod endpoints. The catalogue-gate is
currently green.

The "lovable connection" is the seam between the Lovable frontend and this
backend: the `resolve-vehicle` + `dvsa-lookup` edge functions, the `src/lib`
TypeScript the app imports, the served `catalogue.v2.json`, and the render
worker. Findings below are concentrated there.

Severities: **CRITICAL** = breaks or exposes the live connection; **MAJOR** =
wrong results / real risk under normal use; **MINOR** = robustness/hygiene.
Each finding is tagged `[verified]` (I read the exact lines) or `[reported]`
(surfaced by a review pass, consistent with the code but not line-verified here).

---

## CRITICAL

### C1. CORS preflight throws → both edge functions unreachable cross-origin `[verified]`
`platform/resolver/index.ts:161` and `platform/dvsa-lookup/index.ts:50` handle
`OPTIONS` with `return json({}, 204)`, and `json()` builds
`new Response(JSON.stringify(body), { status })` — i.e. `new Response("{}", {status:204})`.
Deno throws `TypeError: Response with null body status cannot have body` for a
204/205/304 with a non-null body. Every browser CORS preflight therefore 500s
with no CORS headers, and the browser blocks the real request — **the public
frontend cannot call either function cross-origin at all.**
**Fix:** `return new Response(null, { status: 204, headers: cors })` for OPTIONS.

### C2. Supabase RLS enabled on only 1 of 12 catalogue tables `[verified]`
`platform/schema.sql` creates 12 tables but only `variants` gets
`enable row level security` (line 159) + a read policy (162). The other 11
(`manufacturers`, `models`, `generations`, `engines`, `trims`, `colours`,
`wheels`, `licences`, `assets_3d`, `render_sets`, `specifications`) have RLS
disabled. Supabase grants `anon`/`authenticated` full DML on `public` by
default, so with RLS off, anyone holding the public anon key (shipped in the
frontend) can `INSERT`/`UPDATE`/`DELETE` — e.g. repoint `assets_3d.glb_url` at a
malicious payload. **Conditional:** only bites if `schema.sql` was actually run
in the app's Supabase (the deployed resolver reads a storage JSON, not these
tables — see M-README). Treat as CRITICAL for any environment where the schema
is live.
**Fix:** `alter table … enable row level security;` + `for select using (true)`
(and no write policy) on every table.

### C3. SSRF via user-supplied URLs in worker handlers `[verified pattern]`
`trellis/handler.py:176`, `hunyuan21/handler.py:74`, and `render/handler.py:362`
(`glb_url` built at 353-356) `requests.get()` a fully user-controlled URL with
no scheme/host allowlist. A caller passing
`image_url: "http://169.254.169.254/latest/meta-data/…"` or an internal address
makes the GPU worker fetch it; combined with the Supabase creds in the worker
env this is a credential/metadata exfiltration vector.
**Fix:** require http(s), resolve the host, and reject
private/loopback/link-local ranges before fetching.

---

## MAJOR

### M1. `dvsa-lookup` reads the registration from the query string → logged `[verified]`
`platform/dvsa-lookup/index.ts:54` does
`reg = url.searchParams.get("reg") ?? (await req.json()…).reg`, and the 400
message (line 57) advertises `?reg=…`. A `GET ?reg=AB12CDE` puts the plate in
the request URL, which Supabase/edge/CDN/proxy access logs persist — a direct
breach of the project's "the reg is never keyed, indexed or stored" rule, even
though the function body itself never logs it.
**Fix:** accept the reg only via the POST body; drop the query-param path and
the `?reg=` hint.

### M2. CORS response omits `access-control-allow-headers` `[verified]`
`platform/resolver/index.ts:157` sets only `access-control-allow-origin`. A
cross-origin JSON POST (`Content-Type: application/json`) is not a "simple"
request, so even after C1 is fixed the preflight fails for lack of an allowed
`content-type` header.
**Fix:** add `access-control-allow-headers: content-type, authorization, apikey`
and `access-control-allow-methods: POST, OPTIONS`.

### M3. `resolver.loadData` has no error handling / no stale fallback `[verified]`
`platform/resolver/index.ts:48-56` does `(await fetch(...)).json()` with no
`r.ok` check and no try/catch, and the handler (line 168) never wraps it. A
storage 404/5xx or non-JSON body throws uncaught → 500 default error page, and a
single storage blip takes the whole resolver down with no last-good cache.
**Fix:** check `r.ok`, wrap in try/catch returning a controlled 503, serve the
last cached catalogue on failure.

### M4. The `"exact"` resolution tier is dead code `[verified]`
`platform/resolver/index.ts:198` sets `type = "exact"` only when
`best.matched.includes("derivative")`, but `"derivative"` is never pushed in
`scoreAsset` (grep-confirmed: it appears only on line 198). So `resolution.type`
can never be `"exact"` — genuinely exact assets are always labelled
`"generation-correct"`. (The legacy `match` field is unaffected.)
**Fix:** push `"derivative"` when `exactDerivative`/trim actually matches, or
drop the branch.

### M5. Representative fallback can serve a wrong-generation shell `[verified, nuanced]`
In `scoreAsset` (`platform/resolver/index.ts:126-146`) a generation conflict is
rejected only when **both** the request and the asset carry a generation
(127-131), and the ±1-year gate only applies when the asset has `yearStart`
(133). A make+model match alone scores 40 = `MIN_SCORE`, served as
`representative`. **Mitigations that make this less severe than first flagged:**
the recent enrichment backfilled `yearStart` to 100% of assets, and the year
gate (135) *does* reject out-of-range years — so a 2023 Golf will not match a
Mk7 (2013-2020) **when the decode carries a year**. The residual risk is a
lookup with no year (or no generation on either side): it silently picks *some*
generation, and ties break on catalogue array order (see m-tiebreak), so it may
be the wrong or lower-quality one. The `representative` disclosure covers this,
but the "wrong-generation serves are impossible" claim in the lib header is not
true.
**Fix:** when `MIN_SCORE < 75`, require a confirmed generation match or an
in-range year before allowing a `representative` serve; add deterministic
secondary sort keys.

### M6. `store()` clones the Golf entry as a template — latent field leak `[verified, downgraded]`
`pipeline/ingest/pipeline.py:308` builds each new catalogue entry from
`copy.deepcopy` of the VW Golf row, then `.update()`s a subset of fields. Any
key **not** in the update dict is silently inherited from Golf. I diffed the
keys: today the leaked fields are all benign defaults
(`sourceCreator=null`, `hasInterior=false`, `supportsOpenableParts=false`,
`triangleCount=null`, no `recolourAudit`), so this is **not** currently a
CC-BY-attribution or false-interior bug (contrary to the initial flag). It is a
real *latent* trap: the day the Golf row gains an interior, a creator, or a
stale audit stamp, every subsequently ingested car inherits it. Also
`platesBaked/textureOptimised/webOptimised=true` and `schemaVersion` are
inherited assertions that may not hold for a given asset, and there are 2 Golf
rows so `[0]` is order-dependent.
**Fix:** build the entry from an explicit literal field dict, not a deepcopy of
another car.

### M7. Storage key `slug(assetId)` vs dedup on raw `assetId` → mesh collision `[verified]`
`pipeline/ingest/pipeline.py:254` keys storage on `slug(spec["assetId"])` while
the catalogue dedup (line 340) filters on the exact `assetId`. Two assetIds
differing only in case/punctuation slug to the same path: asset B's GLB
overwrites A's at the shared storage key, while A's catalogue row survives and
now resolves to B's mesh (`verify_asset` passes — both are valid GLBs). The
comment at 250-253 claims assetId-keying prevents this; it doesn't, because the
key is `slug(assetId)`, not `assetId`.
**Fix:** dedup/collision-check on `slug(assetId)` (the real storage key).

### M8. `store()` commits the local catalogue before the remote upload `[verified]`
`pipeline/ingest/pipeline.py:345` does `os.replace(tmp, CAT)` (local commit)
*before* the Supabase upload at 346-347. If the upload raises, the local
`catalogue.v2.json` already contains the entry while the served copy the
frontend hits does not — a persistent local/remote divergence with no rollback.
(The read-back at 358 aborts loudly but after local is already committed.)
**Fix:** upload + read-back-verify first, `os.replace` the local file only after
remote success.

### M9. `finished/index.json` is keyed on make+model, evicting variants `[verified]`
`pipeline/ingest/pipeline.py:352` rebuilds the index filtering
`not (make==make and model==model)` — contradicting the assetId-keying used
everywhere else. Storing a second generation/year of the same make+model
silently drops the first from this index.
**Fix:** key the filter on `assetId`.

### M10. `build_index.py` — master-model enrichment is dead, counters wrong `[reported]`
`platform/catalogue/build_index.py:250-267` computes `m = match_master(...)` but
the appended row never reads `m`, so the documented "inherit year/trim from
parent master" never happens; `assets_inherited_yeartrim`/`assets_no_yeartrim`
are computed from `c.yearStart` presence, so the published coverage counts are
wrong.
**Fix:** use `m` to fill null year/trim, or delete the dead match and fix the
counters.

### M11. `build_index.py` `pick()` falls back to `cands[0]` on generation mismatch `[reported]`
`platform/catalogue/build_index.py:229-242`: when no candidate matches the master
row's generation, `pick()` returns `cands[0]` and then overwrites that row's
`year_from/year_to` with the picked asset's years. A distinct master generation
with no matching asset gets attached to an unrelated-generation asset and
relabelled to its years → wrong-generation model + fabricated year span in the
index.
**Fix:** when `gen` is set and no candidate matches, leave `has_3d=False`.

### M12. `asset_audit.py` G4 false-rejects untextured wheels `[reported]`
`pipeline/qc/asset_audit.py:135-153`: a car with no `wheel`-named material whose
wheel-region faces have no sampleable texture (`stdv is None`) is hard-rejected.
A clean model using plain/vertex-coloured PBR wheels is wrongly culled.
**Fix:** treat `stdv is None` (nothing to assess) as pass-with-warning.

### M13. Unbounded numeric inputs → GPU DoS `[verified pattern]`
`render/handler.py:1057-1059` (`samples`/`width`/`height`) and
`trellis/handler.py:191-197` (`texture_size`/`decimation_target`/`num_samples`)
cast user input to int but never clamp. `width:100000` or `samples:10_000_000`
OOMs the GPU or renders forever on an expensive instance.
**Fix:** `min(int(...), CAP)` per knob.

### M14. `groundedsam` crashes on an empty mask `[reported]`
`groundedsam/handler.py:88`: `np.vectorize(...)(cur)` on a size-0 array (a DINO
box whose SAM mask has no pixels > 0.5) raises `ValueError`, and the handler has
no try/except, failing the whole batch.
**Fix:** `if cur.size == 0: continue` (or pass `otypes=[np.int64]`).

### M15. Worker output files are never cleaned up → volume fills `[reported]`
`trellis/handler.py:242/263` and `hunyuan21/handler.py:103/109/111` write GLB/PNG
into the shared network volume and never delete them; the volume grows until
writes fail for all jobs. (`render`/`store` do clean up — inconsistent.)
**Fix:** delete local artifacts in a `finally` after upload.

### M16. `normaliseModel` fallback returns the whole string including trim `[reported]`
`src/lib/vehicle-normalisation.ts:50-51` returns `slug(c)` of the entire cleaned
model string despite the comment promising "first non-trim token". DVLA
"Golf Match" → `golf-match`, which never equals an asset's `golf` family, so a
catalogued car resolves to `unavailable`.
**Fix:** fall back to the first non-trim token / alias family key.

### M17. `customization-builder` launders unvalidated strings via `as any` `[reported]`
`src/lib/customization-builder.ts:106-121`: `family`, `finish`, and `wraps` are
`as any`-cast into the `ColourFamily`/`WrapFinish` union types, so
`family:"burgundy"` passes straight through and the frontend does a palette
lookup that returns nothing/wrong with no guard.
**Fix:** validate against the unions (map or reject unknowns).

### M18. Test suite misses the consequential paths `[reported]`
`tests/resolver/resolver.test.ts:141-149` wraps its only assertion in
`if (r.asset)`, passing vacuously if resolution regresses to null; every asset
factory has full generation+year, so the deployed thin-metadata `minScore:40`
path (M5), the ±1-year boundary, the `"exact"` branch (M4), and tie-breaking are
untested.
**Fix:** assert non-null first; add thin-metadata / boundary / tie-break cases.

### M19. `render` clobbers the caller's `bright` flag `[reported]`
`render/handler.py:628`: inside the clay-trim loop `bright = min(v...) > 0.45`
reassigns the job-input parameter `bright`, later read at 791 to pick the
backdrop. The user's `bright` request is overwritten by the last trim material
(observable when `studio=False`).
**Fix:** rename the loop-local.

---

## MINOR / hygiene

- **CI ships off an un-reviewed branch** `[verified]` — every workflow triggers on
  `claude/lovable-connection-ki7jch` and pushes Docker `:latest`; whatever lands
  here reaches the live endpoints without a PR gate.
- **Committed Python bytecode** `[verified]` — `pipeline/trellis/__pycache__/*.pyc`
  are tracked despite being in `.gitignore`. `git rm --cached` them.
- **25 MB binary in git** `[verified]` — `render/assets/hdri.hdr` bloats history
  permanently; consider Git LFS or fetch-at-build.
- **Stale `platform/README.md`** `[verified]` — documents a "hashed VRM" +
  `SUPABASE_SERVICE_ROLE_KEY`/`VRM_PEPPER` contract the deployed resolver doesn't
  use (it reads public storage, no service key, no VRM). Following it would
  over-privilege the function and re-introduce reg-keying. Update to match.
- **Hardcoded project URL** `[verified]` — `platform/resolver/index.ts:32` bakes
  the Supabase project ref into source (public URL, not a secret, but blocks
  staging). Read from `Deno.env`.
- **`migrate_catalogue.py:116-118`** `[reported]` — expands a single stated year to
  `ys-1 … ys+1`, inventing a 3-year span (soft "no fabricated metadata"
  violation). Use `ys` for both bounds.
- **`migrate_catalogue.py:35-39`** `[reported]` — `GEN_PATTERNS` `[wcefgj]\d{2,3}`
  matches trims as generations ("C63" → generation `c63`). Anchor to a chassis
  whitelist.
- **PNG bytes at a `.jpg` path** `[verified]` — `pipeline/ingest/pipeline.py:290`
  uploads PNG bytes to `…/{sl}.jpg` with `image/png`. Make extension, bytes and
  content-type agree.
- **`bool("false") === true`** `[reported]` — `render/handler.py:1060-1065` coerces
  `studio`/`bright`/`plates_both` with `bool()`, so a JSON string `"false"`
  becomes `True`. Parse truthiness explicitly.
- **No outbound timeouts/retries** `[verified]` — edge-function and worker fetches
  lack `AbortSignal.timeout`/retry; a hung upstream stalls to the platform wall
  clock.
- **Handlers without try/except** `[reported]` — `groundedsam`/`hunyuan21` bodies
  aren't wrapped, so decode/model errors surface as ungraceful worker crashes
  (inconsistent with `render`/`trellis`).
- **Non-atomic stamp write** `[reported]` — `pipeline/qc/recolour_audit.py:33-41`
  writes `catalogue.v2.json` in place (no temp+rename); a crash mid-write
  corrupts the file the gate reads. (`store()` does this correctly — copy it.)
- **Cyrillic homoglyph in log strings** `[reported]` —
  `pipeline/ingest/pipeline.py:111,119` contain a Cyrillic "Т" in "glTF"
  messages (cosmetic; byte compare is correct ASCII).

---

## Positives (checked, sound)

- **No hardcoded secrets** anywhere — all Supabase/RunPod/DVSA creds come from
  `os.environ` / `Deno.env` (full-repo scan clean).
- **OEM paint resolver is compliant** with the documented safety workflow:
  filter by manufacturer → filter by DVLA broad colour → image analysis only
  *ranks* the filtered set → `confirmed` is a hard `false` → caption is always
  the unconfirmed "Possible OEM colour:" form (`src/lib/oem-paint-resolver.ts`).
- **No path traversal** in worker output keys (job-id / uuid / fixed temp names,
  none user-derived); the reg is `encodeURIComponent`-wrapped (no
  injection/SSRF via the plate).
- **`variants_hash`** in `gate_catalogue.py` and `recolour_audit.py` are
  byte-identical, so the stale-stamp gate is sound (guard with `sort_keys=True`
  if `colourVariants` ever holds nested objects).

---

## Recommended order

1. **C1** (one line) — nothing cross-origin works until it's fixed.
2. **C2 / C3 / M1** — security & privacy exposure on the live path.
3. **M2, M3, M13, M15** — the connection is fragile without them.
4. Resolver correctness: **M4, M5, M16, M17, M18**.
5. Pipeline data-integrity: **M6, M7, M8, M9, M10, M11, M12**.
6. Hygiene sweep (MINOR) as a single cleanup pass.
