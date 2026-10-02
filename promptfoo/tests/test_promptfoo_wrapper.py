import json

import httpx
import pytest

from promptfoo.src.promptfoo_wrapper import normalize_backend_base_url, PromptfooHttpWrapper


def test_normalize_backend_base_url_from_websocket():
    assert normalize_backend_base_url("wss://example.com/ws") == "https://example.com"
    assert normalize_backend_base_url("ws://example.com/ws") == "http://example.com"


def test_wrapper_builds_backend_invoke_payload():
    wrapper = PromptfooHttpWrapper(base_url="https://example.com")
    payload = wrapper.build_payload(query="What is the fee?", step_number="step2-Eligibility")

    assert payload["query"] == "What is the fee?"
    assert payload["step_number"] == "step2-Eligibility"
    assert payload["client_id"] == "11111111-1111-4111-8111-111111111111"
    assert payload["application_id"] == 234554


@pytest.mark.asyncio
async def test_wrapper_extracts_eval_response():
    response = {
        "response": [{"source": "Aggregator", "response": "The application fee is $100."}],
        "session_id": "abc-123",
    }
    assert PromptfooHttpWrapper.extract_output(response) == "The application fee is $100."


@pytest.mark.asyncio
async def test_wrapper_invoke_uses_websocket_backend(monkeypatch):
    class FakeSocket:
        def __init__(self):
            self.sent = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def send(self, payload):
            self.sent.append(payload)

        async def recv(self):
            return json.dumps({
                "event": "session_init",
                "session_id": "abc-123",
            })

    class FakeSocketFactory:
        def __init__(self):
            self.socket = FakeSocket()

        async def __call__(self, *args, **kwargs):
            return self.socket

    socket = FakeSocket()

    class FakeWebSocketContext:
        def __init__(self):
            self.sent = []
            self.messages = [
                json.dumps({"event": "session_init", "session_id": "abc-123"}),
                json.dumps({
                    "response": [{"source": "Aggregator", "response": "The application fee is $100."}],
                    "session_id": "abc-123",
                }),
            ]

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def send(self, payload):
            self.sent.append(payload)

        async def recv(self):
            if not self.messages:
                raise asyncio.TimeoutError()
            return self.messages.pop(0)

    monkeypatch.setattr("promptfoo.src.promptfoo_wrapper.websockets.connect", lambda *args, **kwargs: FakeWebSocketContext())

    wrapper = PromptfooHttpWrapper(base_url="wss://example.com/ws")
    result = await wrapper.invoke(query="What is the fee?")
    assert result["response"][0]["response"] == "The application fee is $100."


def test_wrapper_extracts_live_backend_response_from_list_items():
    payload = {
        "response": [
            {"thread_id": "client:session-123"},
            {
                "source": "Aggregator",
                "response": "I can help answer questions related to water licences.",
                "category": "unrelated_topic",
            },
        ],
        "session_id": "session-123",
    }

    assert (
        PromptfooHttpWrapper.extract_output(payload)
        == "I can help answer questions related to water licences."
    )
