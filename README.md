# AI evaluation workspace

This project evaluates an AI Form Assist application that communicates with a hosted WebSocket API endpoint. It is designed around the real Water Permitting workflow as the first use case, using a custom wrapper to send prompts to the AIFA application and then evaluate the responses.

The project is intentionally single-tenant for the current scenario, with the prompts and runtime assumptions tuned to that environment. Water Permitting is the initial domain focus, and the same evaluation pattern can be extended to other business use cases later. The core red-team flow stays focused on PyRIT, Promptfoo and DeepEval.

## Core model

- The default runtime uses PyRIT for the red-team flow.
- The project uses a custom wrapper to call the hosted AI Form Assist application instead of a generic local inference path.
- Report output is stored under the repo-root [results](results) directory for both CLI and browser runs.
- Promptfoo and DeepEval are optional extras and are not required for the main evaluation path.

## Setup

```bash
cd /Users/jatindersingh/Desktop/Projects/AI/project/aifa-ai-evaluation
uv sync --extra dev
```

## Common commands

```bash
# CLI help
./.venv/bin/python -m aifa_pyrit.cli --help
# or
uv run red-team --help

# List cases
./.venv/bin/python -m aifa_pyrit.cli list-cases

# Run a file-based scan
./.venv/bin/python -m aifa_pyrit.cli scan --use-file -a PromptSending

# Run a single query
./.venv/bin/python -m aifa_pyrit.cli test-query -q "What is the application fee?" -a Crescendo

# Seed attack content
./.venv/bin/python -m aifa_pyrit.cli seed-attack -d "violence,harassment,scams"
```

## Browser/web app

```bash
./.venv/bin/python -m uvicorn aifa_pyrit.web_app:app --host 0.0.0.0 --port 8011
```

Open:

```text
http://localhost:8011
```

## Azure App Service deployment

This repository is designed for a Python App Service deployment pattern rather than a container-based deployment. The app is exposed through the FastAPI service in [aifa_pyrit/web_app.py](aifa_pyrit/web_app.py), and the runtime expects the repo-root [results](results) directory to exist for JSON reports.

Key deployment requirements:

- use a Linux Python App Service
- run the app with `gunicorn` and expose port `8000` via `WEBSITES_PORT`
- keep runtime settings in environment variables such as `BACKEND_API_URL`, `AZURE_OPENAI_*`, and `ADVERSARIAL_OPENAI_*`
- keep the repo-root `.env` or App Service app settings aligned with the same config names used by [aifa_pyrit/config.py](aifa_pyrit/config.py)

Example deployment commands:

```bash
cd infra
terraform init
terraform plan
terraform apply
```

The workflow in [.github/workflows/deploy-to-dev.yml](.github/workflows/deploy-to-dev.yml) calls the reusable deployment stack under [.github/workflows/.deploy_stack.yml](.github/workflows/.deploy_stack.yml), which performs Azure login, Terraform provisioning, and a zip deploy of the app package.

## Optional extras

Framework-specific work remains isolated in [promptfoo](promptfoo) so the main red-team package stays lightweight and predictable. Use those directories only when you need the extra evaluation path.

For Promptfoo evaluation, run the eval first and then open the native Promptfoo browser UI:

```bash
cd /Users/jatindersingh/Desktop/Projects/AI/project/aifa-ai-evaluation/promptfoo
./run_promptfoo_eval.sh
npx promptfoo view -p 15500 -y
```

The raw JSON export remains under [results](results), but the preferred viewer for Promptfoo reports is the native `promptfoo view` UI rather than the PyRIT frontend.

## Conventions

- [pyproject.toml](pyproject.toml) remains at the repo root for the main package.
- runtime configuration stays under [aifa_pyrit](aifa_pyrit)
- generated reports stay in [results](results)
- avoid stale `src/`, `red_team/`, or legacy package references
