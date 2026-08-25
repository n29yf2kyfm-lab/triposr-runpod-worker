---
type: "query"
date: "2026-08-25T21:09:09.973062+00:00"
question: "What does a container rollback take besides the repo checkout?"
contributor: "graphify"
outcome: "useful"
source_nodes: ["session-start.sh", "install_blender.sh"]
---

# Q: What does a container rollback take besides the repo checkout?

## Answer

Rollback #15 (2026-08-25): repo reverted 523 commits, torch/transformers/OpenEXR gone (killed the running seg chain), OPENROUTER_API_KEY dropped from ~/.alam3d_env (again — newest var dies first), ~/.claude skills/plugins gone, Blender /opt gone, scratchpad reverted to Aug-12 state resurrecting 6.5GB of already-purged files. Recovery: git fetch+reset from origin, run .claude/hooks/session-start.sh (reinstalled all five plugins unattended — first live-fire validation), install_blender.sh, re-purge scratchpad. Seg deps now in the hook.

## Outcome

- Signal: useful

## Source Nodes

- session-start.sh
- install_blender.sh