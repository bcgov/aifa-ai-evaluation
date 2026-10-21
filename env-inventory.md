# Environment variable inventory

All three containers run in one Azure Container App (shared `localhost`; only `frontend` has ingress).
Docker Compose mirrors this, but uses service names (`backend`, `promptfoo`) instead of `127.0.0.1`.

Legend: **Req** = required for the container to do useful work · **Secret** = store as a secret, never in plain config ·
**TF** = set by [infra/aca/main.tf](../infra/aca/main.tf).

## frontend (nginx, port 80)

| Variable | Req | Default | Secret | TF | Purpose |
|---|---|---|---|---|---|
| `PYRIT_UPSTREAM` | yes | `127.0.0.1:8000` | | ✓ | Where nginx sends `/api/*`. Compose: `backend:8000` |
| `PROMPTFOO_UPSTREAM` | yes | `127.0.0.1:8001` | | ✓ | Where nginx sends `/api/promptfoo/*`. Compose: `promptfoo:8001` |
| `PROMPTFOO_RUN_TOKEN` | no | empty | ✓ | ✓ | Injected as `X-Run-Token` on promptfoo calls; must equal the promptfoo container's value |
| `PYRIT_API_URL` | no | `/api` | | ✓ | Written to `config.js` (informational) |
| `PROMPTFOO_API_URL` | no | `/api/promptfoo` | | ✓ | Written to `config.js` (informational) |
| `PORT`, `APP_ENV` | no | – | | ✓ | Not read by nginx (listens on 80); informational only |

Set in the image (do not override): `NGINX_ENVSUBST_FILTER`, `NGINX_ENTRYPOINT_LOCAL_RESOLVERS`.

## pyrit (FastAPI, port 8000)

| Variable | Req | Default | Secret | TF | Purpose |
|---|---|---|---|---|---|
| `PORT` | no | `8000` | | ✓ | Uvicorn port; must match `PYRIT_UPSTREAM` |
| `BACKEND_API_URL` | **yes** | `http://localhost:8000` | | ✓ | AIFA system under test (WebSocket/HTTP base URL) |
| `BACKEND_API_TIMEOUT` | no | `30` | | ✓ | Seconds per target call |
| `BACKEND_CLIENT_ID` | no | built-in test GUID | | | `client_id` sent to AIFA |
| `BACKEND_APPLICATION_ID` | no | `234554` | | | `application_id` sent to AIFA |
| `BACKEND_STEP_NUMBER` | no | `step2-Eligibility` | | | Form step sent to AIFA |
| `AUDIT_LLM_API_KEY` | **yes**¹ | – | ✓ | ✓ | Scorer/judge model |
| `AUDIT_LLM_ENDPOINT` | **yes**¹ | – | | ✓ | Scorer/judge endpoint |
| `AUDIT_LLM_DEPLOYMENT` | **yes**¹ | `gpt-4` | | ✓ | Scorer/judge deployment |
| `AUDIT_LLM_API_VERSION` | no | `2024-02-15-preview` | | ✓ | |
| `ADVERSARIAL_OPENAI_API_KEY` | for LLM attacks² | – | ✓ | ✓ | Attacker model |
| `ADVERSARIAL_OPENAI_ENDPOINT` | for LLM attacks² | – | | ✓ | |
| `ADVERSARIAL_OPENAI_DEPLOYMENT` | for LLM attacks² | `gpt-4` | | ✓ | |
| `ADVERSARIAL_OPENAI_API_VERSION` | no | `2024-10-21` | | | Not set by TF; default applies |
| `RED_TEAM_THREAT_MODELS` | no | `jailbreak,prompt_injection,data_exfiltration` | | | |
| `RED_TEAM_MAX_ITERATIONS` | no | `5` | | | |
| `RED_TEAM_TIMEOUT_SECONDS` | no | `300` | | | |
| `RED_TEAM_VULNERABILITY_THRESHOLD` | no | `0.3` | | | |
| `AZURE_STORAGE_CONNECTION_STRING` | no³ | empty | ✓ | ✓ | Enables Azure Blob for reports/test cases |
| `AZURE_STORAGE_ACCOUNT_NAME` | no³ | empty | | | Managed-identity alternative to the connection string |
| `PYRIT_RESULTS_CONTAINER_NAME` | no | `pyrit-results` | | ✓ | Reports container |
| `PYRIT_DATA_CONTAINER_NAME` | no | `pyrit-data` | | ✓ | Holds `red_team_test_cases.json` |
| `AZURE_STORAGE_CONTAINER_NAME` | no | – | | | Legacy fallback for `PYRIT_RESULTS_CONTAINER_NAME` |
| `AZURE_TESTCASES_CONTAINER_NAME` | no | – | | | Legacy fallback for `PYRIT_DATA_CONTAINER_NAME` |
| `PROMPTFOO_RUN_TOKEN` | no | empty | ✓ | | Only for the legacy `/api/run-promptfoo` endpoint |
| `LOG_LEVEL` | no | `INFO` | | ✓ | |
| `APP_ENV` | no | – | | ✓ | Informational |

Local development only (leave unset in ACA):

