#!/usr/bin/env bash
# TencentDB Agent Memory — reproducible local install for THIS container.
#
# Owner asked for the full install including the ANTHROPIC_BASE_URL reroute
# (asked and confirmed 2026-08-26). Committed because a machine-local install
# does NOT survive a container rollback and this one took several non-obvious
# steps to get right; origin does survive. Re-run after any rollback.
#
# WHAT THIS IS. Three services upstream; we run two, from SOURCE, because this
# container has NO DOCKER and the documented ./start-all.sh is a docker stack:
#   MemoryCore  :8420  local SQLite memory (L0 raw -> L1 facts -> L2 scenes -> L3 profile)
#   MemoryProxy :8096  sits between an agent and api.anthropic.com, injecting memory
# MemoryHub/MemoryPanel are not deployed (team features, need the docker stack).
#
# FIVE THINGS THAT COST TIME, so nobody re-pays them:
#  1. npm install FAILS on MemoryCore with "Cannot read properties of null
#     (reading 'edgesOut')" -- it is a pnpm-workspace package. Use pnpm.
#  2. `pnpm run build` exits 1 on the LAST sub-step (build:seed-v2 references a
#     scripts/seed-v2/tsconfig.json that does not exist on this branch). That is
#     an UPSTREAM bug on feat/server_team; dist/ is built fine before it. Ignore.
#  3. upstream.url MUST END IN /v1. joinUrl() appends only "/messages", so
#     "https://api.anthropic.com" becomes ".../messages" and every request 404s
#     with an empty body -- which looks like a network fault and is not.
#  4. injection.enabled DEFAULTS TO FALSE. Without it the proxy forwards traffic
#     and injects nothing: a no-op that just adds a hop.
#  5. `kill <npm pid>` leaves the real `node --import tsx/esm src/index.ts` child
#     holding :8096, and the next start dies EADDRINUSE. Kill the CHILD, by PID.
#     (Never pkill -f here -- it has killed this session's own shell before.)
#
# SECURITY NOTES, established by reading the source before installing:
#  * No preinstall/postinstall scripts -- npm/pnpm install executes nothing.
#  * OTel telemetry is DEFAULT-OFF (TDAI_OTEL_ENABLED must equal "true") and
#    defaults to localhost:4317. The one Tencent host in the tree
#    (trace.zhiyan.tencent-cloud.net) is inside a YAML doc-comment example.
#  * creditReport defaults to http://gateway.example.com:8000/... -- a
#    PLACEHOLDER that does not resolve, hence the "creditReport FAIL" line at
#    startup. Nothing is transmitted. Do NOT point it at a real host without
#    deciding usage data may leave this box.
#  * upstream.apiKey is DELIBERATELY EMPTY: non-empty REPLACES the client's
#    Authorization header, empty PASSES IT THROUGH. Passthrough means the proxy
#    never holds an Anthropic credential.
#  * Both services bind 127.0.0.1 only. The upstream example ships 0.0.0.0.
set -euo pipefail
SRC="${TDAM_SRC:-/tmp/tdam_src}"
REPO="$(cd "$(dirname "$0")/../.." && pwd)"

[ -n "${OPENROUTER_API_KEY:-}" ] || { echo "set -a; . /root/.alam3d_env; set +a  first"; exit 1; }

if [ ! -d "$SRC" ]; then
  git clone --depth 1 --branch feat/server_team \
    https://github.com/TencentCloud/TencentDB-Agent-Memory.git "$SRC"
fi

cd "$SRC/MemoryCore"
[ -d node_modules ] || pnpm install --ignore-scripts
pnpm run build || echo "build:seed-v2 failure expected (upstream bug) — dist/ is built"

cd "$SRC/MemoryProxy"
[ -d node_modules ] || npm install --no-audit --no-fund
cp -f "$REPO/pipeline/memory/proxy.config.yaml" config.yaml

# --- start MemoryCore (LLM creds by env NAME only; never write the value) ---
cd "$SRC/MemoryCore"
TDAI_GATEWAY_CONFIG="$PWD/tdai-gateway.standalone.yaml" \
TDAI_LLM_API_KEY="$OPENROUTER_API_KEY" \
TDAI_LLM_BASE_URL="https://openrouter.ai/api/v1" \
TDAI_LLM_MODEL="z-ai/glm-5.3-flash" \
  nohup node --import tsx src/gateway/server.ts > /tmp/tdam_core.log 2>&1 &
sleep 20
curl -fsS http://127.0.0.1:8420/health >/dev/null && echo "MemoryCore :8420 healthy"

# --- start MemoryProxy ---
cd "$SRC/MemoryProxy"
nohup npm start > /tmp/tdam_proxy.log 2>&1 &
sleep 20
grep -aq "server.listening" /tmp/tdam_proxy.log && echo "MemoryProxy :8096 listening"

# --- PROVE the hop, do not assume it. A bogus key must come back as
#     Anthropic's own 401 body; a 404 with an empty body means trap #3. ---
code=$(curl -s -o /tmp/tdam_probe.json -w "%{http_code}" --max-time 45 \
  -X POST "http://127.0.0.1:8096/claude-code/default/v1/messages" \
  -H "content-type: application/json" -H "x-api-key: sk-ant-deliberately-invalid-probe" \
  -H "anthropic-version: 2023-06-01" \
  -d '{"model":"claude-sonnet-5","max_tokens":16,"messages":[{"role":"user","content":"ping"}]}')
if [ "$code" = "401" ] && grep -q authentication_error /tmp/tdam_probe.json; then
  echo "FORWARDING PROVEN: proxy -> api.anthropic.com returned Anthropic's own 401"
else
  echo "FORWARDING NOT PROVEN (http=$code) — check trap #3 before using the reroute"; exit 1
fi

cat <<'EOF'

To route a NEW claude CLI invocation through the memory proxy:
  export ANTHROPIC_BASE_URL=http://127.0.0.1:8096/claude-code/default
This affects processes started AFTER it is set. It cannot reroute an
already-running managed session.
EOF
