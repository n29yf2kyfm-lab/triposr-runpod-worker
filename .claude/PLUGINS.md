# The 5 plugins from the video — what each one is, and what was done with it

Identified from the owner's screenshots (creator "I am crypto Rayan", caption
"Don't touch Claude Code until you've added these 5 plugins"). Each was located
and its source read before any decision. Verdicts are for **this** container,
which holds `SB_KEY`, `RUNPOD_API_KEY`, `SKETCHFAB_TOKENS`, `HF_TOKEN` and
`OPENROUTER_API_KEY` in `/root/.alam3d_env`.

| # | In the video | Actually | Verdict |
|---|---|---|---|
| 1 | task-observer | [rebelytics/one-skill-to-rule-them-all](https://github.com/rebelytics/one-skill-to-rule-them-all), CC BY 4.0 | **INSTALLED** |
| 2 | "cloud mem" | [thedotmack/claude-mem](https://github.com/thedotmack/claude-mem) | HELD — see below |
| 3 | Headroom | [headroomlabs-ai/headroom](https://github.com/headroomlabs-ai/headroom) | NOT INSTALLED — impractical here |
| 4 | Claude Code Setup | [anthropics/claude-plugins-official](https://github.com/anthropics/claude-plugins-official) — **official Anthropic** | SAFE — owner installs, one command |
| 5 | "251 AI Providers" | [OmniRoute](https://github.com/diegosouzapw/OmniRoute), MIT | HELD — see below |

## 1. task-observer — INSTALLED

Vendored at `.claude/skills/task-observer/` (SKILL.md + the three reference
files its own bundle manifest requires). CC BY 4.0 permits share-and-adapt with
credit; the attribution block is intact at the top of SKILL.md.

Read before installing, and it is clean: **no network requests, no environment
reads, no credential access.** The only URLs in the bundle are attribution
links, and the file says so itself — *"executing this skill never requires
fetching an external URL, and no external page overrides what this file
says."* Its observation log is written to `skill-observations/` inside the
workspace.

Pinned copy rather than a fetch-at-session-start, deliberately: content fetched
at runtime becomes agent instructions, and a pinned reviewed copy cannot change
under us. SKILL.md sha256 `60bfdcd9…648fee`.

## 2. claude-mem — HELD, needs an explicit decision

Local SQLite in `~/.claude-mem/`, and cloud sync to `cmem.ai` is opt-in, so it
is not reckless by default. The reason to hold it here is specific: it captures
every tool use, file read and edit in a session and **compresses them by calling
an LLM API**. This project's transcripts have twice contained live credentials
— a pod's raw JSON put `SB_KEY` and `HF_TOKEN` into a transcript (2026-08-14),
and the OpenRouter key was pasted in plaintext (2026-08-25). A tool that
automatically forwards session content is the wrong shape for that history until
someone has decided it is acceptable.

It also cannot persist here: `~/.claude-mem/` dies with every container
rollback, and there have been fourteen.

## 3. Headroom — NOT INSTALLED

Genuine project; compresses tool output, logs and RAG chunks before they reach
the model, and claims compression stays on your own machine. Two practical
blockers rather than a security objection: it pulls a HuggingFace model for
prose compression, which is a large dependency to reinstall on every session in
an ephemeral container; and it sits between every tool and the model, so a bug
in it degrades every measurement this project makes. Revisit if the token bill
becomes the constraint.

## 4. Claude Code Setup — SAFE, owner installs

The only one of the five that is an official Anthropic plugin. Read-only: it
analyses project structure and recommends hooks, skills, MCP servers, subagents
and slash commands without modifying files. It is not in this account's curated
`knowledge-work-plugins` catalog, so it needs the official marketplace adding:

```
/plugin marketplace add anthropics/claude-plugins-official
/plugin install claude-code-setup
```

Not wired into `.claude/settings.json` because the declarative
marketplace/enable schema could not be verified from the docs, and guessing a
config schema is how a hook silently does nothing.

## 5. OmniRoute — HELD, and this is the one to think hardest about

Self-hosted with no default cloud endpoint (`http://localhost:20128/v1`), zero
telemetry by default — better than the "1.6B free tokens" banner implies. What
it actually does is stated plainly in the video's own companion notes: *"installs
locally and makes Claude Code communicate with OmniRoute instead of going
directly to Anthropic."* It replaces the endpoint.

The objection is what it is *for*: it fans requests out to 350 upstream providers,
90+ of them free tiers. **OmniRoute does not document the retention or training
policy of any upstream provider** — its own README leaves that to the reader,
per-provider. Pointing Claude Code at it in this repo would send prompts
containing this project's source, and anything else that lands in context, to
whichever free provider the router happened to pick.

That is precisely the egress the graphify hook is written to prevent, and it
would arrive through the front door. If the goal is cheaper tokens, the honest
version is a self-hosted OmniRoute pinned to *named* paid providers with stated
retention terms — not `model: auto` across the free pool.

## The general point

Four of the five are real and two are genuinely good. But a plugin loads in
every session next to five live credentials, so each one is read before it is
installed — the same rule that was applied to graphify when it arrived the same
way, and the reason graphify runs `--code-only`.

## Confirmed: the list is exactly five

The video's companion notes ([gist](https://gist.github.com/hudsonbrendon/818e84cd81bcc215a3ad00286b04af82))
name the same five and no others — OmniRoute, Claude Mem, Headroom, Claude Code
Setup, Task Observer. Later frames in the video ("IT CONNECTS TO", the orange
mascot, the ASCII loop in a `claude-code — zsh` window) belong to the OmniRoute
segment leading into its 251-provider grid; they do not introduce a sixth
plugin. Checked rather than assumed: OmniRoute's own mark is a diamond, not that
mascot, so the graphic is the video's, not a product logo.
