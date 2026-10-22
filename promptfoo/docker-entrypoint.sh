#!/bin/sh
# Starts the grader proxy (used by promptfoo-config.yaml) and the promptfoo API on $PORT.
set -e
# Allow an explicit private-network proxy to pass through when the user opts in.
# Otherwise, keep the container on direct connectivity for local/public Azure endpoints.
if [ "${PROMPTFOO_USE_PRIVATE_PROXY:-0}" != "1" ] && [ "${PROMPTFOO_USE_PROXY:-0}" != "1" ]; then
  unset ALL_PROXY HTTPS_PROXY HTTP_PROXY all_proxy https_proxy http_proxy NO_PROXY no_proxy
  export NO_PROXY="localhost,127.0.0.1,::1"
  export no_proxy="${NO_PROXY}"
else
  export NO_PROXY="${NO_PROXY:-localhost,127.0.0.1,::1}"
  export no_proxy="${NO_PROXY}"
fi
OPENAI_API_KEY="${OPENAI_API_KEY:-${AUDIT_LLM_API_KEY:-}}" node /app/promptfoo/azure-grader-proxy.js &
exec uvicorn promptfoo.src.promptfoo_service:app --host 0.0.0.0 --port "${PORT:-8001}" --proxy-headers
