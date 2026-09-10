#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
"$PYTHON_BIN" -m venv "$ROOT/agent/.venv"
"$ROOT/agent/.venv/bin/python" -m pip install --upgrade pip
"$ROOT/agent/.venv/bin/python" -m pip install -r "$ROOT/agent/requirements.txt"
echo "LangGraph Agent environment ready: $ROOT/agent/.venv"
