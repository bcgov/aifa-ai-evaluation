#!/usr/bin/env python3
"""Shared Azure/OpenAI-compatible LLM request helper.

This is the single request path used by local Python callers and optional Node-based
wrappers. It accepts either a classic Azure OpenAI endpoint or a Foundry-style
https://<resource>.services.ai.azure.com/openai/v1 endpoint and sends the correct
request shape automatically.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any
from urllib.parse import urlparse

import httpx


def _endpoint_hostname(endpoint: str) -> str:
    if not endpoint:
        return ""
    parsed = urlparse(endpoint.strip())
    return (parsed.hostname or "").lower()


def normalize_endpoint(endpoint: str) -> str:
    value = (endpoint or "").strip().rstrip("/")
    if not value:
        return value
    lowered = value.lower()
    for suffix in ("/openai/v1", "/openai"):
        if lowered.endswith(suffix):
            return value[: -len(suffix)]
    return value


def is_foundry_endpoint(endpoint: str) -> bool:
    value = (endpoint or "").strip()
    if not value:
        return False

    parsed = urlparse(value)
    hostname = (parsed.hostname or "").lower()
    path = (parsed.path or "").lower()

    if hostname == "services.ai.azure.com" or hostname.endswith(".services.ai.azure.com"):
        return True
    if hostname and hostname.endswith(".openai.azure.com"):
        return False
    return "/openai/v1" in path and bool(hostname)


def build_chat_completion_url(endpoint: str, deployment: str, api_version: str) -> str:
    base = normalize_endpoint(endpoint)
    if not base or not deployment:
        return base
    if is_foundry_endpoint(endpoint):
        return f"{base}/openai/v1/chat/completions"
    return f"{base}/openai/deployments/{deployment}/chat/completions?api-version={api_version}"


def build_chat_request_headers(api_key: str, endpoint: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if is_foundry_endpoint(endpoint):
        headers["Authorization"] = f"Bearer {api_key}"
        return headers
    headers["api-key"] = api_key
    return headers


def build_message_payload(messages: list[dict[str, Any]] | None, deployment: str, endpoint: str) -> dict[str, Any]:
    payload = {"messages": messages or []}
    if is_foundry_endpoint(endpoint):
        payload["model"] = deployment
    return payload


def send_chat_completion(
    endpoint: str,
    api_key: str,
    deployment: str,
    api_version: str,
    messages: list[dict[str, Any]],
    *,
    max_completion_tokens: int | None = None,
    reasoning_effort: str | None = None,
    timeout: int = 60,
) -> tuple[int, dict[str, Any] | None, str]:
    if not endpoint:
        raise ValueError("endpoint is required")
    if not api_key:
        raise ValueError("api_key is required")
    if not messages:
        raise ValueError("messages are required")

    url = build_chat_completion_url(endpoint, deployment, api_version)
    headers = build_chat_request_headers(api_key, endpoint)
    payload = build_message_payload(messages, deployment, endpoint)
    if max_completion_tokens is not None:
        payload["max_completion_tokens"] = max_completion_tokens
    if reasoning_effort:
        payload["reasoning_effort"] = reasoning_effort

    with httpx.Client(timeout=httpx.Timeout(timeout), trust_env=True) as client:
        response = client.post(url, headers=headers, json=payload)
    try:
        body = response.json()
    except ValueError:
        body = None
    return response.status_code, body, response.text


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send a chat completion through the shared Azure/OpenAI-compatible client.")
    parser.add_argument("--endpoint", required=True, help="Azure OpenAI or Foundry endpoint")
    parser.add_argument("--api-key", required=True, help="API key or bearer token")
    parser.add_argument("--deployment", required=True, help="Deployment/model name")
    parser.add_argument("--api-version", default="2025-01-01-preview")
    parser.add_argument("--message", action="append", default=[], help="User prompt; may be repeated")
    parser.add_argument("--json-output", action="store_true", help="Emit JSON only")
    parser.add_argument("--max-completion-tokens", type=int, default=None)
    parser.add_argument("--reasoning-effort", default=None)
    parser.add_argument("--timeout", type=int, default=60)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    messages = [{"role": "user", "content": msg} for msg in args.message]
    if not messages:
        messages = [{"role": "user", "content": os.environ.get("LLM_PROMPT", "hello")}]

    try:
        status, payload, raw = send_chat_completion(
            args.endpoint,
            args.api_key,
            args.deployment,
            args.api_version,
            messages,
            max_completion_tokens=args.max_completion_tokens,
            reasoning_effort=args.reasoning_effort,
            timeout=args.timeout,
        )
    except Exception as exc:  # pragma: no cover - CLI-level failure path
        print(str(exc), file=sys.stderr)
        return 1

    if status != 200:
        print(raw, file=sys.stderr)
        return status

    if args.json_output:
        print(json.dumps(payload or {}, ensure_ascii=False))
    else:
        output = payload or {}
        choices = output.get("choices") or []
        if choices:
            msg = choices[0].get("message") or {}
            content = msg.get("content") or ""
            print(content)
        else:
            print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
