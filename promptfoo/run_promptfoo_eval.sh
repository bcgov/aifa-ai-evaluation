#!/usr/bin/env bash
# CLI eval: (re)starts the judge proxy, makes sure the /invoke target is up, runs promptfoo, writes the JSON report.
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
export PYTHONPATH="$REPO_ROOT:$SCRIPT_DIR:${PYTHONPATH:-}"
cd "$SCRIPT_DIR"

if [ -f .env ]; then
  set -a
  . ./.env
  set +a
fi

# Azure and the backend are reached directly; a leftover SOCKS proxy would break Node's fetch.
unset ALL_PROXY HTTPS_PROXY HTTP_PROXY all_proxy https_proxy http_proxy NO_PROXY no_proxy
export OPENAI_API_KEY="${OPENAI_API_KEY:-${AUDIT_LLM_API_KEY:-}}"
export PROMPTFOO_DISABLE_TELEMETRY=1 PROMPTFOO_DISABLE_UPDATE=1

TARGET_HEALTH="http://127.0.0.1:8001/health"
GRADER_HEALTH="http://127.0.0.1:8002/health"
OUTPUT_PATH="$REPO_ROOT/results-promptfoo/promptfoo-report.json"
mkdir -p "$REPO_ROOT/results-promptfoo"

wait_for() {
  for _ in $(seq 1 30); do
    curl -fsS "$1" >/dev/null 2>&1 && return 0
    sleep 1
  done
  echo "[promptfoo] ERROR: $1 did not come up" >&2
  return 1
}

# Always restart the grader so it picks up the current .env.
lsof -ti tcp:8002 2>/dev/null | xargs kill 2>/dev/null || true
node "$SCRIPT_DIR/azure-grader-proxy.js" >/tmp/promptfoo-azure-grader.log 2>&1 &
wait_for "$GRADER_HEALTH" || exit 1

# Reuse a running target (e.g. the web service) or start the bare adapter.
if ! curl -fsS "$TARGET_HEALTH" >/dev/null 2>&1; then
  uv run uvicorn promptfoo.src.promptfoo_adapter:app --host 127.0.0.1 --port 8001 >/tmp/promptfoo-adapter.log 2>&1 &
  wait_for "$TARGET_HEALTH" || exit 1
fi

npx --yes promptfoo eval -c promptfoo-config.yaml --output "$OUTPUT_PATH"
EXIT_CODE=$?

# promptfoo exits 100 when the run finished but some tests failed; the report is still written.
[ "$EXIT_CODE" -eq 100 ] && EXIT_CODE=0
exit $EXIT_CODE
