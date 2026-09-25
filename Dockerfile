FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

COPY pyproject.toml README.md ./
COPY aifa_pyrit ./aifa_pyrit
COPY data ./data
COPY results ./results

RUN python -m pip install --upgrade pip && \
    python -m pip install . && \
    mkdir -p /app/results

EXPOSE 8000

CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--timeout", "180", "--workers", "2", "aifa_pyrit.web_app:app"]
