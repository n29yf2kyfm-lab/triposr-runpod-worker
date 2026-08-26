---
type: "query"
date: "2026-08-26T06:42:04.183199+00:00"
question: "What are the owner's standing rules about local disk, rewind and restore?"
contributor: "graphify"
outcome: "useful"
source_nodes: ["CLAUDE.md", "session-start.sh"]
---

# Q: What are the owner's standing rules about local disk, rewind and restore?

## Answer

OWNER STANDING ORDER 2026-08-26, verbatim: 'Never /rewind. Never restore a snapshot. Never git reset --hard unless I say restore. If disk is over 70%, prune scratchpad and /tmp first. Upload artefacts to the bucket, then delete the local copy. Push every commit. Do not keep GLBs, sheets, or Blender extracts on this box. Keep that box empty. Origin and the bucket survive. Local never does.' Enforced: fileCheckpointingEnabled=false in ~/.claude/settings.json so no snapshots exist to rewind to (that file does NOT survive a rollback — re-set it after one, alongside ~/.alam3d_env). git reset --hard is the correct repair for a rolled-back checkout and local-only:0 proves nothing is lost, but it needs the owner to say 'restore' first. Prune at 70%, not at 93%. Upload-then-delete is BOTH halves: keeping fills the disk, deleting without uploading is how polished_f34r.glb was destroyed — list the bucket prefix to confirm the object before rm.

## Outcome

- Signal: useful

## Source Nodes

- CLAUDE.md
- session-start.sh