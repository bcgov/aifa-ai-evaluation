# AI evaluation workspace

This project evaluates an AI Form Assist application that communicates with a hosted WebSocket API endpoint. It is designed around the real Water Permitting workflow as the first use case, using a custom wrapper to send prompts to the AIFA application and then evaluate the responses.

The project is intentionally single-tenant for the current scenario, with the prompts and runtime assumptions tuned to that environment. Water Permitting is the initial domain focus, and the same evaluation pattern can be extended to other business use cases later. The core red-team flow stays focused on PyRIT, while optional frameworks such as Promptfoo and DeepEval remain separate and non-blocking extras.

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

## Optional extras

Framework-specific work remains isolated in [promptfoo](promptfoo) so the main red-team package stays lightweight and predictable. Use those directories only when you need the extra evaluation path.

## Conventions

- [pyproject.toml](pyproject.toml) remains at the repo root for the main package.
- runtime configuration stays under [aifa_pyrit](aifa_pyrit)
- generated reports stay in [results](results)
- avoid stale `src/`, `red_team/`, or legacy package references
