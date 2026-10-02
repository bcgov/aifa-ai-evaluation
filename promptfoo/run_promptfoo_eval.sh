#!/usr/bin/env bash
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

# Fall back to the repo-level env file when Promptfoo is launched from a parent shell
# or when the local SOCKS proxy is defined there instead of in the promptfoo subfolder.
if [ -z "${ALL_PROXY:-${HTTPS_PROXY:-${HTTP_PROXY:-}}}" ]; then
  for env_file in "$REPO_ROOT/.env" "$REPO_ROOT/aifa_pyrit/.env"; do
    if [ -f "$env_file" ]; then
      set -a
      . "$env_file"
      set +a
      break
    fi
  done
fi

# Promptfoo's default grading provider reads Azure env names such as AZURE_OPENAI_API_KEY
# and AZURE_OPENAI_BASE_URL. This repo stores the values under AZURE_OPENAI_* names,
# so normalize them before the eval starts.
export AZURE_OPENAI_DEPLOYMENT_NAME="${AZURE_OPENAI_DEPLOYMENT_NAME:-${AZURE_OPENAI_DEPLOYMENT:-${AZURE_DEPLOYMENT_NAME:-gpt-4}}}"
export AZURE_DEPLOYMENT_NAME="${AZURE_DEPLOYMENT_NAME:-${AZURE_OPENAI_DEPLOYMENT_NAME:-${AZURE_OPENAI_DEPLOYMENT:-gpt-4}}}"
export AZURE_API_KEY="${AZURE_API_KEY:-${AZURE_OPENAI_API_KEY:-}}"
export AZURE_OPENAI_API_KEY="${AZURE_OPENAI_API_KEY:-${AZURE_API_KEY:-}}"
export AZURE_OPENAI_BASE_URL="${AZURE_OPENAI_BASE_URL:-${AZURE_OPENAI_ENDPOINT:-}}"
export AZURE_API_BASE_URL="${AZURE_API_BASE_URL:-${AZURE_OPENAI_BASE_URL:-${AZURE_OPENAI_ENDPOINT:-}}}"
export AZURE_OPENAI_API_BASE_URL="${AZURE_OPENAI_API_BASE_URL:-${AZURE_OPENAI_BASE_URL:-${AZURE_OPENAI_ENDPOINT:-}}}"
export OPENAI_API_KEY="${OPENAI_API_KEY:-${AZURE_OPENAI_API_KEY:-}}"
export OPENAI_BASE_URL="${OPENAI_BASE_URL:-${AZURE_OPENAI_BASE_URL:-${AZURE_OPENAI_ENDPOINT:-}}}"

if [ -n "${AZURE_OPENAI_ENDPOINT:-}" ] && [[ "${AZURE_OPENAI_ENDPOINT}" != *.openai.azure.com* ]]; then
  echo "[promptfoo] WARNING: AZURE_OPENAI_ENDPOINT is not a standard Azure OpenAI resource URL (expected https://<resource>.openai.azure.com)."
  echo "[promptfoo] WARNING: llm-rubric grading will fail with 404 unless the endpoint matches Azure OpenAI's /openai/deployments/... contract."
  echo "[promptfoo] WARNING: Current endpoint: ${AZURE_OPENAI_ENDPOINT}"
fi

HEALTH_URL="http://127.0.0.1:8001/health"
GRADER_URL="http://127.0.0.1:8002/grade"
OUTPUT_PATH="$REPO_ROOT/results/promptfoo-report.json"

mkdir -p "$REPO_ROOT/results"

if ! curl -fsS "$GRADER_URL" >/dev/null 2>&1; then
  if [ -n "${ALL_PROXY:-${HTTPS_PROXY:-${HTTP_PROXY:-}}}" ]; then
    echo "[promptfoo] Starting local Azure grader proxy on http://127.0.0.1:8002"
    node "$SCRIPT_DIR/azure-grader-proxy.js" >/tmp/promptfoo-azure-grader.log 2>&1 &
  else
    echo "[promptfoo] WARNING: no ALL_PROXY/HTTPS_PROXY/HTTP_PROXY is configured."
    echo "[promptfoo] WARNING: Promptfoo llm-rubric grading will try a direct Azure OpenAI call and may time out."
  fi
fi

if curl -fsS "$HEALTH_URL" >/dev/null 2>&1; then
  :
else
  uv run uvicorn promptfoo.src.promptfoo_adapter:app --host 127.0.0.1 --port 8001 >/tmp/promptfoo-adapter.log 2>&1 &

  for _ in $(seq 1 30); do
    if curl -fsS "$HEALTH_URL" >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
fi

npx promptfoo eval -c promptfoo-config.yaml --output "$OUTPUT_PATH"

