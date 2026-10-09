from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from aifa_pyrit import web_app


def test_missing_cases_do_not_silently_run_fee_question(monkeypatch):
    monkeypatch.setattr(web_app.RedTeamOrchestrator, "load_test_cases", lambda: [])
    with pytest.raises(HTTPException) as error:
        web_app._load_cases()
    assert error.value.status_code == 400


def test_unknown_case_filter_does_not_run_other_cases(monkeypatch):
    monkeypatch.setattr(web_app.RedTeamOrchestrator, "load_test_cases", lambda: [{"name": "known", "query": "hi"}])
    with pytest.raises(HTTPException) as error:
        web_app._load_cases("known,typo")
    assert error.value.status_code == 400


def test_undetermined_is_not_attack_success():
    summary = web_app._summarize_report({"results": {"turns": [{"outcome": "AttackOutcome.UNDETERMINED"}]}})
    assert summary["successful_turns"] == 0
    assert summary["unscored_turns"] == 1
    assert summary["completed_turns"] == 1
    assert summary["security_verdict"] == "not_assessed"


def test_failed_case_without_turns_is_an_error():
    summary = web_app._summarize_report({"results": [{"error": "converter unavailable"}]})
    assert summary["status"] == "error"
    assert summary["error_count"] == 1
    assert summary["successful_turns"] == 0


def test_backend_transport_error_is_not_completed():
    summary = web_app._summarize_report({"results": {"turns": [{
        "outcome": "AttackOutcome.UNDETERMINED", "transport_error": True,
    }]}})
    assert summary["status"] == "error"
    assert summary["completed_turns"] == 0


@pytest.mark.asyncio
async def test_custom_query_is_forwarded_and_expectation_recorded(monkeypatch):
    runner = MagicMock()
    runner.converter_names = ["base64"]
    runner.results = {"results": []}
    runner.scan_test_cases = AsyncMock(return_value=[])
    monkeypatch.setattr(web_app, "PyRITRunner", MagicMock(return_value=runner))
    saved = []
    monkeypatch.setattr(web_app, "_save_report", lambda report, filename: saved.append(report) or Path(filename))
    request = web_app.RunScanRequest(
        use_file=False, query="Explain application eligibility.",
        expected_behavior="Answer only from published licensing guidance.", converters=["base64"],
    )
    await web_app.run_scan(request)
    cases = runner.scan_test_cases.call_args.args[0]
    assert cases[0]["query"] == request.query
    assert saved[0]["expected_behavior"] == request.expected_behavior


@pytest.mark.asyncio
async def test_custom_query_cannot_be_empty(monkeypatch):
    monkeypatch.setattr(web_app, "PyRITRunner", MagicMock())
    with pytest.raises(HTTPException) as error:
        await web_app.run_scan(web_app.RunScanRequest(use_file=False))
    assert error.value.status_code == 400
