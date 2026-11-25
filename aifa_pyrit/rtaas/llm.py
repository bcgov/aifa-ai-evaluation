"""One Azure OpenAI chat client for the ladder judge and the DeepEval metrics.

Uses the same contract the deployed container uses (api-key header, plus a `model` field for
Foundry v1 endpoints). The judge endpoint is private, so these calls only succeed from inside
the VNet (the deployed app or the jumpbox).
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
from typing import Any, Optional

import httpx

from aifa_pyrit.config import build_chat_completion_url, build_chat_request_body, build_chat_request_headers

os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")

from deepeval.models import DeepEvalBaseLLM  # noqa: E402

RETRIES = 3


def judge_config() -> dict[str, str]:
    from aifa_pyrit.evaluators.uat_judge import _cfg

    return _cfg()


def configured() -> bool:
    c = judge_config()
    return bool(c.get("endpoint") and c.get("key") and c.get("deployment"))


def _request(messages: list[dict[str, str]], max_tokens: int) -> tuple[str, dict[str, str], dict[str, Any]]:
    c = judge_config()
    url = build_chat_completion_url(c["endpoint"], c["deployment"], c["version"])
    body = build_chat_request_body(c["endpoint"], c["deployment"], messages, max_completion_tokens=max_tokens)
    return url, build_chat_request_headers(c["key"], c["endpoint"]), body


def _content(resp: httpx.Response) -> str:
    return resp.json()["choices"][0]["message"]["content"] or ""


def _retryable(resp: httpx.Response) -> bool:
    return resp.status_code == 429 or resp.status_code >= 500


def chat(messages: list[dict[str, str]], max_tokens: int = 1500, timeout: int = 120) -> str:
    url, headers, body = _request(messages, max_tokens)
    err = ""
    for attempt in range(RETRIES):
        try:
            resp = httpx.post(url, json=body, headers=headers, timeout=timeout, trust_env=True)
            if resp.status_code == 200:
                return _content(resp)
            err = f"HTTP {resp.status_code}: {resp.text[:200]}"
            if not _retryable(resp):
                break
        except httpx.HTTPError as exc:
            err = str(exc)
        time.sleep(min(2 ** (attempt + 1), 20))
    raise RuntimeError(f"judge LLM call failed: {err}")


async def achat(messages: list[dict[str, str]], max_tokens: int = 1500, timeout: int = 120) -> str:
    url, headers, body = _request(messages, max_tokens)
    err = ""
    async with httpx.AsyncClient(trust_env=True, timeout=timeout) as client:
        for attempt in range(RETRIES):
            try:
                resp = await client.post(url, json=body, headers=headers)
                if resp.status_code == 200:
                    return _content(resp)
                err = f"HTTP {resp.status_code}: {resp.text[:200]}"
                if not _retryable(resp):
                    break
            except httpx.HTTPError as exc:
                err = str(exc)
            await asyncio.sleep(min(2 ** (attempt + 1), 20))
    raise RuntimeError(f"judge LLM call failed: {err}")


def parse_json(text: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        raise ValueError(f"no JSON object in judge reply: {text[:150]!r}")
    return json.loads(match.group())


class AzureJudgeLLM(DeepEvalBaseLLM):
    """DeepEval custom model backed by `chat()`. Returns a schema instance when DeepEval asks for one."""

    def __init__(self, max_tokens: int = 2000):
        self.max_tokens = max_tokens
        super().__init__(model=judge_config().get("deployment") or "judge")

    def load_model(self, *args, **kwargs) -> "AzureJudgeLLM":
        return self

    def _shape(self, text: str, schema: Optional[type] = None) -> Any:
        if schema is None:
            return text
        try:
            return schema.model_validate(parse_json(text))
        except Exception:  # let DeepEval's own JSON repair have a go
            return text

    def generate(self, prompt: str, schema: Optional[type] = None, **kwargs: Any) -> Any:
        return self._shape(chat([{"role": "user", "content": prompt}], self.max_tokens), schema)

    async def a_generate(self, prompt: str, schema: Optional[type] = None, **kwargs: Any) -> Any:
        return self._shape(await achat([{"role": "user", "content": prompt}], self.max_tokens), schema)

    def get_model_name(self, *args, **kwargs) -> str:
        return f"azure:{self.name}"
