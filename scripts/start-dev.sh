#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

PYTHON="${AGENT_PYTHON:-$ROOT/agent/.venv/bin/python}"
[[ -x "$PYTHON" ]] || {
  echo "Agent virtualenv is missing. Run: bash scripts/setup-agent.sh" >&2
  exit 1
}
[[ -x "$ROOT/bin/main" ]] || {
  echo "C++ server is not built. Run: bash setup.sh" >&2
  exit 1
}

export PYTHONPATH="$ROOT/agent/backend${PYTHONPATH:+:$PYTHONPATH}"
"$PYTHON" "$ROOT/agent/backend/run.py" &
AGENT_PID=$!
cleanup() {
  kill "$AGENT_PID" 2>/dev/null || true
  wait "$AGENT_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

AGENT_HEALTH_URL="${AGENT_SERVICE_URL:-http://127.0.0.1:8010}/api/health"
READY=0
for _ in $(seq 1 60); do
  if curl -fsS "$AGENT_HEALTH_URL" >/dev/null 2>&1; then
    READY=1
    break
  fi
  if ! kill -0 "$AGENT_PID" 2>/dev/null; then
    echo "LangGraph Agent exited during startup" >&2
    exit 1
  fi
  sleep 1
done

if [[ "$READY" != "1" ]]; then
  echo "Timed out waiting for Agent: $AGENT_HEALTH_URL" >&2
  exit 1
fi

"$ROOT/bin/main"
