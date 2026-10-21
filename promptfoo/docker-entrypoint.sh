#!/bin/sh
# Starts the grader proxy (used by promptfoo-config.yaml) and the promptfoo API on $PORT.
set -e
# Host-local proxies (e.g. socks5h://127.0.0.1:8081 from a developer .env) are unreachable in the container.
unset ALL_PROXY HTTPS_PROXY HTTP_PROXY all_proxy https_proxy http_proxy
OPENAI_API_KEY="${OPENAI_API_KEY:-${AUDIT_LLM_API_KEY:-}}" node /app/promptfoo/azure-grader-proxy.js &
exec uvicorn promptfoo.src.promptfoo_service:app --host 0.0.0.0 --port "${PORT:-8001}" --proxy-headers
