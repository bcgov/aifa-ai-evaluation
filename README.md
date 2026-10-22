# AI evaluation workspace

Red-team and quality evaluation for the **AI Form Assist (AIFA)** water-licence assistant. It sends test prompts to the hosted AIFA WebSocket API and scores the answers.

| Product | What it does | Docs |
|---|---|---|
| **PyRIT** (`aifa_pyrit/`) | Adversarial attacks (jailbreaks, prompt injection, multi-turn) with scoring; CLI + FastAPI | [aifa_pyrit/README.md](aifa_pyrit/README.md) |
| **Promptfoo** (`promptfoo/`) | Quality eval of curated test cases, graded by a judge model | [promptfoo/README.md](promptfoo/README.md) |
| **Frontend** (`frontend/`) | Browser UI for both (static files behind nginx) | [frontend/README.md](frontend/README.md) |
| **Infra** (`infra/aca/`, `.github/workflows/`) | Terraform + GitHub Actions release to Azure Container Apps | [infra/README.md](infra/README.md) |

```mermaid
flowchart LR
  user(["Browser"])

  subgraph aca["Azure Container App (one network namespace)"]
    direction LR
    fe["frontend<br/>nginx :80<br/>public ingress"]
    py["pyrit<br/>FastAPI :8000"]
    subgraph pfc["promptfoo container"]
      pf["promptfoo service<br/>FastAPI :8001"]
      gr["judge proxy<br/>:8002"]
    end
    fe -- "/api/*" --> py
    fe -- "/api/promptfoo/*" --> pf
    pf -- "/grade" --> gr
  end

  aifa[("AIFA backend<br/>WebSocket")]
  llm[("Azure OpenAI<br/>judge and attacker models")]
  blob[("Azure Blob<br/>reports and test data")]

  user -- HTTPS --> fe
  py -- "attack prompts" --> aifa
  pf -- "test prompts" --> aifa
  py -- "score and attack" --> llm
  gr -- "grade answers" --> llm
  py --> blob
  pf --> blob
```

Other folders: `data/` (PyRIT test cases), `data_promptfoo/` (Promptfoo test cases), `results/` and `results-promptfoo/` (reports), `docs/` (proxy and registry notes), [env-inventory.md](env-inventory.md) (every environment variable per container).

## Prerequisites

Python 3.11+, [uv](https://docs.astral.sh/uv/), Node.js 22+, Docker (for Compose), and for releases the Azure CLI and GitHub CLI.

## 1. Configure

```bash
uv sync --extra dev
cp aifa_pyrit/.env.example aifa_pyrit/.env      # PyRIT settings
cp promptfoo/.env.example promptfoo/.env        # Promptfoo settings
```

Fill in the AIFA backend URL (`BACKEND_API_URL`, a `wss://…/ws` endpoint), the judge model (`AUDIT_LLM_*`) and, for LLM attacks, `ADVERSARIAL_OPENAI_*`. Never commit `.env` files.

## 2. Run locally with the shared launcher

The easiest supported path is the repo launcher, which loads the proxy settings and starts the whole local stack:

```bash
./scripts/start_app_with_proxy.sh --check
./scripts/start_app_with_proxy.sh
```

This starts:

- PyRIT web app: http://localhost:8011
- Promptfoo service: http://localhost:8001
- Promptfoo judge proxy: http://localhost:8002

Health checks:

```bash
curl http://127.0.0.1:8011/api/health
curl http://127.0.0.1:8001/api/promptfoo/info
curl http://127.0.0.1:8002/health
```

If your Azure judge endpoint is private-only, export the proxy chain before starting the app:

```bash
export PROMPTFOO_USE_PRIVATE_PROXY=1
export HTTP_PROXY=http://127.0.0.1:8118
export HTTPS_PROXY=http://127.0.0.1:8118
export ALL_PROXY=http://127.0.0.1:8118
export NO_PROXY=localhost,127.0.0.1,::1
./scripts/start_app_with_proxy.sh
```

## 3. Run individual pieces manually

### PyRIT CLI

```bash
uv run red-team --help
uv run red-team list-cases
uv run red-team scan --use-file -a PromptSending
```

### PyRIT web app only

```bash
uv run python -m uvicorn aifa_pyrit.web_app:app --host 127.0.0.1 --port 8011
```

### Promptfoo only

```bash
cd promptfoo
uv sync && npm ci
OPENAI_API_KEY="${AUDIT_LLM_API_KEY:-}" node azure-grader-proxy.js
promptfoo/.venv/bin/python -m uvicorn promptfoo.src.promptfoo_service:app --host 127.0.0.1 --port 8001
```

## 4. Run with Docker Compose

This mirrors production and exposes the frontend at http://localhost:8080:

```bash
docker compose up --build
docker compose logs -f
docker compose down
```

Useful checks:

```bash
curl http://localhost:8080
curl http://localhost:8011/api/health
curl http://localhost:8001/api/promptfoo/info
```

Compose reads the repo `.env` files and keeps the app, promptfoo service, and front-end together in one networking setup.

## 4. Production release (Azure Container Apps)

One Container App runs the three containers; only the frontend has public ingress. Details and variables: [infra/README.md](infra/README.md).

```mermaid
flowchart LR
  dev(["Push or PR"]) --> gha["GitHub Actions<br/>Deploy to ACA"]
  gha --> build["Build images<br/>pyrit, frontend, promptfoo"]
  build --> ghcr[("GHCR<br/>latest, sha-commit, run-n")]
  gha --> plan["terraform plan"]
  manual(["Run workflow<br/>plan or apply"]) --> gha
  manual -- "apply" --> apply["terraform apply<br/>OIDC login"]
  ghcr --> apply
  apply --> app["Azure Container App<br/>image tag run-n"]
  app --> verify{{"Verify<br/>/healthz and /api/health"}}
```

**One-time setup:** run [initial-azure-setup.sh](initial-azure-setup.sh) to create the GitHub OIDC identity and Terraform state storage, add the identity to the Azure contributor group, then set the secrets and variables in the GitHub `dev` environment.

**Release:**

1. Push your branch or open a PR. *Deploy to ACA* builds the three images, pushes them to GHCR (`latest`, `sha-<commit>`, `run-<n>`) and runs `terraform plan`.
2. GitHub → Actions → **Deploy to ACA** → Run workflow → `plan`, review, then run again with `apply`.
3. Verify using the `container_app_url` output: `/healthz`, `/api/health`, `/api/promptfoo/info`.

**Rollback:** re-run the `apply` workflow run of the last good release; it redeploys that run's image tag.

## Troubleshooting

- **404 on `/api/promptfoo/*` locally:** the promptfoo service on `:8001` is not running or is stale; restart it.
- **UI shows old behavior:** hard-reload (`Cmd/Ctrl+Shift+R`); the browser caches scripts.
- **Judge returns 404:** `AUDIT_LLM_ENDPOINT` must serve `/openai/deployments/<deployment>/chat/completions`. Check with `promptfoo/test_grader_no_proxy.sh`.
- **Azure calls hang locally:** unset `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY` unless you need the tunnel ([docs/proxy-connection-guide.md](docs/proxy-connection-guide.md)).
- **Where did my reports go:** `results/` (PyRIT) and `results-promptfoo/` locally; Blob containers when `AZURE_STORAGE_CONNECTION_STRING` is set.
