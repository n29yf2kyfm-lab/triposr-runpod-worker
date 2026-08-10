#!/bin/bash
# Rotating Sketchfab token prober.
#
# The waves already rotate tokens per retry (fetch_glb calls next(tok) on every
# attempt, verified A->B->C->A). What was missing is a way OUT of a bench: a
# marque that circuit-breaks is parked for a fixed COOLDOWN, which is a guess.
# Sketchfab sends no Retry-After and no X-RateLimit-* headers, so the reset time
# is not discoverable -- the only way to know is to ask.
#
# This asks cheaply: one download probe per token per cycle (3 requests / 5 min),
# rotating which token goes first so no single account is always the canary. The
# moment ANY token returns non-429, every BENCH_UNTIL is cleared and the
# supervisor resumes on its next 120s tick. That turns a blind 40-minute wait
# into "resume within ~5 minutes of the window actually draining".
set -a; . /root/.alam3d_env; set +a
cd /home/user/triposr-runpod-worker
LOG=/tmp/token_prober.log
INTERVAL=300
echo "$(date +%H:%M:%S) prober up (every ${INTERVAL}s, rotating start token)" >> $LOG
cycle=0
while true; do
  open=$(python3 - "$cycle" <<'PY'
import os, sys, json, glob, urllib.request, urllib.error
start=int(sys.argv[1])
toks=[t.strip() for t in os.environ.get("SKETCHFAB_TOKENS","").split(",") if t.strip()]
if not toks:
    print("NONE"); raise SystemExit
# pick a real uid from whichever manifest is around
uid=None
for p in sorted(glob.glob("/tmp/*/manifest.filtered.json")):
    try:
        rows=json.load(open(p))
        if rows: uid=rows[0]["uid"]; break
    except Exception: pass
if not uid:
    print("NONE"); raise SystemExit
# rotate which account is probed first each cycle
order=[toks[(start+i) % len(toks)] for i in range(len(toks))]
for i,t in enumerate(order):
    rq=urllib.request.Request(f"https://api.sketchfab.com/v3/models/{uid}/download",
        headers={"Authorization": f"Token {t}", "User-Agent":"Mozilla/5.0"})
    try:
        urllib.request.urlopen(rq, timeout=25)
        print(f"OPEN:{(start+i) % len(toks) + 1}"); raise SystemExit
    except urllib.error.HTTPError as e:
        if e.code not in (429, 403):
            print(f"OPEN:{(start+i) % len(toks) + 1}"); raise SystemExit
    except Exception:
        pass
print("THROTTLED")
PY
)
  if [[ "$open" == OPEN:* ]]; then
    echo "$(date +%H:%M:%S) QUOTA OPEN on token ${open#OPEN:} -- clearing all benches" >> $LOG
    rm -f /tmp/*/BENCH_UNTIL
    # keep probing: the window can close again, and the supervisor re-benches
  else
    echo "$(date +%H:%M:%S) still throttled on all tokens (cycle $cycle)" >> $LOG
  fi
  cycle=$(( (cycle + 1) % 3 ))
  sleep $INTERVAL
done
