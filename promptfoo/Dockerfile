# Build from the repo root: docker build -f promptfoo/Dockerfile .
FROM node:22-bookworm-slim

ARG PROMPTFOO_VERSION=latest

RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-venv curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

RUN npm install -g "promptfoo@${PROMPTFOO_VERSION}" && npm cache clean --force

RUN python3 -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir \
    "fastapi>=0.110.0" "uvicorn>=0.30.0" "httpx[socks]>=0.25.0" "websockets>=12.0" \
    "pydantic>=2.5.0" "pydantic-settings>=2.1.0" "python-dotenv>=1.1.1"

WORKDIR /app/promptfoo
COPY promptfoo/package.json promptfoo/package-lock.json ./
RUN npm ci --omit=dev

COPY promptfoo/ /app/promptfoo/
COPY data_promptfoo/ /app/data_promptfoo/

RUN mkdir -p /app/results-promptfoo /app/results \
 && chmod +x docker-entrypoint.sh run_promptfoo_eval.sh \
 && chown -R node:node /app

ENV PATH=/opt/venv/bin:$PATH \
    PYTHONPATH=/app \
    PORT=8001 \
    PROMPTFOO_RESULTS_DIR=/app/results-promptfoo \
    PROMPTFOO_CONFIG_DIR=/app/results-promptfoo/.promptfoo \
    PROMPTFOO_DISABLE_TELEMETRY=1 \
    PROMPTFOO_DISABLE_UPDATE=1 \
    PROMPTFOO_DISABLE_REMOTE_GENERATION=true \
    PROMPTFOO_RUNNING_IN_DOCKER=true

USER node
EXPOSE 8001
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD curl -fsS "http://127.0.0.1:${PORT}/health" || exit 1
ENTRYPOINT ["./docker-entrypoint.sh"]
