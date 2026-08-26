#!/usr/bin/env bash
#
# Set up abi/screenshot-to-code — a React/Vite + FastAPI app that turns
# screenshots, mockups and screen recordings into working code.
#
#   ./tools/screenshot-to-code/install.sh            # auto: Docker if available, else local
#   ./tools/screenshot-to-code/install.sh --local    # force poetry + pnpm
#   ./tools/screenshot-to-code/install.sh --docker   # force docker compose
#
# The upstream project is cloned rather than vendored, into vendor/ (gitignored).
# Override with: STC_DIR=/some/path ./tools/screenshot-to-code/install.sh

set -euo pipefail

REPO_URL="https://github.com/abi/screenshot-to-code.git"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
STC_DIR="${STC_DIR:-$ROOT/vendor/screenshot-to-code}"
MODE="auto"

for arg in "$@"; do
  case "$arg" in
    --local)  MODE="local" ;;
    --docker) MODE="docker" ;;
    -h|--help) sed -n '2,11p' "${BASH_SOURCE[0]}" | sed 's/^# \?//'; exit 0 ;;
    *) echo "unknown option: $arg (try --help)" >&2; exit 2 ;;
  esac
done

info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mwarn:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

have() { command -v "$1" >/dev/null 2>&1; }

# --- API keys -----------------------------------------------------------------
# At least one of OpenAI / Anthropic / Gemini is required. Gemini is what powers
# asset extraction and video mode; Replicate powers image editing. Keys are read
# from the environment and never written anywhere but the app's own .env.

collect_keys() {
  KEYS=()
  for k in OPENAI_API_KEY ANTHROPIC_API_KEY GEMINI_API_KEY REPLICATE_API_KEY; do
    if [ -n "${!k:-}" ]; then KEYS+=("$k=${!k}"); fi
  done

  local have_model=0
  for entry in "${KEYS[@]:-}"; do
    case "$entry" in OPENAI_API_KEY=*|ANTHROPIC_API_KEY=*|GEMINI_API_KEY=*) have_model=1 ;; esac
  done

  if [ "$have_model" -eq 0 ]; then
    warn "No model provider key found in the environment."
    warn "Export at least one of OPENAI_API_KEY, ANTHROPIC_API_KEY or GEMINI_API_KEY,"
    warn "or add it later via the gear icon in the running app."
  fi
}

write_env() {
  local target="$1"
  : > "$target"
  for entry in "${KEYS[@]:-}"; do printf '%s\n' "$entry" >> "$target"; done
  chmod 600 "$target"
  info "Wrote ${#KEYS[@]} key(s) to ${target/#$ROOT\//}"
}

# --- clone --------------------------------------------------------------------

clone_or_update() {
  if [ -d "$STC_DIR/.git" ]; then
    info "Updating existing checkout at $STC_DIR"
    git -C "$STC_DIR" pull --ff-only
  else
    info "Cloning $REPO_URL -> $STC_DIR"
    mkdir -p "$(dirname "$STC_DIR")"
    git clone --depth 1 "$REPO_URL" "$STC_DIR"
  fi
}

# --- install paths ------------------------------------------------------------

install_docker() {
  have docker || die "docker not found. Install Docker, or re-run with --local."
  docker compose version >/dev/null 2>&1 \
    || die "'docker compose' (v2) not available. Update Docker, or re-run with --local."
  docker info >/dev/null 2>&1 \
    || die "The Docker daemon isn't running. Start Docker Desktop / dockerd and retry."

  write_env "$STC_DIR/.env"

  info "Building and starting containers (first build takes a few minutes)"
  ( cd "$STC_DIR" && docker compose up -d --build )

  cat <<EOF

  Running at http://localhost:5173  (backend on :7001)

  Logs:  cd ${STC_DIR/#$ROOT\//} && docker compose logs -f
  Stop:  cd ${STC_DIR/#$ROOT\//} && docker compose down

  Note: this mode does not hot-reload on file changes. Use --local to develop.
EOF
}

install_local() {
  have poetry || die "poetry not found. Run: pip install --upgrade poetry"
  have pnpm   || die "pnpm not found. Run: npm install -g pnpm"

  info "Installing backend dependencies (poetry)"
  ( cd "$STC_DIR/backend" && poetry install --no-interaction )

  write_env "$STC_DIR/backend/.env"

  # Optional: powers the "screenshot preview" tool, where the agent renders its
  # own output in a headless browser to check its work. The app runs fine
  # without it and simply skips the tool.
  info "Installing Chromium for the screenshot preview tool (optional)"
  if ! ( cd "$STC_DIR/backend" && poetry run playwright install chromium ); then
    warn "Chromium install failed — screenshot preview will be unavailable."
    warn "On Linux this usually needs system libs: poetry run playwright install --with-deps chromium"
  fi

  info "Installing frontend dependencies (pnpm)"
  ( cd "$STC_DIR/frontend" && pnpm install --frozen-lockfile )

  cat <<EOF

  Setup complete. Start the two servers in separate terminals:

    cd ${STC_DIR/#$ROOT\//}/backend  && poetry run uvicorn main:app --reload --port 7001
    cd ${STC_DIR/#$ROOT\//}/frontend && pnpm dev

  Then open http://localhost:5173

  To run the backend on another port, set VITE_WS_BACKEND_URL in frontend/.env.local
EOF
}

# --- main ---------------------------------------------------------------------

have git || die "git is required."
collect_keys
clone_or_update

if [ "$MODE" = "auto" ]; then
  if have docker && docker compose version >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    MODE="docker"
  else
    MODE="local"
  fi
  info "Auto-selected $MODE mode"
fi

case "$MODE" in
  docker) install_docker ;;
  local)  install_local ;;
esac
