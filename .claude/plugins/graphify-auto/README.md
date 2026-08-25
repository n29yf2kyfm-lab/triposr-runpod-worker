# graphify-auto

Installs [graphify](https://pypi.org/project/graphifyy/) and rebuilds the
repository's code graph at the start of **every** Claude session, so `/graphify`
is ready without anyone remembering to set it up.

## What it does, on every session start

1. `pip install graphifyy` — skipped when the binary is already present. This is
   the line that repairs the install after a container rollback.
2. `graphify install --platform claude` — puts the skill at
   `~/.claude/skills/graphify/SKILL.md` so `/graphify` resolves.
3. `graphify extract "$CLAUDE_PROJECT_DIR" --code-only --no-cluster` — builds
   `graphify-out/graph.json`.

Measured on `triposr-runpod-worker`: **12s cold** (764 code files → 4,306 nodes /
9,109 edges), **2s warm** off graphify's incremental manifest cache.

Runs in async mode, so the session opens immediately and this finishes in the
background. Nothing in the session's critical path depends on the graph existing.

## Zero egress — this is not optional

`--code-only` uses the local tree-sitter AST path and **no LLM backend at all**.
graphify's other modes (`--backend gemini|kimi|claude|openai|deepseek|ollama`)
POST repository source to a third-party vendor. This container holds the Supabase
service key, the RunPod key and the Sketchfab tokens, so an unattended
session-start hook must never take that path. `--no-cluster` is set for the same
reason: clustering ends in an LLM community-naming call that auto-detects
whatever API key happens to be in the environment.

`graphify claude install` is deliberately **not** run. It appends a graphify
section to the repository's `CLAUDE.md` — the owner's project memory — and
installs a `PreToolUse` hook. Neither belongs in an automatic per-session job.

## Two ways it is wired

* **Committed repo hook** (active now, no install step): `.claude/settings.json`
  registers `.claude/hooks/session-start.sh`. A fresh remote session clones this
  repo and the hook fires before the first turn. This is the rollback-proof
  half — origin is the only thing that has survived all fourteen of this
  project's container rollbacks.
* **Plugin package** (this directory): `.claude-plugin/plugin.json` +
  `hooks/hooks.json` pointing at `${CLAUDE_PLUGIN_ROOT}/hooks/session-start.sh`,
  for installing the same behaviour in other repositories.

Both scripts are identical, and the work is idempotent, so a double fire costs
the 2s warm path.

## Log

`graphify-out/session-start.log` (gitignored, inside `graphify-out/`). A run that
produced no graph writes `FAIL_NO_GRAPH` rather than exiting silently.
