# Promptfoo cheat sheet

This folder is a separate Promptfoo subproject for evaluation work. Keep the main red-team package in [../aifa_pyrit](../aifa_pyrit) and use this folder for Promptfoo-specific execution only.

## 1) Quick setup

```bash
cd /Users/jatindersingh/Desktop/Projects/AI/project/aifa-ai-evaluation/promptfoo
uv sync
cp .env.example .env
```

Then edit the local `.env` file with the values needed for your environment.

## 2) Run the eval

```bash
cd /Users/jatindersingh/Desktop/Projects/AI/project/aifa-ai-evaluation/promptfoo
./run_promptfoo_eval.sh
```

This is the supported script for the framework-local evaluation flow.

## 3) Open the native Promptfoo viewer

After the eval, open the built-in Promptfoo browser UI instead of the PyRIT frontend for Promptfoo-specific results:

```bash
cd /Users/jatindersingh/Desktop/Projects/AI/project/aifa-ai-evaluation/promptfoo
npx promptfoo view -p 15500 -y
```

You can also run it without auto-opening:

```bash
npx promptfoo view -p 15500
```

The raw JSON export is still written to the repo-root results folder, but the recommended visual report is the native `promptfoo view` interface.

## 4) Repo rules

- Use the repo root for the main red-team CLI and browser app.
- Use [promptfoo](.) for Promptfoo evaluation only.
- Keep framework-specific env and config files in this folder.
- Avoid stale repo references like `evaluation/promptfoo`, `nr-ai-form`, or old `src` layouts.

## 5) Folder map

- [promptfoo-config.yaml](promptfoo-config.yaml) — Promptfoo config
- [run_promptfoo_eval.sh](run_promptfoo_eval.sh) — runner script
- [.env.example](.env.example) — env template
- [src](src) — adapter/wrapper implementation

## 6) Typical commands

```bash
cd promptfoo
uv sync
./run_promptfoo_eval.sh
```

If you want the root-level project docs, see [../README.md](../README.md) and [../QUICK_REFERENCE.md](../QUICK_REFERENCE.md).
