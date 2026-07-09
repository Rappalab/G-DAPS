#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_DIR"

export PYTHONPATH="$APP_DIR"
set -a
[ -f .env ] && source .env
set +a

mkdir -p "${GDAPS_DATA_DIR:-$APP_DIR/data}"
FLASK_PORT="${FLASK_PORT:-5000}"

exec "$APP_DIR/.venv/bin/gunicorn" -w 2 -b "0.0.0.0:${FLASK_PORT}" app.kml_engine:app
