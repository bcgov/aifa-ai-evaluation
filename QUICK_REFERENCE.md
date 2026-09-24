# Quick Reference

This repo is the main red-team evaluation package for the AI Form Assist app. The browser workflow and CLI workflow both use the package under [aifa_pyrit](aifa_pyrit), and all attack results are written to the project-root [results](results) directory.

## Setup

```bash
cd /Users/jatindersingh/Desktop/Projects/AI/project/aifa-ai-evaluation
uv sync --extra dev
```

## CLI commands

```bash
# CLI help
./.venv/bin/python -m aifa_pyrit.cli --help
# or
uv run red-team --help

# List available cases
./.venv/bin/python -m aifa_pyrit.cli list-cases

# Run a file-based scan
./.venv/bin/python -m aifa_pyrit.cli scan --use-file -a PromptSending

# Run a single query
./.venv/bin/python -m aifa_pyrit.cli test-query -q "What is the application fee?" -a Crescendo

# Seed attack data
./.venv/bin/python -m aifa_pyrit.cli seed-attack -d "violence,harassment,scams"
```

## Browser/web app

```bash
./.venv/bin/python -m uvicorn aifa_pyrit.web_app:app --host 0.0.0.0 --port 8011
```

Then open:

```text
http://localhost:8011
```

The web API exposes report snapshots from [results](results), including the generated JSON files for Crescendo, MultiTurn, and scan runs.

## Optional extras

```bash
cd promptfoo
uv sync
cp .env.example .env
./run_promptfoo_eval.sh
```

## File conventions

- [pyproject.toml](pyproject.toml) stays at the repo root for the main package.
- runtime configuration lives under [aifa_pyrit](aifa_pyrit)
- generated reports live in [results](results)
- optional Promptfoo work stays in its own folder and is not required for the core red-team flow

## Troubleshooting

- Use `./.venv/bin/python` or `uv run` instead of a system Python when the repo venv is not active.
- Keep commands anchored to the repo root for the main package.
- Do not use stale paths like `src/`, old `red_team/`, or old project-name references.
