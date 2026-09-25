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
