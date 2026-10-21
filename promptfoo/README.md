# Promptfoo evaluation

Runs the test cases in [../data_promptfoo](../data_promptfoo) against the AIFA backend and has a judge model grade the answers. Separate from the PyRIT red-team package.

```
promptfoo eval ─► /invoke (adapter) ─► AIFA backend (WebSocket)
       └────────► /grade (azure-grader-proxy.js) ─► Azure OpenAI (judge)
```

## Configure

```bash
cd promptfoo
cp .env.example .env     # fill in the values
uv sync && npm ci        # Python deps and the judge proxy's Node deps
```

| Variable | Purpose |
|---|---|
| `AUDIT_LLM_ENDPOINT`, `_API_KEY`, `_DEPLOYMENT`, `_API_VERSION` | Judge model. Any endpoint serving `/openai/deployments/<deployment>/chat/completions` works, including a gateway path prefix |
| `BACKEND_API_URL` | AIFA system under test (`wss://…/ws`) |
| `AZURE_STORAGE_CONNECTION_STRING` | Optional Blob storage (see below) |

## Run from the command line

```bash
cd promptfoo
./run_promptfoo_eval.sh          # judge proxy + adapter + eval → ../results-promptfoo/promptfoo-report.json
./test_grader_no_proxy.sh        # checks the judge endpoint on its own
npx promptfoo view -p 15500 -y   # native Promptfoo viewer
```

The script restarts the judge proxy, starts the adapter on `:8001` if nothing is there, and runs every test case.

## Run the service (what the web UI talks to)

From the repo root:

```bash
(cd promptfoo && set -a && . ./.env && set +a && node azure-grader-proxy.js) &       # judge :8002
promptfoo/.venv/bin/python -m uvicorn promptfoo.src.promptfoo_service:app --port 8001
```

The service exposes the `/invoke` adapter, `/health`, and `/api/promptfoo/*` (jobs, results, test files). In Docker the entrypoint starts both the proxy and the service on `$PORT` (8001).

## Use it from the UI

Open **Run tests**, pick a YAML file from `data_promptfoo`, tick the cases, press **Run selected**. The run opens on its own screen with live CLI output and a pass/fail summary; **Results** keeps every run with per-test responses and grader reasons, JSON and CSV downloads, and **Re-run failures**.

## Use it from curl

```bash
curl localhost:8001/api/promptfoo/tests/files                              # YAML files and case counts
curl localhost:8001/api/promptfoo/tests/datasets/promptfoo_tests_cases.yaml/cases
curl -X POST localhost:8001/api/promptfoo/tests/run -H 'Content-Type: application/json' \
  -d '{"dataset":"promptfoo_tests_cases.yaml","cases":[0,1]}'              # → job id
curl "localhost:8001/api/promptfoo/jobs/<id>/logs?since=0"                 # console output
curl localhost:8001/api/promptfoo/results                                  # saved results
```

## Test cases and storage

A test file is a YAML list of `vars.query` plus `assert` entries (`icontains`, `llm-rubric`, …); see [../data_promptfoo/promptfoo_tests_cases.yaml](../data_promptfoo/promptfoo_tests_cases.yaml). Every `.yaml` file in `data_promptfoo/` appears in the UI.

With `AZURE_STORAGE_CONNECTION_STRING` (or `AZURE_STORAGE_ACCOUNT_NAME` for managed identity), test files are read from the `PROMPTFOO_DATA_CONTAINER_NAME` container (default `promptfoo-data`) and results are saved to `PROMPTFOO_RESULTS_CONTAINER_NAME` (`promptfoo-results`). Without them the local folders are used.

## Files

- [promptfoo-config.yaml](promptfoo-config.yaml): target, judge and tests; the target URL comes from `PROMPTFOO_TARGET_URL` (default `http://127.0.0.1:8001/invoke`)
- [src/promptfoo_service.py](src/promptfoo_service.py): API, jobs, results · [src/promptfoo_adapter.py](src/promptfoo_adapter.py), [src/promptfoo_wrapper.py](src/promptfoo_wrapper.py): `/invoke` and the WebSocket client
- [Dockerfile](Dockerfile), [docker-entrypoint.sh](docker-entrypoint.sh): container image
- [setup_local_forward.sh](setup_local_forward.sh), [teardown_local_forward.sh](teardown_local_forward.sh): optional SOCKS tunnel helpers ([../docs/proxy-connection-guide.md](../docs/proxy-connection-guide.md))
