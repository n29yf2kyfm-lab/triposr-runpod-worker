# MCP servers

`.mcp.json` at the repo root registers five MCP servers at **project scope**. Claude Code
prompts you to approve project-scoped servers the first time you open the repo; approve
them and they load on every subsequent session here.

| Server | What it does | Needs |
| --- | --- | --- |
| `chrome-devtools` | Drives real Chrome — DOM/network/console inspection, performance traces, screenshots | Node LTS, local Chrome |
| `playwright` | Browser automation over accessibility snapshots (no vision model needed) | Node LTS, Playwright browsers |
| `glyph` | Tree-sitter symbol outlines of the codebase (Go, Java, JS/TS, Python) | `glyph` binary on `PATH` |
| `firecrawl` | Web search + scrape/crawl to markdown, JS rendering and CAPTCHA handling | `FIRECRAWL_API_KEY` |
| `perplexity` | `perplexity_search`, `_ask`, `_research`, `_reason` against the Perplexity API | `PERPLEXITY_API_KEY` |

## Setup

### 1. glyph (the only non-npx server)

`glyph` is a Go binary and must exist on `PATH` before the server will start:

```bash
GOBIN=/usr/local/bin go install github.com/benmyles/glyph@latest
glyph --help   # should print: Usage: glyph [mcp|cli] [options]
```

Any `GOBIN` on your `PATH` works — `$(go env GOPATH)/bin` is the usual alternative. If you
put it somewhere else, change the `command` in `.mcp.json` to the absolute path.

### 2. API keys

`firecrawl` and `perplexity` read their keys from the environment — `.mcp.json` only
references them via `${VAR}`, so no secret is ever committed. Export them from your shell
profile (or whatever secret manager you use) before launching Claude Code:

```bash
export FIRECRAWL_API_KEY=fc-...      # https://firecrawl.dev  → dashboard
export PERPLEXITY_API_KEY=pplx-...   # https://perplexity.ai  → API settings
```

Both servers hit paid APIs on every tool call. If you skip a key, that one server fails to
start and the other four are unaffected.

### 3. Browsers

`chrome-devtools` launches your installed Chrome. In a headless environment append flags in
`.mcp.json`, e.g. `["-y", "chrome-devtools-mcp@latest", "--headless", "--isolated"]`
(`--isolated` uses a throwaway profile instead of your real one).

`playwright` needs browsers installed (`npx playwright install chromium`) unless the
environment already provides them via `PLAYWRIGHT_BROWSERS_PATH`.

## Verifying

```bash
claude mcp list       # shows each server and whether it connected
```

Inside a session, `/mcp` lists the connected servers and their tools.

## Alternative: user scope

To get these in every repo rather than just this one, register them globally instead:

```bash
claude mcp add -s user chrome-devtools -- npx -y chrome-devtools-mcp@latest
claude mcp add -s user playwright      -- npx -y @playwright/mcp@latest
claude mcp add -s user glyph           -- glyph mcp
claude mcp add -s user firecrawl  -e FIRECRAWL_API_KEY="$FIRECRAWL_API_KEY"   -- npx -y firecrawl-mcp
claude mcp add -s user perplexity -e PERPLEXITY_API_KEY="$PERPLEXITY_API_KEY" -- npx -y @perplexity-ai/mcp-server
```
