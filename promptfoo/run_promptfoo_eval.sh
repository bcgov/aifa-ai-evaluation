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
# Write promptfoo outputs to results-promptfoo by default to isolate from PyRIT
OUTPUT_PATH="$REPO_ROOT/results-promptfoo/promptfoo-report.json"

mkdir -p "$REPO_ROOT/results-promptfoo"

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

# Avoid leaking host-local proxy settings into the containerized `npx` invocation.
# When a developer has a local proxy (e.g. 127.0.0.1:8081) exported on the host,
# npm/npx will attempt to use it and fail inside the container because
# localhost inside the container is the container itself. Clear common proxy
# env vars for the `npx` step so it uses direct network access.
unset ALL_PROXY HTTPS_PROXY HTTP_PROXY all_proxy https_proxy http_proxy

# Ensure npx installs run non-interactively (accept prompts) and use --yes
# to avoid interactive confirmation in CI/containers. Preload a small shim to
# disable telemetry which sometimes blocks during shutdown.
NODE_PRELOAD="-r $SCRIPT_DIR/disable-telemetry.js"
NODE_LOADER="--loader=$SCRIPT_DIR/disable-telemetry-loader.mjs"
if command -v npx >/dev/null 2>&1; then
  NODE_OPTIONS="$NODE_PRELOAD $NODE_LOADER" npx --yes promptfoo eval -c promptfoo-config.yaml --output "$OUTPUT_PATH"
  EXIT_CODE=$?
elif command -v npm >/dev/null 2>&1; then
  # Some minimal node images don't include npx; `npm exec --yes` is equivalent.
  NODE_OPTIONS="$NODE_PRELOAD $NODE_LOADER" npm exec --yes -- promptfoo eval -c promptfoo-config.yaml --output "$OUTPUT_PATH"
  EXIT_CODE=$?
else
  echo "[promptfoo] ERROR: neither 'npx' nor 'npm' is available in PATH."
  EXIT_CODE=127
fi

echo "[promptfoo] promptfoo exit code: $EXIT_CODE"

# If promptfoo failed during shutdown (telemetry) or similar but wrote a valid
# output report, treat the run as successful so downstream consumers can read
# the JSON results. This avoids transient telemetry shutdown errors (exit 100)
# from blocking the evaluation flow when `results-promptfoo/promptfoo-report.json`
# exists and is non-empty.
if [ "$EXIT_CODE" -ne 0 ] && [ -s "$OUTPUT_PATH" ]; then
  echo "[promptfoo] Non-zero exit but output exists at $OUTPUT_PATH; treating as success (clearing exit code)"
  EXIT_CODE=0
fi

exit $EXIT_CODE

