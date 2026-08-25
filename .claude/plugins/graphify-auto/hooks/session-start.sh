#!/bin/bash
# SessionStart hook — install and start the whole toolchain, every session.
#
# WHY THIS EXISTS: this container is ephemeral and has rolled back fourteen
# times in this project's history, wiping ~/.claude, every pip install and every
# npm global with it. Origin is the only thing that has survived all of them, so
# the durable place for "run this in every session" is a COMMITTED hook, not a
# machine-local install. A fresh remote session clones this repo, and this fires
# before the first turn.
#
# WHAT IT INSTALLS (the owner's five, plus graphify):
#   graphify        code knowledge graph            local AST only, zero egress
#   task-observer   vendored skill, .claude/skills  nothing to install
#   claude-mem      session memory                  npx claude-mem install
#   headroom        context compression proxy       pip + headroom init claude
#   omniroute       local multi-provider gateway    npm -g omniroute
#   claude-code-setup  official Anthropic plugin    registered in settings.json
#
# Every step is idempotent and fails OPEN: a step that cannot install logs a
# WARN and the session still starts. Nothing here may ever hard-fail a session.
set -uo pipefail

# Async: the session opens immediately and this finishes in the background.
echo '{"async": true, "asyncTimeout": 600000}'

ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
LOG="${ROOT}/graphify-out/session-start.log"
mkdir -p "$(dirname "$LOG")"
exec >>"$LOG" 2>&1
echo "=== $(date -u +%FT%TZ) session-start hook ==="

have(){ command -v "$1" >/dev/null 2>&1; }
listening(){ curl -fsS -m 3 -o /dev/null "$1" 2>/dev/null; }

# ---------------------------------------------------------------- graphify ---
# ZERO EGRESS BY DESIGN. --code-only uses the local tree-sitter AST path and no
# LLM backend at all. graphify's --backend gemini|kimi|claude|openai|deepseek|
# ollama modes would POST this repo's source to a third-party vendor, and this
# container holds the Supabase service key, the RunPod key and the Sketchfab
# tokens. --no-cluster is set for the same reason: clustering ends in an LLM
# community-naming call that auto-detects whatever API key is in the env.
# `graphify claude install` is deliberately NOT run: it appends to the repo's
# CLAUDE.md (the owner's project memory) and installs a PreToolUse hook.
have graphify || { echo "installing graphifyy"; pip install --quiet --disable-pip-version-check graphifyy || echo "WARN pip graphifyy"; }
graphify install --platform claude >/dev/null 2>&1 || echo "WARN graphify skill install"
graphify extract "$ROOT" --code-only --no-cluster || echo "WARN graphify extract"
[ -s "${ROOT}/graphify-out/graph.json" ] && echo "OK graph.json $(stat -c %s "${ROOT}/graphify-out/graph.json") bytes" || echo "FAIL_NO_GRAPH"
# graphify-out/memory/ is COMMITTED session knowledge (survives rollbacks via
# origin). reflect is deterministic and local -- regenerate LESSONS.md against
# the fresh graph so stale nodes drop out.
if [ -d "${ROOT}/graphify-out/memory" ]; then
  (cd "$ROOT" && graphify reflect --graph graphify-out/graph.json >/dev/null 2>&1) \
    && echo "OK reflect $(ls "${ROOT}/graphify-out/memory" | wc -l) memories" || echo "WARN reflect failed"
fi

# -------------------------------------------------------------- claude-mem ---
# Local SQLite in ~/.claude-mem. Installs its own plugin + hooks into
# ~/.claude; both die with a rollback, which is why this reinstalls them.
if [ ! -d "$HOME/.claude-mem" ]; then
  echo "installing claude-mem"
  npx --yes claude-mem install >/dev/null 2>&1 || echo "WARN claude-mem install"
fi
# The worker is what actually records observations; autostart is skipped by the
# installer, so start it here and leave it if it is already up.
npx --yes claude-mem start >/dev/null 2>&1 || echo "WARN claude-mem start"
[ -d "$HOME/.claude-mem" ] && echo "OK claude-mem" || echo "WARN claude-mem absent"

