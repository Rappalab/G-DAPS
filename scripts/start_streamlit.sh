#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"

export PYTHONPATH="$APP_DIR"
set -a
[ -f .env ] && source .env
set +a

STREAMLIT_PORT="${STREAMLIT_PORT:-8501}"
exec "$APP_DIR/.venv/bin/streamlit" run app/streamlit_app.py --server.port "$STREAMLIT_PORT" --server.address 0.0.0.0
