import base64
import codecs
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from aifa_pyrit.converters import (
    available_converters,
    build_converter_config,
    needs_llm,
    normalize_converter_names,
)
from aifa_pyrit.pyrit_runner import PyRITRunner


def test_available_converters():
    converters = available_converters()
    assert "base64" in converters
    assert "rot13" in converters
    assert "leetspeak" in converters
    assert "morse" in converters
    assert "ascii_smuggler" in converters
    assert "translation" in converters


def test_normalize_converter_names():
    assert normalize_converter_names([" Base64 ", "ROT13"]) == ["base64", "rot13"]
    assert normalize_converter_names(None) == []
    assert normalize_converter_names([]) == []
    assert normalize_converter_names(["translation:french"]) == ["translation:french"]

    with pytest.raises(ValueError, match="Unknown converter"):
        normalize_converter_names(["invalid_converter"])


def test_needs_llm():
    assert needs_llm(["translation"]) is True
    assert needs_llm(["translation:spanish"]) is True
    assert needs_llm(["base64", "rot13"]) is False
    assert needs_llm([]) is False
    assert needs_llm(None) is False


def test_build_converter_config_empty():
    assert build_converter_config(None) is None
    assert build_converter_config([]) is None


def test_build_converter_config_non_llm():
    config = build_converter_config(["base64", "rot13", "leetspeak", "morse", "ascii_smuggler"])
    assert config is not None


def test_build_converter_config_translation():
    with pytest.raises(ValueError, match="needs an LLM target"):
        build_converter_config(["translation"])

    mock_target = MagicMock()
    config = build_converter_config(["translation:spanish"], converter_target=mock_target)
    assert config is not None


def test_llm_converter_error_text_raises_instead_of_being_sent():
    import asyncio
    from types import SimpleNamespace

    from aifa_pyrit.converters import ConverterFailedError, _fail_on_llm_error

    async def failing(**kwargs):
        return SimpleNamespace(output_text="Azure OpenAI request was blocked by private-endpoint/network policy")

    async def working(**kwargs):
        return SimpleNamespace(output_text="Quelle est la taxe ?")

    bad = _fail_on_llm_error(SimpleNamespace(convert_async=failing), "translation:french")
    good = _fail_on_llm_error(SimpleNamespace(convert_async=working), "translation:french")

    with pytest.raises(ConverterFailedError):
        asyncio.run(bad.convert_async(prompt="hi"))
    assert asyncio.run(good.convert_async(prompt="hi")).output_text == "Quelle est la taxe ?"


def test_pyrit_runner_converter_integration():
    runner = PyRITRunner(converters=["base64", "rot13"])
    assert runner.converter_names == ["base64", "rot13"]

    kwargs = runner._converter_kwargs()
    assert "attack_converter_config" in kwargs
    assert kwargs["attack_converter_config"] is not None


def test_pyrit_runner_no_converters():
    runner = PyRITRunner()
    assert runner.converter_names == []
    assert runner._converter_kwargs() == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(("names", "expected"), [
    ([], "hi"),
    (["base64"], base64.b64encode(b"hi").decode()),
    (["rot13"], codecs.encode("hi", "rot_13")),
    (["morse"], ".... .."),
    (["ascii_smuggler"], "".join(chr(0xE0000 + ord(c)) for c in "hi")),
    (["leetspeak"], None),
    (["base64", "rot13"], codecs.encode(base64.b64encode(b"hi").decode(), "rot_13")),
])
async def test_real_converter_chain_reaches_websocket_and_report(monkeypatch, names, expected):
    from pyrit.setup import initialize_pyrit_async
    from aifa_pyrit import custom_backend_target, pyrit_runner

    async def initialize():
        await initialize_pyrit_async(memory_db_type="InMemory")

    websocket = AsyncMock()
    websocket.recv.return_value = json.dumps({"response": [{"response": "Offline test reply"}]})
    monkeypatch.setattr(custom_backend_target.websockets, "connect", AsyncMock(return_value=websocket))
    monkeypatch.setattr(pyrit_runner.settings, "backend_api_url", "ws://127.0.0.1:9999/ws")
    runner = PyRITRunner(converters=names)
    monkeypatch.setattr(runner, "initialize_pyrit", initialize)
    monkeypatch.setattr(runner, "_set_pyrit_env", lambda: None)
    monkeypatch.setattr(runner, "save_result_payload", MagicMock())
    monkeypatch.setattr(runner, "_create_adversarial_target", MagicMock(side_effect=AssertionError("Unexpected LLM call")))

    result = await runner.run_attack("hi")

    assert "error" not in result, result.get("error")
    websocket.send.assert_awaited_once()
    sent = json.loads(websocket.send.call_args.args[0])["query"]
    if expected is not None:
        assert sent == expected
    else:
        assert sent and sent != "hi"
    turn = result["results"]["turns"][0]
    assert turn["original_prompt"] == "hi"
    assert turn["prompt"] == sent
    assert turn["response"] == "Offline test reply"
    assert result["converters"] == names


@pytest.mark.asyncio
async def test_translation_http_failure_never_reaches_backend(monkeypatch):
    import httpx
    from pyrit.setup import initialize_pyrit_async
    from aifa_pyrit import custom_azure_openai_target, custom_backend_target, pyrit_runner

    await initialize_pyrit_async(memory_db_type="InMemory")
    azure = custom_azure_openai_target.CustomAzureOpenAITarget(
        endpoint="https://test.invalid", api_key="test-only", deployment="test",
    )
    client = AsyncMock()
    client.post.return_value = httpx.Response(403, json={"error": {"code": "403", "message": "Public access is disabled"}})
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=client)
    context.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(custom_azure_openai_target.httpx, "AsyncClient", MagicMock(return_value=context))
    connect = AsyncMock(side_effect=AssertionError("Failed translation must not reach backend"))
    monkeypatch.setattr(custom_backend_target.websockets, "connect", connect)
    monkeypatch.setattr(pyrit_runner.settings, "backend_api_url", "ws://127.0.0.1:9999/ws")
    runner = PyRITRunner(converters=["translation:french"])
    monkeypatch.setattr(runner, "initialize_pyrit", AsyncMock())
    monkeypatch.setattr(runner, "_set_pyrit_env", lambda: None)
    monkeypatch.setattr(runner, "_create_adversarial_target", lambda: azure)
    monkeypatch.setattr(runner, "save_result_payload", MagicMock())
    result = await runner.run_attack("hi")
    assert "403" in result["error"]
    connect.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [
    (403, {"error": {"code": "403", "message": "Public access is disabled"}}),
    (500, {"error": {"message": "Unavailable"}}),
    (200, {"choices": [{"message": {"content": None}}]}),
])
async def test_azure_failures_raise_instead_of_returning_assistant_text(monkeypatch, response):
    import httpx
    from pyrit.models import Message
    from pyrit.setup import initialize_pyrit_async
    from aifa_pyrit import custom_azure_openai_target as module

    await initialize_pyrit_async(memory_db_type="InMemory")
    target = module.CustomAzureOpenAITarget(endpoint="https://test.invalid", api_key="test-only")
    client = AsyncMock()
    client.post.return_value = httpx.Response(response[0], json=response[1])
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=client)
    context.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(module.httpx, "AsyncClient", MagicMock(return_value=context))
    with pytest.raises(RuntimeError):
        await target._send_prompt_to_target_async(normalized_conversation=[Message.from_prompt(prompt="hi", role="user")])
