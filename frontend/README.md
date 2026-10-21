# Frontend

Static single-page UI (plain HTML, CSS and ES modules, no build step) for both evaluation products. Pages: **New Run**, **Live Run**, **Export** (PyRIT) and **Run tests**, **Results** (Promptfoo). `classic.html` is the older single-page PyRIT view.

## Run locally

The PyRIT web app serves this folder, so there is nothing to build:

```bash
uv run python -m uvicorn aifa_pyrit.web_app:app --port 8011      # http://localhost:8011
```

PyRIT pages work immediately. The Promptfoo pages need the promptfoo service on `:8001` ([../promptfoo/README.md](../promptfoo/README.md)); the app forwards `/api/promptfoo/*` there (`PROMPTFOO_SERVICE_URL` to change it). After editing JS or CSS, hard-reload the page.

## Run with nginx (Docker)

```bash
docker compose up --build frontend     # from the repo root; starts backend and promptfoo too
# UI at http://localhost:8080
```

Or build the image alone:

```bash
docker build -t aifa-frontend frontend
docker run --rm -p 8080:80 -e PYRIT_UPSTREAM=host.docker.internal:8011 -e PROMPTFOO_UPSTREAM=host.docker.internal:8001 aifa-frontend
```

nginx ([nginx.conf](nginx.conf)) serves the files and proxies `/api/promptfoo/*` to the promptfoo container and `/api/*` to PyRIT; `/healthz` is the health check.

| Variable | Default | Purpose |
|---|---|---|
| `PYRIT_UPSTREAM` | `127.0.0.1:8000` | Where `/api/*` goes (Compose: `backend:8000`) |
| `PROMPTFOO_UPSTREAM` | `127.0.0.1:8001` | Where `/api/promptfoo/*` goes (Compose: `promptfoo:8001`) |
| `PROMPTFOO_RUN_TOKEN` | empty | Sent as `X-Run-Token`; must match the promptfoo container |

In Azure all three containers share one network namespace, so the defaults apply.

## Layout

- `index.html`, `css/`, `js/`: pages and one module per page (`new-run.js`, `live-run.js`, `export.js`, `pf-commands.js`, `pf-run.js`, `pf-results.js`); `app.js` is the hash router (`#/new`, `#/live/<id>`, `#/pf-commands`, `#/pf-run/<job>`, `#/pf-results/<name>`)
- `api.js`, `promptfoo-api.js`: the only places that call the backends
- `config.js.template`: rendered to `config.js` at container start
