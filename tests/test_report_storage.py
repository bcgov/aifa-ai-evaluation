import json
from pathlib import Path

from aifa_pyrit.storage import LocalReportStore, get_report_store


def test_local_report_store_round_trip(tmp_path):
    store = LocalReportStore(base_dir=tmp_path)
    payload = {"status": "ok", "message": "hello"}

    saved = store.save_report(payload, "demo_report.json")
    assert Path(saved).exists()

    listed = store.list_reports()
    assert any(item["name"] == "demo_report.json" for item in listed)

    loaded = store.get_report("demo_report.json")
    assert loaded["status"] == "ok"
    assert loaded["message"] == "hello"


def test_get_report_store_defaults_to_local_when_storage_is_not_configured(monkeypatch):
    monkeypatch.delenv("AZURE_STORAGE_CONNECTION_STRING", raising=False)
    monkeypatch.delenv("AZURE_STORAGE_ACCOUNT_NAME", raising=False)
    monkeypatch.delenv("AZURE_STORAGE_ACCOUNT_KEY", raising=False)
    monkeypatch.delenv("AZURE_STORAGE_CONTAINER_NAME", raising=False)

    store = get_report_store()
    assert isinstance(store, LocalReportStore)
    assert store.base_dir.name == "results"


def test_pyrit_container_names_are_separate_from_promptfoo(monkeypatch):
    from aifa_pyrit.storage import pyrit_data_container, pyrit_results_container
    from promptfoo.src.storage import DEFAULT_DATA_CONTAINER, DEFAULT_RESULTS_CONTAINER

    for var in ("PYRIT_RESULTS_CONTAINER_NAME", "PYRIT_DATA_CONTAINER_NAME",
                "AZURE_STORAGE_CONTAINER_NAME", "AZURE_TESTCASES_CONTAINER_NAME"):
        monkeypatch.delenv(var, raising=False)
    names = {pyrit_results_container(), pyrit_data_container(), DEFAULT_DATA_CONTAINER, DEFAULT_RESULTS_CONTAINER}
    assert names == {"pyrit-results", "pyrit-data", "promptfoo-data", "promptfoo-results"}

    monkeypatch.setenv("AZURE_STORAGE_CONTAINER_NAME", "aifa-reports")
    assert pyrit_results_container() == "aifa-reports"
    monkeypatch.setenv("PYRIT_RESULTS_CONTAINER_NAME", "pyrit-results-dev")
    assert pyrit_results_container() == "pyrit-results-dev"
