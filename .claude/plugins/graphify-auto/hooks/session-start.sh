#!/bin/bash
# SessionStart hook — install graphify and build the code graph, every session.
#
# WHY THIS EXISTS: this container is ephemeral and has rolled back 14 times in
# this project's history, wiping ~/.claude/skills and every pip install with it.
# Origin is the only thing that has survived every rollback, so the durable place
# for "run this in every session" is a COMMITTED hook, not a machine-local one.
# A fresh remote session clones this repo, and this fires before the first turn.
#
# ZERO EGRESS BY DESIGN. `graphify extract` is run with --code-only, which uses
# the local tree-sitter AST path and no LLM backend at all. graphify's other
# modes (--backend gemini|kimi|claude|openai|deepseek|ollama) would POST this
# repo's source to a third-party vendor; this container holds the Supabase
# service key, the RunPod key and the Sketchfab tokens, so that must never
# happen unattended. --no-cluster is set for the same reason: clustering ends in
# an LLM community-naming call that auto-detects whatever API key is in the env.
#
# Measured on this repo 2026-08-25: 759 code files -> 4,302 nodes / 9,107 edges
# in 19.9s cold. Subsequent runs hit graphify's incremental manifest cache.
set -uo pipefail

# Async: the session opens immediately and this finishes in the background.
# Nothing in the session's critical path depends on graph.json existing (a
# missing graph just means /graphify says to run an extract), so blocking every
# session start for ~40s to remove a benign race is a bad trade.
echo '{"async": true, "asyncTimeout": 300000}'

ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
LOG="${ROOT}/graphify-out/session-start.log"
mkdir -p "$(dirname "$LOG")"
exec >>"$LOG" 2>&1
echo "=== $(date -u +%FT%TZ) session-start hook ==="

# Idempotent: pip is a no-op when the wheel is already present, and this is the
# line that repairs the install after a container rollback.
if ! command -v graphify >/dev/null 2>&1; then
  echo "graphify absent, installing"
  pip install --quiet --disable-pip-version-check graphifyy || {
    echo "FAIL: pip install graphifyy"; exit 0; }
else
  echo "graphify present: $(command -v graphify)"
fi

# Puts the skill at ~/.claude/skills/graphify/SKILL.md so /graphify resolves.
# Writes ~/.claude/CLAUDE.md (user-level) — it does NOT touch this repo's
# CLAUDE.md, which is the owner's project memory and must not be appended to on
# every session. `graphify claude install` is deliberately NOT run for that
# reason: it edits the repo CLAUDE.md and installs a PreToolUse hook.
graphify install --platform claude || echo "WARN: graphify install --platform claude failed"

# --code-only --no-cluster: local AST only, no API key read, no network.
graphify extract "$ROOT" --code-only --no-cluster || echo "WARN: extract failed"

if [ -s "${ROOT}/graphify-out/graph.json" ]; then
  echo "OK graph.json $(stat -c %s "${ROOT}/graphify-out/graph.json") bytes"
else
  echo "FAIL_NO_GRAPH: graphify-out/graph.json missing or empty"
fi
echo "=== done $(date -u +%FT%TZ) ==="
