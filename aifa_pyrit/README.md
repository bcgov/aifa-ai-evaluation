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

The web app lists each valid JSON dataset separately under **Test questions**. Each file uses `{"test_cases": [{"name": "unique_case_name", "query": "Question", "expected_behavior": "Expected result", "description": "Purpose"}]}`. Names must be unique within a file; each case requires a nonempty name and query. Empty, malformed, and unrelated JSON files are skipped with a warning in the backend logs.

Without Azure storage configuration, the web app discovers JSON files directly under `data/`. With `AZURE_STORAGE_CONNECTION_STRING` or `AZURE_STORAGE_ACCOUNT_NAME` configured, it instead discovers JSON blobs in `PYRIT_DATA_CONTAINER_NAME` (default `pyrit-data`), including blobs in virtual folders. Storage failures return HTTP 503 and appear in the UI rather than silently switching to local files. Uploading files to the container does not require an app restart; reload the page to refresh the dropdown.

The dropdown sends the selected dataset ID to the run API, so only that file's cases run. IDs look like `azure:red_team_test_cases_security.json` or `local:red_team_test_cases_security.json`; use the ID returned by `/api/datasets`. The old `saved-test-cases` ID remains an alias for the default file. CLI `list-cases`, CLI file scans, and the classic scan API still use the existing default-file loader.

### Azure Container Apps setup

Rebuild and deploy the updated **PyRIT backend and frontend images**. Environment changes alone cannot enable multi-file selection in an older image. Set the following on the **pyrit container**, not only the frontend or Promptfoo container:

| Variable | Value |
| --- | --- |
| `PYRIT_DATA_CONTAINER_NAME` | Your existing test dataset container, for example `pyrit-data` |
| `PYRIT_RESULTS_CONTAINER_NAME` | Your reports container, for example `pyrit-results` |
| `AZURE_STORAGE_ACCOUNT_NAME` | Storage account name only, when using managed identity |
| `AZURE_STORAGE_CONNECTION_STRING` | Alternative to managed identity: a connection string supplied through an ACA secret reference |

Prefer managed identity: enable the Container App identity and grant it **Storage Blob Data Reader** on the data container. Report storage additionally needs write/create permissions, typically **Storage Blob Data Contributor** on the reports container. Leave the connection string unset for managed identity; if both authentication settings are supplied, the connection string wins. These roles must be assigned to the identity used by the backend, not your personal account. The data reader does not create the data container.

The existing ACA Terraform configuration already forwards `azure_storage_connection_string`, `pyrit_data_container_name`, and `pyrit_results_container_name` into the PyRIT container. It does not currently forward `AZURE_STORAGE_ACCOUNT_NAME`; add that environment setting through your deployment configuration if choosing managed identity. This change does not modify Terraform or deployed resources.

Create the data container and upload the dataset JSON files themselves. For example, upload `red_team_test_cases.json`, `red_team_test_cases_additional.json`, `red_team_test_cases_security.json`, and `red_team_test_cases_integrity.json` as separate blobs. Committing these files does not upload them to Azure. Keep data and results in different containers.

Storage firewalls and private endpoints must allow the ACA environment to reach the Blob endpoint, including correct private DNS when applicable. Credentials alone do not provide network access.

After deploying and reloading the frontend, inspect `GET https://<your-app-host>/api/datasets`:

- Multiple entries with `source: "azure"`: discovery is working; the UI should show their filenames and case counts.
- Entries with `source: "local"`: neither Azure authentication setting is configured on the backend.
- HTTP 503: check the backend logs, authentication, Blob data permissions, container name, firewall, and private DNS.
- An empty array: the selected source has no nonempty valid test-case datasets; inspect JSON format and skipped-file warnings.
- Only a `saved-test-cases` entry named `Saved test cases`: the backend is still running the older single-file implementation.

No additional dataset-specific environment variable is required. Existing `BACKEND_API_URL` and attacker/judge settings are still required to execute evaluations; they do not control dataset discovery.

## Docker

```bash
docker build -f aifa_pyrit/Dockerfile -t aifa-pyrit .
docker run --rm -p 8000:8000 --env-file aifa_pyrit/.env -v "$PWD/results:/app/results" aifa-pyrit
```
