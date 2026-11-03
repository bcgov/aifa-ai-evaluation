"""Backend API client."""

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx

from aifa_pyrit.config import settings
from aifa_pyrit.logging_utils import setup_logger

logger = setup_logger("aifa_pyrit.client", log_dir=os.getenv("APP_LOG_DIR"))
INVOKE_PATH = "/invoke"


def normalize_backend_base_url(raw_url: str) -> str:
    """Normalize websocket endpoints to HTTP POST endpoints used by the hosted app /invoke API."""
    value = (raw_url or "").strip().rstrip("/")
    if not value:
        return value

    lowered = value.lower()
    if lowered.startswith("wss://"):
        value = "https://" + value[6:]
    elif lowered.startswith("ws://"):
        value = "http://" + value[5:]

    if value.lower().endswith("/ws"):
        value = value[:-3]
    if value.lower().endswith("/invoke"):
        value = value[:-7]
    return value


class BackendClient:
    """Client for backend API."""

    def __init__(self, base_url: Optional[str] = None, timeout: Optional[int] = None):
        raw_url = normalize_backend_base_url(base_url or settings.backend_api_url)
        parsed = urlparse(raw_url)
        self.invoke_path = INVOKE_PATH
        self.base_url = raw_url.replace(INVOKE_PATH, "") if parsed.path.endswith(INVOKE_PATH) else raw_url
        self.timeout = timeout or settings.backend_api_timeout
        self.client = httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout)

    async def health_check(self) -> bool:
        """Check backend health."""
        try:
            response = await self.client.get("/health")
            return response.status_code == 200
        except Exception:
            logger.exception("health_check_failed")
            return False

    async def invoke(self, *, query: str, step_number: Optional[str] = None) -> Dict[str, Any]:
        """Call backend invoke endpoint."""
        payload = {"query": query}
        if step_number:
            payload["step_number"] = step_number
        url = f"{self.base_url}{self.invoke_path}"
        started_at = time.perf_counter()

        logger.info(
            "backend_invoke_start url=%s payload=%s timeout_seconds=%s",
            url,
            payload,
            self.timeout,
        )

        try:
            resp = await self.client.post(self.invoke_path, json=payload)
            elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
            logger.info(
                "backend_invoke_response_received url=%s status_code=%s elapsed_ms=%s response_preview=%s",
                url,
                resp.status_code,
                elapsed_ms,
                resp.text[:2000],
            )
            resp.raise_for_status()
            response = resp.json()
            logger.info(
                "backend_invoke_success url=%s elapsed_ms=%s response_keys=%s",
                url,
                elapsed_ms,
                sorted(response.keys()) if isinstance(response, dict) else type(response).__name__,
            )
            return response
        except httpx.HTTPStatusError as exc:
            elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
            response_text = exc.response.text[:2000] if exc.response is not None else ""
            logger.exception(
                "backend_invoke_http_error url=%s status_code=%s elapsed_ms=%s response_preview=%s payload=%s",
                url,
                exc.response.status_code if exc.response is not None else None,
                elapsed_ms,
                response_text,
                payload,
            )
            raise
        except Exception:
            elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
            logger.exception(
                "backend_invoke_failed url=%s elapsed_ms=%s payload=%s",
                url,
                elapsed_ms,
                payload,
            )
            raise

    def get_sample_cases(self) -> List[Dict[str, Any]]:
        """Load test cases from JSON file."""
        try:
            file = Path(__file__).parent / "../data/test_cases.json"
            if not file.exists():
                logger.warning("test_cases_not_found")
                return []
            data = json.load(open(file))
            cases = data.get("test_cases", [])
            logger.info("cases_loaded", count=len(cases))
            return cases
        except Exception:
            logger.exception("load_test_cases_failed")
            return []

    async def close(self):
        """Close client."""
        await self.client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

