# Five design skills from the "Claude Free AI Web Design Tools" TikTok (2026-09-23)

Installed at the owner's request. Each was cloned and read before installing,
because a skill loads into every session alongside this container's keys.

| Tool in the video | Source | Licence | Installed as |
|---|---|---|---|
| Taste Skill | github.com/Leonxlnx/taste-skill (c184364) | MIT | `.claude/skills/taste-skill` (skill name `design-taste-frontend`) |
| Impeccable | github.com/pbakaus/impeccable (e0881d2, v4.3.1) | Apache-2.0 | `.claude/skills/impeccable` |
| Playwright CLI | github.com/microsoft/playwright-cli, npm `@playwright/cli` 0.1.21 | Apache-2.0 | `.claude/skills/playwright-cli` + `.playwright/cli.config.json` |
| Awesome Design | github.com/VoltAgent/awesome-design-md (f696123) | MIT | `.claude/skills/awesome-design` (74 DESIGN.md files, wrapper SKILL.md written here) |
| Image to Three.js | github.com/img2threejs/img2threejs (6e60b5e, v2.0.0) | Apache-2.0 | `.claude/skills/img2threejs` |

## What was deliberately left out

* **Impeccable's plugin hooks.** The Claude Code *plugin* adds PostToolUse and
  Stop hooks that run its engine binary on EVERY Edit/Write in the repo. Only the
  skill is installed, so it runs when invoked, not on every edit to pipeline code.
  On first use its launcher downloads the engine binary from the project's GitHub
  releases and refuses to run it unless the .sha256 sidecar matches.
* **img2threejs `integrations/vision`** pins `transformers==4.57.6`, which
  SkillSpector flagged with 9 CVEs including remote code execution. It is an
  optional add-on and is not installed. `forge/tests` and CI files are left out
  too. The core is Python standard library only, and it passes an allowlisted
  environment to its own subprocesses.
* **Taste Skill's 12 variant skills** (brutalist, soft, stitch, and others). Only
  the main skill is installed. The rest are in the upstream repo if wanted.

## SkillSpector (static, --no-llm)

Scores: taste-skill CAUTION; impeccable, playwright-cli and img2threejs
DO_NOT_INSTALL. **Every HIGH finding in the installed files was opened at its
line and is a false positive:** an HTML comment template in impeccable's
live.md, "never commit auth-state files" in playwright's storage-state.md, a
reference list, test commands in img2threejs's SKILL.md, and ordinary design
guidance. This is the same noise pattern CLAUDE.md records for SkillSpector.
The two CRITICAL findings are the excluded vision dependency above.
