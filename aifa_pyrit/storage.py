from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import logging

try:
    from azure.storage.blob import BlobServiceClient
except Exception:  # pragma: no cover - optional dependency
    BlobServiceClient = None

# Optional Managed Identity support
try:
    from azure.identity import DefaultAzureCredential
except Exception:  # pragma: no cover - optional dependency
    DefaultAzureCredential = None

logger = logging.getLogger(__name__)


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
        # Prefer connection string when provided. If absent, attempt Managed Identity
        self.use_managed_identity = False
        if not self.connection_string:
            if DefaultAzureCredential is not None:
                # Expect account name env var when using Managed Identity
                account_name = os.getenv("AZURE_STORAGE_ACCOUNT_NAME")
                if not account_name:
                    logger.error("AzureBlobReportStore init failed: missing AZURE_STORAGE_ACCOUNT_NAME for Managed Identity")
                    raise ValueError("AZURE_STORAGE_ACCOUNT_NAME is required when AZURE_STORAGE_CONNECTION_STRING is not set")
                self.account_url = f"https://{account_name}.blob.core.windows.net"
                self.use_managed_identity = True
            else:
                logger.error("AzureBlobReportStore init failed: missing connection string and azure-identity not installed")
                raise ValueError("AZURE_STORAGE_CONNECTION_STRING is required or install azure-identity and set AZURE_STORAGE_ACCOUNT_NAME for Managed Identity")

        try:
            if self.use_managed_identity:
                logger.info("Initializing BlobServiceClient with Managed Identity account_url=%s", self.account_url)
                cred = DefaultAzureCredential()
                self.client = BlobServiceClient(account_url=self.account_url, credential=cred)
            else:
                self.client = BlobServiceClient.from_connection_string(self.connection_string)
            container_client = self.client.get_container_client(self.container_name)
            try:
                container_client.create_container()
            except Exception as exc:
                # Prefer to ignore 'container already exists' errors when possible.
                try:
                    from azure.core.exceptions import ResourceExistsError

                    if isinstance(exc, ResourceExistsError):
                        logger.debug("Container already exists: %s", self.container_name)
                    else:
                        raise
                except Exception:
                    # Fallback: inspect message/status for 409 / already exists and ignore
                    msg = str(exc)
                    if "ContainerAlreadyExists" in msg or "already exists" in msg or getattr(getattr(exc, 'status_code', None), '__int__', lambda: None) == 409:
                        logger.debug("Container already exists (fallback): %s", self.container_name)
                    else:
                        logger.exception("AzureBlobReportStore failed to create container: %s", exc)
                        raise

            self.container_client = container_client
        except Exception as exc:
            logger.exception("AzureBlobReportStore failed to initialize: %s", exc)
            raise

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
    account = os.getenv("AZURE_STORAGE_ACCOUNT_NAME")
    container = os.getenv("AZURE_STORAGE_CONTAINER_NAME")
    logger.debug("get_report_store: AZURE_STORAGE_CONNECTION_STRING present=%s, AZURE_STORAGE_ACCOUNT_NAME=%s, AZURE_STORAGE_CONTAINER_NAME=%s", bool(conn), account, container)
    # Use Azure storage when either a connection string + container is provided
    # or when account name + container are provided for Managed Identity.
    if (conn and container) or (account and container):
        try:
            if conn:
                store = AzureBlobReportStore(connection_string=conn, container_name=container)
            else:
                store = AzureBlobReportStore(connection_string=None, container_name=container)
            logger.info("Using AzureBlobReportStore container=%s", container)
            return store
        except Exception as exc:
            logger.exception("Failed to create AzureBlobReportStore, falling back to LocalReportStore: %s", exc)
    logger.info("Using LocalReportStore")
    return LocalReportStore()
