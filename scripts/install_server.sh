#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/gdaps}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

cd "$APP_DIR"
$PYTHON_BIN -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt

mkdir -p data
if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example. Fill API keys and server values before operation."
fi
