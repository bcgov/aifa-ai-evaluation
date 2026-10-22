# PyRIT red-team (`aifa_pyrit`)

Attacks the AIFA backend with [PyRIT](https://github.com/Azure/PyRIT) (jailbreaks, prompt injection, multi-turn) and scores each answer. Used from the command line or through a FastAPI app that also serves the browser UI.

## Configure

```bash
uv sync --extra dev                       # from the repo root
cp aifa_pyrit/.env.example aifa_pyrit/.env
```

| Variable | Purpose |
|---|---|
| `BACKEND_API_URL` | AIFA system under test (`wss://…/ws`) |
| `AUDIT_LLM_API_KEY`, `_ENDPOINT`, `_DEPLOYMENT` | Judge/scorer model |
| `ADVERSARIAL_OPENAI_API_KEY`, `_ENDPOINT`, `_DEPLOYMENT` | Attacker model for LLM-driven attacks |
| `AZURE_STORAGE_CONNECTION_STRING` | Optional: store reports and test cases in Azure Blob |

Full list: [../env-inventory.md](../env-inventory.md).

## Command line

```bash
uv run red-team --help
uv run red-team list-cases                               # show cases from data/red_team_test_cases.json
uv run red-team scan --use-file -a PromptSending         # run every case
uv run red-team scan --use-file -a Crescendo -c sysprompt_repeat_above   # selected cases
uv run red-team test-query -q "What is the application fee?" -a Crescendo # one ad-hoc question
uv run red-team seed-attack -d "violence,harassment"      # seed prompts from PyRIT datasets
uv run red-team check-proxy                              # show effective proxy settings and validate Azure access
```

Attack types (`-a`): `PromptSending`, `Crescendo`, `MultiTurn`, `RedTeaming`, `PromptSeed`. Reports are written to `results/` (or the Blob results container).

## Web app and API

Use the shared repo launcher for the supported local setup:

```bash
./scripts/start_app_with_proxy.sh
```

This starts the PyRIT app plus the Promptfoo service and judge proxy in one shell. The browser UI is available at <http://localhost:8011>.

If you want to run only the PyRIT app manually:

```bash
uv run python -m uvicorn aifa_pyrit.web_app:app --host 127.0.0.1 --port 8011
```

Open <http://localhost:8011>: **New Run**, **Live Run**, and **Export**.

Useful checks:

```bash
curl http://127.0.0.1:8011/api/health
curl http://127.0.0.1:8011/api/datasets
curl -X POST http://127.0.0.1:8011/api/runs -H 'Content-Type: application/json' \
  -d '{"tenant_id":"aifa-water-licence","dataset_id":"saved-test-cases","attack_type":"PromptSending"}'
curl http://127.0.0.1:8011/api/runs/<id>
curl http://127.0.0.1:8011/api/reports
```

`/api/promptfoo/*` is forwarded to the Promptfoo service (`PROMPTFOO_SERVICE_URL`, default `http://127.0.0.1:8001`) for local development.

If the judge endpoint is private-only, export the proxy chain in the same shell before starting the app:

```bash
export PROMPTFOO_USE_PRIVATE_PROXY=1
export HTTP_PROXY=http://127.0.0.1:8118
export HTTPS_PROXY=http://127.0.0.1:8118
export ALL_PROXY=http://127.0.0.1:8118
./scripts/start_app_with_proxy.sh
```

## Test cases

`data/red_team_test_cases.json` is `{"test_cases": [{"name", "query", "expected_behavior", "description"}]}`. Add a case, then run `list-cases` to confirm. With Azure Blob enabled the file is read from the `PYRIT_DATA_CONTAINER_NAME` container (default `pyrit-data`) and reports go to `PYRIT_RESULTS_CONTAINER_NAME` (`pyrit-results`).

## Docker

```bash
docker build -f aifa_pyrit/Dockerfile -t aifa-pyrit .
docker run --rm -p 8000:8000 --env-file aifa_pyrit/.env -v "$PWD/results:/app/results" aifa-pyrit
```
