# Browser UI for Red Team scans

This folder contains the frontend for the project browser workflow. The canonical app entry is `aifa_pyrit.web_app`, and the recommended startup command is run from the repo root.

## Run it

```bash
cd /Users/jatindersingh/Desktop/Projects/AI/project/aifa-ai-evaluation
./.venv/bin/python -m uvicorn aifa_pyrit.web_app:app --host 0.0.0.0 --port 8011 --reload=false
```

Then open:

```text
http://localhost:8011
```

If the venv is active, this also works:

```bash
python -m aifa_pyrit.web_app
```

## Features

- Launch scan runs from the browser form
- Use PyRIT attack types and seed datasets
- View saved JSON reports from the dashboard
- Reuse the same report folder as the CLI workflow

## Notes

- Do not use stale commands like `cd evaluation` or `python -m pyrit.web_app`.
- Prefer the repo-root startup commands in `README.md` and `QUICK_REFERENCE.md`.