| Variable | Purpose |
|---|---|
| `ALL_PROXY` / `HTTPS_PROXY` / `HTTP_PROXY`, `RED_TEAM_PROXY_URL` / `PROXY_URL`, `NO_PROXY`, `USE_AZURE_PROXY` | SOCKS/HTTP tunnel to reach private Azure endpoints from a laptop |
| `PROMPTFOO_SERVICE_URL` (default `http://127.0.0.1:8001`) | Dev pass-through for `/api/promptfoo/*` when the UI is served by uvicorn instead of nginx |
| `PROMPTFOO_CONTAINER_RUN_URL` | Legacy `/api/run-promptfoo` only |

Set internally at runtime (do not set): `OPENAI_CHAT_ENDPOINT`, `OPENAI_CHAT_KEY`, `OPENAI_CHAT_MODEL`.
Present in `config.py` but unused by the containerised flow: `AZURE_SEARCH_*`, `AZURE_AI_PROJECT`, `ENABLE_RED_TEAM`,
`ENABLED_EVALUATORS`, `EVALUATION_*`, `GROUNDEDNESS_THRESHOLD`, `CODE_VULNERABILITY_THRESHOLD`.

## promptfoo (FastAPI + promptfoo CLI, port 8001)

| Variable | Req | Default | Secret | TF | Purpose |
|---|---|---|---|---|---|
| `PORT` | no | `8001` | | ✓ | Uvicorn port; must match `PROMPTFOO_UPSTREAM` |
| `BACKEND_API_URL` | **yes** | `http://localhost:8000` | | ✓ | AIFA system under test (the adapter's `/invoke` forwards here) |
| `BACKEND_API_TIMEOUT` | no | `30` | | ✓ | |
| `BACKEND_CLIENT_ID` / `BACKEND_APPLICATION_ID` / `BACKEND_STEP_NUMBER` | no | as in pyrit | | | Values sent to AIFA |
| `AUDIT_LLMI_KEY` | **yes**¹ | – | ✓ | ✓ | Grader (llm-rubric) model; mapped to promptfoo's `AZURE_API_KEY` |
| `AUDIT_LLM_ENDPOINT` | **yes**¹ | – | | ✓ | Grader host |
| `AUDIT_LLM_DEPLOYMENT` | **yes**¹ | `gpt-4` | | ✓ | Grader deployment |
| `AUDIT_LLM_API_VERSION` | no | `2024-02-15-preview` | | ✓ | |
| `ADVERSARIAL_OPENAI_API_KEY` | for red team² | – | ✓ | ✓ | Attack-probe generator; falls back to the grader model |
| `ADVERSARIAL_OPENAI_ENDPOINT` | for red team² | – | | ✓ | |
| `ADVERSARIAL_OPENAI_DEPLOYMENT` | for red team² | `gpt-4` | | ✓ | |
| `PROMPTFOO_RUN_TOKEN` | no | empty | ✓ | ✓ | If set, every `/api/promptfoo/*` call must send it (nginx does) |
| `AZURE_STORAGE_CONNECTION_STRING` | no³ | empty | ✓ | ✓ | Enables Azure Blob for promptfoo data/results |
| `AZURE_STORAGE_ACCOUNT_NAME` | no³ | empty | | | Managed-identity alternative |
| `PROMPTFOO_RESULTS_CONTAINER_NAME` | no | `promptfoo-results` | | ✓ | Results, generated configs, run metadata |
| `PROMPTFOO_DATA_CONTAINER_NAME` | no | `promptfoo-data` | | ✓ | Holds `promptfoo_tests_cases.yaml` |
| `PROMPTFOO_MAX_PARALLEL_JOBS` | no | `1` | | | Concurrent promptfoo jobs |
| `PROMPTFOO_JOB_TIMEOUT` | no | `3600` | | | Seconds per job step |
| `PROMPTFOO_DISABLE_REMOTE_GENERATION` | no | `true` (image) | | | `false` allows Promptfoo-hosted probe generation (sends data to Promptfoo Cloud) |
| `APP_ENV` | no | – | | ✓ | Informational |

Set in the image (normally leave as is): `PROMPTFOO_RESULTS_DIR=/app/results-promptfoo`,
`PROMPTFOO_CONFIG_DIR`, `PROMPTFOO_DISABLE_TELEMETRY=1`, `PROMPTFOO_DISABLE_UPDATE=1`, `PROMPTFOO_RUNNING_IN_DOCKER=true`,
`PYTHONPATH=/app`, `PATH`.

Advanced/testing only: `PROMPTFOO_TARGET_URL` (default `http://127.0.0.1:$PORT/invoke`), `PROMPTFOO_BIN` (override the CLI),
`AZURE_GRADER_PROXY_PORT` (grader proxy, default `8002`).

Derived automatically (do not set): `AZURE_API_KEY`, `AZURE_API_HOST`, `AUDIT_LLM_DEPLOYMENT_NAME`, `AZURE_DEPLOYMENT_NAME`,
`FORCE_COLOR`, `CI`. Proxy variables (`ALL_PROXY`, `HTTP(S)_PROXY`) are stripped inside this container, and `OPENAI_API_KEY`
is only passed to the grader proxy.

---

¹ Without the Azure OpenAI grader, PyRIT cannot score and promptfoo `llm-rubric` assertions error.
² Needed for LLM-driven attacks (PyRIT Crescendo/RedTeaming/MultiTurn; promptfoo red-team generation and jailbreak strategies).
³ Set either the connection string or the account name to switch from local folders to Azure Blob. With an account name,
the Container App identity needs **Storage Blob Data Contributor**. Both containers share the storage account, but each
uses its own data/results containers.
