#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PYRIT_ENV_FILE="$REPO_ROOT/aifa_pyrit/.env"
PROMPTFOO_ENV_FILE="$REPO_ROOT/promptfoo/.env"
LOG_DIR="$REPO_ROOT/.logs"
mkdir -p "$LOG_DIR"

usage() {
  cat <<'EOF'
Usage: scripts/start_app_with_proxy.sh [--backend-only|--promptfoo-only|--check]

Starts the local stack with the private-network proxy settings loaded for Azure judge calls.
This launches the PyRIT web app, the Promptfoo judge proxy, and the Promptfoo service together.

Environment variables:
  HTTP_PROXY, HTTPS_PROXY, ALL_PROXY
    Optional explicit proxy settings. Defaults to http://127.0.0.1:8118 when unset.
  PROMPTFOO_USE_PRIVATE_PROXY
    Set to 1 to preserve proxy settings when starting Promptfoo.
  USE_AZURE_PROXY
    Set to true to preserve Proxy env for PyRIT runtime.

Examples:
  export HTTP_PROXY=http://127.0.0.1:8118
  export HTTPS_PROXY=http://127.0.0.1:8118
  export ALL_PROXY=http://127.0.0.1:8118
  scripts/start_app_with_proxy.sh

  scripts/start_app_with_proxy.sh --check
EOF
}

load_env_file() {
  local env_file="$1"
  if [[ -f "$env_file" ]]; then
    set -a
    # shellcheck disable=SC1090
    . "$env_file"
    set +a
  fi
}

wait_for_health() {
  local url="$1"
  local name="$2"
  local max_attempts="${3:-60}"
  for ((attempt=1; attempt<=max_attempts; attempt++)); do
    if curl --silent --show-error --fail "$url" >/dev/null 2>&1; then
      echo "${name} is ready at ${url}"
      return 0
    fi
    sleep 1
  done
  echo "${name} did not become ready at ${url} within ${max_attempts}s" >&2
  return 1
}

CHECK_ONLY=0
BACKEND_ONLY=0
PROMPTFOO_ONLY=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --check)
      CHECK_ONLY=1
      ;;
    --backend-only)
      BACKEND_ONLY=1
      ;;
    --promptfoo-only)
      PROMPTFOO_ONLY=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

load_env_file "$PYRIT_ENV_FILE"
load_env_file "$PROMPTFOO_ENV_FILE"

if [[ -z "${HTTP_PROXY:-}" && -z "${HTTPS_PROXY:-}" && -z "${ALL_PROXY:-}" ]]; then
  export HTTP_PROXY="${HTTP_PROXY:-http://127.0.0.1:8118}"
  export HTTPS_PROXY="${HTTPS_PROXY:-http://127.0.0.1:8118}"
  export ALL_PROXY="${ALL_PROXY:-http://127.0.0.1:8118}"
fi

export PROMPTFOO_USE_PRIVATE_PROXY="${PROMPTFOO_USE_PRIVATE_PROXY:-1}"
export USE_AZURE_PROXY="${USE_AZURE_PROXY:-true}"
export NO_PROXY="${NO_PROXY:-localhost,127.0.0.1,::1}"
export no_proxy="${NO_PROXY}"

if [[ "$CHECK_ONLY" -eq 1 ]]; then
  echo "Proxy-aware app startup configuration"
  echo "HTTP_PROXY=${HTTP_PROXY}"
  echo "HTTPS_PROXY=${HTTPS_PROXY}"
  echo "ALL_PROXY=${ALL_PROXY}"
  echo "PROMPTFOO_USE_PRIVATE_PROXY=${PROMPTFOO_USE_PRIVATE_PROXY}"
  echo "USE_AZURE_PROXY=${USE_AZURE_PROXY}"
  echo "NO_PROXY=${NO_PROXY}"
  exit 0
fi

cd "$REPO_ROOT"
BACKEND_PID=""
PROMPTFOO_PID=""
PROXY_PID=""

if [[ "$PROMPTFOO_ONLY" -eq 0 && "$BACKEND_ONLY" -eq 0 ]]; then
  echo "Starting backend app on http://127.0.0.1:8011"
  uv run python -m uvicorn aifa_pyrit.web_app:app --host 127.0.0.1 --port 8011 >"$LOG_DIR/backend.log" 2>&1 &
  BACKEND_PID=$!
fi

if [[ "$BACKEND_ONLY" -eq 0 ]]; then
  echo "Starting promptfoo judge proxy on http://127.0.0.1:8002"
  (
    cd "$REPO_ROOT/promptfoo"
    OPENAI_API_KEY="${OPENAI_API_KEY:-${AUDIT_LLM_API_KEY:-}}" node azure-grader-proxy.js >"$LOG_DIR/promptfoo-proxy.log" 2>&1
  ) &
  PROXY_PID=$!

  echo "Starting promptfoo service on http://127.0.0.1:8001"
  if [[ -x "$REPO_ROOT/promptfoo/.venv/bin/python" ]]; then
    cd "$REPO_ROOT"
    PYTHONPATH="$REPO_ROOT:$REPO_ROOT/promptfoo${PYTHONPATH:+:$PYTHONPATH}" \
      "$REPO_ROOT/promptfoo/.venv/bin/python" -m uvicorn promptfoo.src.promptfoo_service:app --host 127.0.0.1 --port 8001 >"$LOG_DIR/promptfoo-service.log" 2>&1 &
    PROMPTFOO_PID=$!
  else
    echo "promptfoo virtualenv not found at $REPO_ROOT/promptfoo/.venv/bin/python" >&2
    echo "Falling back to a local uvicorn via 'uv run' if available" >&2
    cd "$REPO_ROOT"
    PYTHONPATH="$REPO_ROOT:$REPO_ROOT/promptfoo${PYTHONPATH:+:$PYTHONPATH}" \
      uv run python -m uvicorn promptfoo.src.promptfoo_service:app --host 127.0.0.1 --port 8001 >"$LOG_DIR/promptfoo-service.log" 2>&1 &
    PROMPTFOO_PID=$!
  fi
fi

cleanup() {
  for pid in "${BACKEND_PID:-}" "${PROMPTFOO_PID:-}" "${PROXY_PID:-}"; do
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" || true
    fi
  done
}

trap cleanup EXIT

if [[ "$PROMPTFOO_ONLY" -eq 0 && "$BACKEND_ONLY" -eq 0 ]]; then
  wait_for_health "http://127.0.0.1:8011/api/health" "PyRIT web app" || exit 1
  wait_for_health "http://127.0.0.1:8001/api/promptfoo/info" "Promptfoo service" || exit 1
  wait_for_health "http://127.0.0.1:8002/health" "Promptfoo grader proxy" || exit 1
  echo "All services are ready."
  echo "PyRIT: http://127.0.0.1:8011"
  echo "Promptfoo: http://127.0.0.1:8001"
  echo "Judge proxy: http://127.0.0.1:8002"
fi

wait_for_pids=()
for pid in "${BACKEND_PID:-}" "${PROMPTFOO_PID:-}" "${PROXY_PID:-}"; do
  if [[ -n "$pid" ]]; then
    wait_for_pids+=("$pid")
  fi
done

if [[ ${#wait_for_pids[@]} -gt 0 ]]; then
  wait "${wait_for_pids[@]}"
fi
