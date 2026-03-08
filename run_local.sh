#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if [ ! -x ".venv/bin/python3" ]; then
  python3 -m venv .venv
fi

if [ ! -x ".venv/bin/pip" ] || ! .venv/bin/pip --version >/dev/null 2>&1; then
  rm -rf .venv
  python3 -m venv .venv
fi

VENV_PYTHON=".venv/bin/python3"

"$VENV_PYTHON" -m pip install --disable-pip-version-check -r requirements.txt

if [ -f ".env" ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

"$VENV_PYTHON" manage.py migrate
"$VENV_PYTHON" manage.py runserver 127.0.0.1:8000
