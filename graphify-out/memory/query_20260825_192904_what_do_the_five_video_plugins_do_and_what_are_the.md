---
type: "query"
date: "2026-08-25T19:29:04.034001+00:00"
question: "What do the five video plugins do and what are the wiring traps?"
contributor: "graphify"
outcome: "useful"
source_nodes: ["session-start.sh", "PLUGINS.md"]
---

# Q: What do the five video plugins do and what are the wiring traps?

## Answer

All five installed 2026-08-25 (owner decision after risk review), started by committed .claude/hooks/session-start.sh: graphify (code-only, zero egress), task-observer (vendored skill), claude-mem (worker :37700), headroom (proxy :8787), omniroute (gateway :20128, NOT the endpoint — undocumented upstream retention). TRAPS: headroom init writes ANTHROPIC_BASE_URL into .claude/settings.local.json (must stay gitignored or fresh remote sessions cannot reach the API); pip headroom-ai needs --ignore-installed PyJWT (Debian package, no RECORD). In cloud sessions the platform sets the base URL, so both proxies see zero traffic — they only apply on desktop.

## Outcome

- Signal: useful

## Source Nodes

- session-start.sh
- PLUGINS.md