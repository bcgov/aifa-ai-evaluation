FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml poetry.lock* /app/
RUN pip install --upgrade pip
RUN pip install poetry || true
RUN poetry export -f requirements.txt --without-hashes -o requirements.txt || true
RUN pip install -r requirements.txt || pip install uvicorn fastapi azure-identity azure-storage-blob

# Install system build tools required by some Python packages (Rust/Cargo for wheels)
RUN apt-get update && apt-get install -y --no-install-recommends \
	build-essential \
	cargo \
	rustc \
 && rm -rf /var/lib/apt/lists/*

# Ensure critical runtime deps are present if export failed. Installing some
# packages explicitly as a fallback; pyrit may require Rust to build native
# extensions which we now provide via apt packages above.
RUN pip install --no-cache-dir pydantic-settings pydantic python-dotenv structlog httpx[socks] click tabulate websockets gunicorn || true
RUN pip install --no-cache-dir pyrit || true
COPY . /app
CMD ["uvicorn", "aifa_pyrit.web_app:app", "--host", "0.0.0.0", "--port", "8011"]
