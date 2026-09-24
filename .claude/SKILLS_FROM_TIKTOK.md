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

# Second TikTok: "How to make your vibe coded landing page look fire" (2026-09-24)

Four tools in the video. Two were already installed from the first one:
No. 4 "world class design prompting" is **Impeccable**, and "steal any famous
design system with getdesign.md" is **awesome-design** (VoltAgent/awesome-design-md,
whose site is getdesign.md). Upstream is still at f696123 with 74 DESIGN.md files,
the same commit installed above, so there was nothing to update. The "300+"
catalogue in the video is the getdesign.md website, not the repo.

| Tool in the video | Source | Licence | Installed as |
|---|---|---|---|
| 21st.dev ("integrate high quality design assets") | github.com/21st-dev/skill (15c7436), CLI `@21st-dev/cli` 1.17.1 | Apache-2.0 | `.claude/skills/21st-{cli-use,ai,registry,design-sync,ui-build,ui-explore,ui-review}` |
| No. 3 "insane web animations with WebGPU" | github.com/dgreenheck/webgpu-claude-skill (af2319b) | MIT | `.claude/skills/webgpu-threejs-tsl` |

## What the 21st.dev skills need, measured rather than assumed

* **An account.** Without one, `21st search` returns "Not signed in. Run
  `21st login` or set TWENTYFIRST_TOKEN." Only `21st logo` works keyless. A free
  key comes from 21st.dev/settings/api-keys and belongs in `/root/.alam3d_env` as
  `API_KEY_21ST`, never in the repo. Code retrieval has a free daily quota; hosted
  21st AI generation is paid and off on the free plan.
* **Telemetry needs a token.** The CLI posts command names and review summaries
  to `21st.dev/api/v1/cli/events`, but `trackDirectCliCommand` and
  `trackCliSummary` both return at `if (!token) return`. Read in the 1.17.1 source.
* **`21st review --help` ignores `--help` and RUNS a review** of the current
  directory. It is a local lint and writes nothing without `--fix`, but do not use
  `--help` on that subcommand.
* **`--context auto` sends the project's design context** (`.21st/design.json`)
  with a search or a generation, and `21st init --design-context` writes a `.21st/`
  folder into the repo. The `21st-ui-*` skills do both. Keep them to UI work.
* **`21st-registry` and `21st-design-sync` PUBLISH to the public 21st.dev site.**
  They are installed because they only trigger on an explicit "publish" request,
  and publishing is outward-facing, so it is confirmed with the owner first.
* **Overlap:** the `21st-ui-*` skills trigger on the same wording as Impeccable
  ("build this UI", "review this page"). When both fit, name the one you want.

## The WebGPU skill

Documentation and examples only: no network, environment or process access.
It targets `three/webgpu` + TSL. The simulator's vendored three.js r169 ships only
the WebGL `three.module.js` build, so using it there means vendoring the WebGPU build.

## SkillSpector (static, --no-llm)

21st skills 25/MEDIUM CAUTION, webgpu-threejs-tsl 0/LOW SAFE. Neither had any
HIGH or CRITICAL finding.

## Taste Skill variants added (2026-09-24, owner request)

Upstream Leonxlnx/taste-skill is still at c184364, and the installed `taste-skill`
is byte-identical to its v2 (experimental), the version on the site in the video.
Two of the variants left out first time were added from the same commit (MIT):

* `.claude/skills/redesign-skill` (name `redesign-existing-projects`) is an
  audit-first upgrade of an existing site that keeps function intact. It suggests
  picsum.photos placeholder images when real assets are missing. Do not ship those
  in the trainer: it makes no off-origin requests, by design.
* `.claude/skills/image-to-code-skill` (name `image-to-code`) builds a page to
  match a design image. It is written for Codex and tells the agent to GENERATE
  the design image first. Here that means a paid image tool (for example
  Higgsfield), so ask before spending credits.

SkillSpector (static): redesign-skill 0/CAUTION, image-to-code-skill 0/SAFE, with
no HIGH or CRITICAL findings.
