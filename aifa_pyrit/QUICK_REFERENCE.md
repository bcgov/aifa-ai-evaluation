# Quick Reference

This project uses a minimal scorer-first workflow. PyRIT drives the attack execution, while the local scorer in the runtime package flags sensitive or unsafe disclosure. Optional Azure-specific evaluators can be enabled later, but they are not required for the default session.

## Setup

```bash
cd /Users/jatindersingh/Desktop/Projects/AI/project/aifa-ai-evaluation
uv sync --extra dev
```

## Common commands

```bash
# CLI help
uv run red-team --help
./.venv/bin/python -m aifa_pyrit.cli --help

# List available cases
./.venv/bin/python -m aifa_pyrit.cli list-cases

# Run a file-based scan
./.venv/bin/python -m aifa_pyrit.cli scan --use-file -a PromptSending

# Run a single query
./.venv/bin/python -m aifa_pyrit.cli test-query -q "What is the application fee?" -a Crescendo

# Seed attack data
./.venv/bin/python -m aifa_pyrit.cli seed-attack -d "violence,harassment,scams"
```

## Run the web app

```bash
./.venv/bin/python -m uvicorn aifa_pyrit.web_app:app --host 0.0.0.0 --port 8011 --reload=false
```

Then open:

```text
http://localhost:8011
```

## File conventions

- `pyproject.toml` stays at the repo root.
- `aifa_pyrit/.env` is the runtime env file used by the package settings loader.
- `aifa_pyrit/.env.example` is the template for local secrets.
- `data/red_team_test_cases.json` is the default case source.

## Typical workflows

### CLI only

```bash
./.venv/bin/python -m aifa_pyrit.cli list-cases
./.venv/bin/python -m aifa_pyrit.cli scan --use-file -a PromptSending
```

### Browser workflow

```bash
./.venv/bin/python -m uvicorn aifa_pyrit.web_app:app --host 0.0.0.0 --port 8011 --reload=false
```

### Optional extras

If you decide to add Azure-specific evaluators later, enable them deliberately through the settings instead of treating them as part of the default flow.

## Troubleshooting

- Use `./.venv/bin/python` or `uv run` instead of a system Python when the repo venv is not active.
- If imports fail, make sure you are in the repo root and not under an old `src/` or `pyrit/` folder.
- If the CLI cannot find test data, verify that `data/red_team_test_cases.json` exists.
