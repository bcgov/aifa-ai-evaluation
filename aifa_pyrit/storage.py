from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from azure.storage.blob import BlobServiceClient
except Exception:  # pragma: no cover - optional dependency
    BlobServiceClient = None


class ReportStore(ABC):
    @abstractmethod
    def save_report(self, payload: dict[str, Any], filename: str | None = None) -> str:
        raise NotImplementedError

    @abstractmethod
    def get_report(self, filename: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def list_reports(self) -> list[dict[str, Any]]:
        raise NotImplementedError


class LocalReportStore(ReportStore):
    def __init__(self, base_dir: str | Path | None = None):
        self.base_dir = Path(base_dir or Path(__file__).resolve().parents[1] / "results")
        self.base_dir.mkdir(exist_ok=True, parents=True)

    def save_report(self, payload: dict[str, Any], filename: str | None = None) -> str:
        if filename is None:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            filename = f"report_{timestamp}.json"
        full_path = self.base_dir / filename
        with full_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, default=str)
        return str(full_path.resolve())

    def get_report(self, filename: str) -> dict[str, Any]:
        path = self.base_dir / filename
        if not path.exists():
            raise FileNotFoundError(filename)
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def list_reports(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for path in sorted(self.base_dir.glob("*.json"), reverse=True):
            try:
                payload = self.get_report(path.name)
                items.append({
                    "name": path.name,
                    "updated_at": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
                    "summary": payload.get("summary", {}) if isinstance(payload, dict) else {},
                    "size": path.stat().st_size,
                })
            except Exception:
                items.append({
                    "name": path.name,
                    "updated_at": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
                    "summary": {"status": "unreadable"},
                    "size": path.stat().st_size,
                })
        return items


class AzureBlobReportStore(ReportStore):
    def __init__(self, connection_string: str | None = None, container_name: str | None = None):
        if BlobServiceClient is None:
            raise RuntimeError("azure-storage-blob is not installed")

        self.connection_string = connection_string or os.getenv("AZURE_STORAGE_CONNECTION_STRING", "")
        self.container_name = container_name or os.getenv("AZURE_STORAGE_CONTAINER_NAME", "aifa-reports")
        if not self.connection_string:
            raise ValueError("AZURE_STORAGE_CONNECTION_STRING is required")

        self.client = BlobServiceClient.from_connection_string(self.connection_string)
        container_client = self.client.get_container_client(self.container_name)
        container_client.create_container(exist_ok=True)
        self.container_client = container_client

    def save_report(self, payload: dict[str, Any], filename: str | None = None) -> str:
        if filename is None:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            filename = f"report_{timestamp}.json"
        content = json.dumps(payload, indent=2, default=str).encode("utf-8")
        blob = self.container_client.get_blob_client(filename)
        blob.upload_blob(content, overwrite=True)
        return f"azure://{self.container_name}/{filename}"

    def get_report(self, filename: str) -> dict[str, Any]:
        blob = self.container_client.get_blob_client(filename)
        data = blob.download_blob().readall()
        return json.loads(data.decode("utf-8"))

    def list_reports(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for blob in self.container_client.list_blobs():
            items.append({
                "name": blob.name,
                "updated_at": blob.last_modified.isoformat() if getattr(blob, "last_modified", None) else datetime.now(timezone.utc).isoformat(),
                "summary": {},
                "size": blob.size,
            })
        return items


def get_report_store() -> ReportStore:
    conn = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
    container = os.getenv("AZURE_STORAGE_CONTAINER_NAME")
    if conn and container:
        try:
            return AzureBlobReportStore(connection_string=conn, container_name=container)
        except Exception:
            pass
    return LocalReportStore()
