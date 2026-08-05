#!/usr/bin/env bash
# Start the API (:8000) and the web app (:5173) together for local dev.
set -euo pipefail
cd "$(dirname "$0")"

# --- API ---
cd api
if [ ! -d .venv ]; then
  python3 -m venv .venv
  ./.venv/bin/pip install -q -r requirements.txt
fi
./.venv/bin/uvicorn app.main:app --port 8000 &
API_PID=$!
cd ..

# --- Web ---
cd web
[ -d node_modules ] || npm install
npm run dev &
WEB_PID=$!
cd ..

echo ""
echo "  SnapList running:"
echo "    web  ->  http://localhost:5173"
echo "    api  ->  http://localhost:8000/api/health"
echo "  Ctrl-C to stop."
trap "kill $API_PID $WEB_PID 2>/dev/null || true" EXIT
wait