# ---------------------------------------------------------------- headroom ---
# [proxy] not [all]: the full extra pulls a HuggingFace prose model, which is a
# large download to repeat on every cold session. kompress then reports
# "degraded (optional)" and compression falls back to heuristics — that is the
# accepted trade here, not a fault. Set HEADROOM_FULL=1 to take the model.
# --ignore-installed PyJWT: this image's PyJWT is a Debian package with no
# RECORD file, so pip cannot uninstall it and the whole install aborts.
if ! have headroom; then
  echo "installing headroom"
  EXTRA="proxy"; [ "${HEADROOM_FULL:-0}" = "1" ] && EXTRA="all"
  pip install --quiet --ignore-installed PyJWT "headroom-ai[${EXTRA}]" || echo "WARN headroom install"
fi
# Writes ANTHROPIC_BASE_URL=http://127.0.0.1:8787 into the PROJECT's
# .claude/settings.local.json, and installs its own SessionStart + PreToolUse
# "ensure" hooks that keep the proxy alive. That file is gitignored on purpose:
# committing it would point every fresh remote session at a proxy that is not
# running there, and the session could not reach the API at all.
have headroom && { headroom init claude >/dev/null 2>&1 || echo "WARN headroom init"; }
if have headroom && ! listening http://127.0.0.1:8787/livez; then
  nohup headroom proxy --port 8787 >/tmp/headroom_proxy.log 2>&1 &
  sleep 6
fi
listening http://127.0.0.1:8787/livez && echo "OK headroom proxy 8787" || echo "WARN headroom proxy down"

# --------------------------------------------------------------- omniroute ---
# Local gateway on :20128. Installed and running, but NOT made Claude Code's
# endpoint: it routes to 350 upstream providers whose retention and training
# terms it does not document, and ANTHROPIC_BASE_URL already belongs to
# headroom. Connect providers in the dashboard and pin named ones before
# sending anything through it.
if ! have omniroute; then
  echo "installing omniroute"
  npm install -g omniroute >/dev/null 2>&1 || echo "WARN omniroute install"
fi
if have omniroute && ! listening http://127.0.0.1:20128/; then
  nohup omniroute >/tmp/omniroute.log 2>&1 &
  sleep 12
fi
listening http://127.0.0.1:20128/ && echo "OK omniroute 20128" || echo "WARN omniroute down"

# ----------------------------------------------- official Anthropic plugin ---
# claude-code-setup is read-only: it analyses the project and recommends hooks,
# skills, MCP servers and subagents without modifying files. Registered
# declaratively rather than through /plugin, which a hook cannot run. The schema
# below is not guessed — it is the shape claude-mem and headroom both wrote.
python3 - <<'PY' 2>/dev/null || echo "WARN settings.json registration"
import json, os
p = os.path.expanduser("~/.claude/settings.json")
os.makedirs(os.path.dirname(p), exist_ok=True)
try:
    d = json.load(open(p))
except Exception:
    d = {}
d.setdefault("extraKnownMarketplaces", {})["claude-plugins-official"] = {
    "source": {"source": "github", "repo": "anthropics/claude-plugins-official"}}
d.setdefault("enabledPlugins", {})["claude-code-setup@claude-plugins-official"] = True
json.dump(d, open(p, "w"), indent=2)
print("OK claude-code-setup registered")
PY

# ----------------------------------------------------------- task-observer ---
# Vendored at .claude/skills/task-observer (pinned, CC BY 4.0). Nothing to
# install — this only reports whether the bundle its own manifest requires is
# complete, because a missing reference file degrades it silently.
TO="${ROOT}/.claude/skills/task-observer"
n=$(ls "$TO"/references/*.md 2>/dev/null | wc -l)
[ -s "$TO/SKILL.md" ] && [ "$n" -eq 3 ] && echo "OK task-observer (SKILL.md + $n refs)" \
  || echo "WARN task-observer bundle incomplete (SKILL.md + $n/3 refs)"

echo "=== done $(date -u +%FT%TZ) ==="
