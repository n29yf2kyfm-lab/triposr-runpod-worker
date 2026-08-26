# screenshot-to-code

Setup helper for [`abi/screenshot-to-code`](https://github.com/abi/screenshot-to-code) (MIT) —
converts screenshots, mockups, Figma designs and screen recordings into working code.

It is **not** part of the TripoSR worker and shares no code with it; this directory just
holds a reproducible way to stand the tool up. The upstream app is cloned into `vendor/`
(gitignored) rather than vendored, so it stays easy to update and doesn't bloat this repo.

## Quick start

```bash
export GEMINI_API_KEY=...        # any one of GEMINI / OPENAI / ANTHROPIC
./tools/screenshot-to-code/install.sh
```

Auto-selects Docker when the daemon is reachable, otherwise the local
poetry + pnpm path. Force either with `--docker` / `--local`.

Then open <http://localhost:5173>.

## API keys

At least one model provider key is required. The script reads them from the environment
and writes only into the app's own `.env` (mode `600`) — nothing lands in this repo.

| Variable | Required | Unlocks |
| --- | --- | --- |
| `GEMINI_API_KEY` | one of the three — recommended | Gemini code-gen; extracts real logos/images from the screenshot; required for video mode |
| `OPENAI_API_KEY` | one of the three | GPT code-gen variants |
| `ANTHROPIC_API_KEY` | one of the three | Claude code-gen variants |
| `REPLICATE_API_KEY` | optional | Image generation, editing, background removal |

Keys can also be set at runtime via the gear icon in the app. With more keys present the
app picks a stronger mix of models per variant.

## The two modes

**Docker** (`--docker`) — `docker compose up -d --build`. Simplest, but no hot reload, so
it's for using the tool rather than hacking on it. Requires Docker Compose **v2**
(`docker compose`, not the older `docker-compose` binary).

**Local** (`--local`) — installs backend deps with poetry and frontend deps with pnpm, then
prints the two commands to run. Backend needs Python ≥ 3.10. Supports hot reload.

The local path also installs Chromium for the optional *screenshot preview* tool, which
lets the agent render its own generated page and visually check its work. If that install
fails the script warns and continues — the app just skips the tool. On Linux it may need
system libraries: `poetry run playwright install --with-deps chromium`.

## Ports

| Service | Port |
| --- | --- |
| frontend (Vite) | 5173 |
| backend (FastAPI/uvicorn) | 7001 |

To move the backend, set `VITE_WS_BACKEND_URL` and `VITE_HTTP_BACKEND_URL` in
`frontend/.env.local`.

## Verified

The local path was run end-to-end on Linux / Node 22 / Python 3.11: `poetry install` and
`pnpm install --frozen-lockfile` both succeed, uvicorn serves `HTTP 200` on :7001 and Vite
serves `HTTP 200` on :5173. The Docker path follows upstream's documented compose setup but
was not executed here (no Docker daemon available in that environment).

## Updating

Re-running the script fast-forwards the existing checkout. To start clean:

```bash
rm -rf vendor/screenshot-to-code && ./tools/screenshot-to-code/install.sh
```
