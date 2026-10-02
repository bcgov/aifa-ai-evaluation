"""Promptfoo-compatible wrapper for the Azure-backed backend.

This module intentionally sits inside the evaluation project and wraps the repo's
real WebSocket-backed backend behind a simple HTTP-like contract that Promptfoo
can call as a standard HTTP provider.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Callable, Dict, Optional

import httpx
import websockets

try:
    from promptfoo.src.config import settings
except ModuleNotFoundError:  # pragma: no cover - fallback for local subproject execution
    from src.config import settings

INVOKE_PATH = "/invoke"


def normalize_backend_base_url(raw_url: str) -> str:
    """Normalize WebSocket endpoint values to the backend's HTTP invoke base."""
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


def to_websocket_url(raw_url: str) -> str:
    """Convert a backend URL or websocket target into a valid ws/wss URL."""
    value = (raw_url or "").strip().rstrip("/")
    if not value:
        return value

    lowered = value.lower()
    if lowered.startswith("wss://") or lowered.startswith("ws://"):
        return value
    if lowered.startswith("https://"):
        return "wss://" + value[8:]
    if lowered.startswith("http://"):
        return "ws://" + value[7:]
    return value


class PromptfooHttpWrapper:
    """Bridge Promptfoo HTTP requests to the live WebSocket backend."""

    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        timeout: Optional[int] = None,
        client_factory: Optional[Callable[..., httpx.AsyncClient]] = None,
    ):
        raw_url = base_url or settings.backend_api_url
        self.base_url = normalize_backend_base_url(raw_url)
        self.origin = "https://train.j200.gov.bc.ca"
        self.timeout = timeout or settings.backend_api_timeout
        self.websocket_url = to_websocket_url(raw_url)
        if not self.websocket_url.endswith("/ws"):
            self.websocket_url = self.websocket_url.rstrip("/") + "/ws"

        factory = client_factory or (lambda **kwargs: httpx.AsyncClient(**kwargs))
        self.client = factory(base_url=self.base_url, timeout=self.timeout)

    def build_payload(self, *, query: str, step_number: Optional[str] = None) -> Dict[str, Any]:
        payload = {
            "client_id": settings.backend_client_id,
            "query": query,
            "application_id": settings.backend_application_id,
        }
        if step_number:
            payload["step_number"] = step_number
        elif settings.backend_step_number:
            payload["step_number"] = settings.backend_step_number
        return payload

    @staticmethod
    def extract_output(response: Any) -> str:
        if isinstance(response, str):
            return response

        if isinstance(response, list):
            for item in response:
                candidate = PromptfooHttpWrapper.extract_output(item)
                if candidate and candidate not in {"{}", "[]"}:
                    return candidate
            return json.dumps(response, ensure_ascii=False)

        if isinstance(response, dict):
            for key in ("response_message", "message", "answer", "content", "text"):
                if key in response and response[key] not in (None, ""):
                    value = response[key]
                    if isinstance(value, str):
                        return value
                    if isinstance(value, list):
                        for item in value:
                            candidate = PromptfooHttpWrapper.extract_output(item)
                            if candidate and candidate not in {"{}", "[]"}:
                                return candidate
                    return json.dumps(value, ensure_ascii=False)

            if "response" in response:
                value = response["response"]
                if isinstance(value, str):
                    return value
                if isinstance(value, list):
                    for item in value:
                        candidate = PromptfooHttpWrapper.extract_output(item)
                        if candidate and candidate not in {"{}", "[]"}:
                            return candidate
                    return json.dumps(value, ensure_ascii=False)
                if isinstance(value, dict):
                    candidate = PromptfooHttpWrapper.extract_output(value)
                    if candidate and candidate not in {"{}", "[]"}:
                        return candidate
                return json.dumps(value, ensure_ascii=False)

            for value in response.values():
                if isinstance(value, (dict, list)):
                    candidate = PromptfooHttpWrapper.extract_output(value)
                    if candidate and candidate not in {"{}", "[]"}:
                        return candidate
            return ""

        return str(response)

    async def invoke(self, *, query: str, step_number: Optional[str] = None) -> Dict[str, Any]:
        payload = self.build_payload(query=query, step_number=step_number)
        session_id = payload.get("session_id") or "promptfoo-session"
        payload["session_id"] = session_id

        async with websockets.connect(
            self.websocket_url,
            additional_headers={"Origin": self.origin},
            open_timeout=self.timeout,
        ) as websocket:
            await websocket.send(json.dumps(payload))
            for _ in range(10):
                raw_message = await asyncio.wait_for(websocket.recv(), timeout=self.timeout)
                data = json.loads(raw_message)
                if isinstance(data, dict) and data.get("event") == "session_init":
                    continue
                if isinstance(data, dict) and "response" in data:
                    return data
                if isinstance(data, dict) and "error" in data:
                    return {
                        "response": [{"source": "error", "response": str(data["error"])}],
                        "session_id": data.get("session_id", session_id),
                    }

        return {
            "response": [{"source": "error", "response": "INFRA_ERROR::NO_FINAL_RESPONSE"}],
            "session_id": session_id,
        }

    async def close(self):
        await self.client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
