---
type: "query"
date: "2026-08-25T21:09:09.888333+00:00"
question: "Why did the terminal-state watcher fire instantly on an old failure line?"
contributor: "graphify"
outcome: "corrected"
correction: "Always use tail -n0 -f for terminal-state watchers on append logs, or grep from a line offset recorded before arming."
source_nodes: ["slice.log"]
---

# Q: Why did the terminal-state watcher fire instantly on an old failure line?

## Answer

tail -f replays the last ~10 lines of the file before following, so a watcher grepping for SLICE_FAILED matched the PREVIOUS run's failure line and exited immediately while the resumed run was healthy (2026-08-25). Same failure class as the pgrep-matches-its-own-wrapper trap.

## Outcome

- Signal: corrected
- Correction: Always use tail -n0 -f for terminal-state watchers on append logs, or grep from a line offset recorded before arming.

## Source Nodes

- slice.log