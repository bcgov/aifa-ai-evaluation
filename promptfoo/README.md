# Promptfoo evaluation

This subfolder is kept separate from the main red-team package in [../aifa_pyrit](../aifa_pyrit), but it still follows the repo’s shared structure:

- test data comes from [../data_promptfoo](../data_promptfoo)
- evaluation output is written to the repo-root [../results](../results) directory
- Promptfoo-specific config and wrapper code remain inside this folder

## Prerequisites

- Node.js 22+
- Python 3.11+
- Repo environment installed at the project root

```bash
cd /Users/jatindersingh/Desktop/Projects/AI/project/aifa-ai-evaluation/promptfoo
node --version
npx promptfoo --version
```

## Configure environment

```bash
cd /Users/jatindersingh/Desktop/Projects/AI/project/aifa-ai-evaluation/promptfoo
cp .env.example .env
```

Update the values so they match your backend and Azure settings. The evaluation uses the shared repo data contract and writes reports to the main results folder.

## Run the evaluation

From inside the Promptfoo folder:

```bash
cd /Users/jatindersingh/Desktop/Projects/AI/project/aifa-ai-evaluation/promptfoo
./run_promptfoo_eval.sh
```

Or from the repo root:

```bash
cd /Users/jatindersingh/Desktop/Projects/AI/project/aifa-ai-evaluation
./promptfoo/run_promptfoo_eval.sh
```

The generated report is stored at [../results/promptfoo-report.json](../results/promptfoo-report.json).

## View results in the native Promptfoo UI

Use the built-in Promptfoo browser UI instead of the PyRIT frontend for Promptfoo-specific reports:

```bash
cd /Users/jatindersingh/Desktop/Projects/AI/project/aifa-ai-evaluation/promptfoo
npx promptfoo view -p 15500 -y
```

This launches the native Promptfoo view in the browser. If you want to keep it simple without auto-opening, run:

```bash
npx promptfoo view -p 15500
```

The viewer reads the eval data produced by Promptfoo and is the preferred way to inspect Promptfoo results. The repo-root results JSON is still kept as the raw export for scripts and automation.

## Files involved

- [promptfoo-config.yaml](promptfoo-config.yaml) — Promptfoo config and shared data path
- [run_promptfoo_eval.sh](run_promptfoo_eval.sh) — launches the local adapter and writes to the main results directory
- [../data_promptfoo/promptfoo_tests_cases.yaml](../data_promptfoo/promptfoo_tests_cases.yaml) — source test cases
- [src](src) — adapter and wrapper code used by the eval

## Notes

- Do not use stale `datasets/` references or old root-level output paths.
- The main package should continue to use the repo-root [../results](../results) directory for generated artifacts.
- This Promptfoo flow is optional; the primary red-team path remains the repo-root package in [../aifa_pyrit](../aifa_pyrit).
