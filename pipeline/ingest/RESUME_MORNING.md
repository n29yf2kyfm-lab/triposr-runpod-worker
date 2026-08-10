# Morning resume — paused 2026-08-10 ~01:05

Paused deliberately to stop burning credit while Sketchfab's download quota was
exhausted. Nothing was mid-flight and nothing is lost: every wave is resumable
against the bucket, and the hard-reject cache means no download is re-paid.

## State at pause

| | |
|---|---|
| RunPod balance | $30.06 |
| render-v2 endpoint | **workersMax scaled 9 -> 0** |
| Sketchfab | all 3 accounts hard-429 since ~00:35 |
| Supervisor / prober / waves | all stopped |
| Live catalogue | 864 approved |

Endpoint config before the pause is saved at `/tmp/endpoint_state_before_pause.json`
(render-v2 min=0 max=9; trellis2-v2 min=0 max=0; building-scan min=0 max=1).
`/tmp` does not survive a container rollback — the only value that matters is
**render-v2 max = 9**.

## Resume, in order

1. Check Sketchfab is actually open before anything else. If this still 429s,
   there is no point starting workers:
   ```
   set -a; . /root/.alam3d_env; set +a
   python3 - <<'PY'
   import os, json, urllib.request, urllib.error
   toks=[t.strip() for t in os.environ['SKETCHFAB_TOKENS'].split(',') if t.strip()]
   uid=json.load(open('/tmp/nissan/manifest.filtered.json'))[0]['uid']
   for n,t in enumerate(toks,1):
       rq=urllib.request.Request(f"https://api.sketchfab.com/v3/models/{uid}/download",
           headers={"Authorization":f"Token {t}","User-Agent":"Mozilla/5.0"})
       try: urllib.request.urlopen(rq,timeout=25); print(f"token{n}: OPEN")
       except urllib.error.HTTPError as e: print(f"token{n}: {e.code}")
   PY
   ```
2. Restore render workers:
   ```
   curl -X PATCH -H "Authorization: Bearer $RUNPOD_API_KEY" \
     -H "Content-Type: application/json" -d '{"workersMax":9}' \
     https://rest.runpod.io/v1/endpoints/ng8oiz4p2l0xa0
   ```
   The first submit after a scale change can return **HTTP 409** while the
   endpoint settles — retry with backoff, it is not a failure.
3. Clear stale benches, then start the supervisor and the prober:
   ```
   rm -f /tmp/*/BENCH_UNTIL
   setsid bash /tmp/supervisor.sh    < /dev/null > /tmp/sup_stdout.log 2>&1 &
   setsid bash /tmp/token_prober.sh  < /dev/null > /dev/null 2>&1 &
   ```
   Start **one** supervisor only. Duplicates race to start the same marque and
   double-render; check with
   `ps -eo args | grep -c '[s]upervisor.sh'`.
   If `/tmp` was wiped by a rollback, both scripts are committed at
   `pipeline/ingest/token_prober.sh` (and the supervisor is reproducible from
   the commit history — see "supervisor" in the log).

## What is queued

Manifests are ordered UK-common-first (`pipeline/ingest/uk_priority.py`), so
superminis and family cars render before halo cars. Rows are counted post-filter:

| marque | rows | rendered | note |
|---|---|---|---|
| nissan | 415 | 310 | wave walked the manifest; 92 passes audited |
| honda | 258 | 228 | 145 sheets still unaudited |
| toyota | 373 | 158 | 153 sheets still unaudited |
| ford | 373 | 11 | quota-blocked at row 17 |
| renault | 133 | 11 | quota-blocked at row 21 |
| fiat | 114 | 99 | +7 top-up rows unrendered |
| citroen | 87 | 71 | complete |
| landrover | 68 | 50 | complete |
| hyundai | 89 | 0 | never started |
| byd | 46 | 0 | never started |

## The big unfinished job — needs NO Sketchfab quota

**606 sheets are already rendered and never audited** (mercedes 188, toyota 153,
honda 145, peugeot 85, nissan 35). Auditing is pure Supabase work and can run
while Sketchfab is shut.

More urgent: **the tyre ruling only exists as of 2026-08-09 night.** Toyota,
Mercedes, Peugeot and Honda were all audited BEFORE it and are live now — 241
cars. The one pre-rule marque that was rechecked (Fiat) turned up 12 live cars
with body-colour tyres. Two retro-audit agents were started for this; if they
did not finish, restart them. Their outputs are
`pipeline/ingest/retro_tyre_audit.json` and `..._2.json`.

## Open items

- **Render-side inversion, unresolved.** ~2% of sheets render an upright GLB on
  its side or upside down. Marked `fail-rerender`, never scrapped. Needs the
  worker fixed or a post-render check.
- **Render worker hardening is committed but NOT deployed** — no Docker daemon
  in this container, so the image must be rebuilt elsewhere, the template
  repinned, and workers force-recycled. After any repin, re-render one known
  car and LOOK: warm workers keep serving the old image with no error.
- **FreshRaccoon5597's Sketchfab token is unrecoverable** from this machine
  (proven by validating every hex-32 candidate). Regenerate it from the account
  if a fourth rotation slot is wanted.
