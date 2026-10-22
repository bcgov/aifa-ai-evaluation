# Promptfoo evaluation

Runs the test cases in [../data_promptfoo](../data_promptfoo) against the AIFA backend and has a judge model grade the answers. Separate from the PyRIT red-team package.

```
promptfoo eval ─► /invoke (adapter) ─► AIFA backend (WebSocket)
       └────────► /grade (azure-grader-proxy.js) ─► Azure OpenAI (judge)
```

## Configure

```bash
cd promptfoo
cp .env.example .env
uv sync && npm ci
```

Required values:

| Variable | Purpose |
|---|---|
| `AUDIT_LLM_ENDPOINT`, `_API_KEY`, `_DEPLOYMENT`, `_API_VERSION` | Judge model used for rubric grading |
| `BACKEND_API_URL` | AIFA backend under test (`wss://…/ws`) |
| `AZURE_STORAGE_CONNECTION_STRING` | Optional Blob storage |

## Run from the command line

Use the repo-level launcher for the supported local setup:

```bash
cd /Users/jatindersingh/Desktop/Projects/AI/project/aifa-ai-evaluation
./scripts/start_app_with_proxy.sh
```

This starts the full stack, including the Promptfoo judge proxy and the Promptfoo service.

You can also run only Promptfoo tests using the repo script:

```bash
cd promptfoo
./run_promptfoo_eval.sh
```

Other useful commands:

```bash
./test_grader_no_proxy.sh
npx promptfoo view -p 15500 -y
```

## Private endpoint / proxy mode

If the judge model is behind a private Azure endpoint, you must preserve the proxy chain in the same shell session that starts the app:

```bash
export PROMPTFOO_USE_PRIVATE_PROXY=1
export HTTP_PROXY=http://127.0.0.1:8118
export HTTPS_PROXY=http://127.0.0.1:8118
export ALL_PROXY=http://127.0.0.1:8118
export NO_PROXY=localhost,127.0.0.1,::1

./scripts/start_app_with_proxy.sh
```

This is the supported local path when the Azure judge endpoint blocks direct public access.

For the full private-network tunnel setup, see [../docs/private-network-proxy.md](../docs/private-network-proxy.md).

## Run the service the browser talks to

From the repo root:

```bash
./scripts/start_app_with_proxy.sh
```

This starts:

- Promptfoo API on `http://127.0.0.1:8001`
- Judge proxy on `http://127.0.0.1:8002`
- PyRIT app on `http://127.0.0.1:8011`

The service exposes `/invoke`, `/health`, and `/api/promptfoo/*` endpoints used by the UI and job runner.

## Use it from the UI

Open the main app at `http://localhost:8011`, then go to the Promptfoo flow in the browser. Select a YAML case file from `data_promptfoo`, choose the cases, and run them. Results are kept under `results-promptfoo/` and can be re-run or downloaded from the UI.

## Use it from curl

```bash
curl http://127.0.0.1:8001/api/promptfoo/tests/files
curl http://127.0.0.1:8001/api/promptfoo/tests/datasets/promptfoo_tests_cases.yaml/cases
curl -X POST http://127.0.0.1:8001/api/promptfoo/tests/run -H 'Content-Type: application/json' \
  -d '{"dataset":"promptfoo_tests_cases.yaml","cases":[0,1]}'
curl "http://127.0.0.1:8001/api/promptfoo/jobs/<id>/logs?since=0"
curl http://127.0.0.1:8001/api/promptfoo/results
```

## Test cases and storage

Test files live under [../data_promptfoo](../data_promptfoo) and are YAML lists of `vars.query` plus assertions such as `icontains` or `llm-rubric`.

When Azure storage is configured, Promptfoo reads dataset files from the configured data container and writes results to the results container; otherwise it uses the local `data_promptfoo/` and `results-promptfoo/` folders.

## Files

- [promptfoo-config.yaml](promptfoo-config.yaml): target, judgment config, and test settings
- [src/promptfoo_service.py](src/promptfoo_service.py): API, jobs, results
- [src/promptfoo_adapter.py](src/promptfoo_adapter.py): `/invoke` and `/health`
- [azure-grader-proxy.js](azure-grader-proxy.js): legacy grader compatibility shim
- [Dockerfile](Dockerfile), [docker-entrypoint.sh](docker-entrypoint.sh): container image
