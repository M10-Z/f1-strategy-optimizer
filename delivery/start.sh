#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
fi
if [[ ! -f .venv/.f1-ready ]]; then
  .venv/bin/python -m pip install -r requirements-runtime.txt
  .venv/bin/python -m pip install --no-deps wheel/*.whl
  touch .venv/.f1-ready
fi
exec .venv/bin/python start.py "$@"
