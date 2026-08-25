---
type: "query"
date: "2026-08-25T19:29:04.110208+00:00"
question: "How to recover the OpenRouter key after a rollback?"
contributor: "graphify"
outcome: "useful"
source_nodes: ["alam3d_env"]
---

# Q: How to recover the OpenRouter key after a rollback?

## Answer

Reproduced again 2026-08-25 (the newest env var dies first): grep -rhoE 'sk-or-v1-[0-9a-f]{64}' /root/.claude/projects/-home-user-triposr-runpod-worker/, validate each against GET https://openrouter.ai/api/v1/key expecting 200, append the NAME=value to /root/.alam3d_env, chmod 600. Worked first try.

## Outcome

- Signal: useful

## Source Nodes

- alam3d_env