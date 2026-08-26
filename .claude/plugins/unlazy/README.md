# unlazy (vendored plugin)

Local plugin wrapper around **Leonxlnx/unlazy** (MIT, 2.6k stars). Upstream is a
SKILL repo — it ships no `.claude-plugin/plugin.json`, no marketplace entry and
its README never mentions plugins — so this manifest is ours, following the
`graphify-auto` pattern already in this repo.

## What it is
Acceptance gates written *before* work starts, Depth Tree decomposition, and a
Stop hook that blocks a done-report while gates are unmet. v1 asked the model to
work harder; v2 makes half-done structurally visible.

## Why vendored rather than `npx skills add`
The installer CLI is third-party code that would execute on a box holding
SB_KEY, RUNPOD_API_KEY, SKETCHFAB_TOKENS, HF_TOKEN and OPENROUTER_API_KEY. The
repo was cloned and audited first, so copying it is strictly less exposure.

## Audit (2026-08-26, before first run)
* **Zero outbound network** anywhere in scripts/agents/templates.
* **No credential reads** — only `PATH`, `PATHEXT` and its own `UNLAZY_*`.
* Stop hook **fails open** on every error path, carries a `MAX_BLOCKS=6`
  release valve, tracks resolved gate state rather than raw bytes, and is
  **silent when no gate files exist**.
* Upstream suite: **32/32 pass** on this container.

## Verified from the plugin path
* no gate files -> silent, rc=0 (an ordinary turn is never blocked)
* malformed hook input -> fails open, rc=0 (cannot trap a session)

## The one thing to know before enabling
The Stop hook can refuse a turn-end while gates are unmet. The owner halts work
verbally ("Stop", "Stand down"), so that is in tension with owner authority even
with the release valve. It only ever engages once a gate ledger exists, i.e.
after `/unlazy` has been invoked for a task — an ordinary turn is untouched.
Disable by removing `unlazy` from `enabledPlugins`.
