"""Storage for promptfoo test data and results: local folders by default, Azure Blob when configured.

Azure is enabled by AZURE_STORAGE_CONNECTION_STRING or AZURE_STORAGE_ACCOUNT_NAME (managed identity),
the same credentials as aifa_pyrit, but promptfoo uses its own containers:
  PROMPTFOO_DATA_CONTAINER_NAME     test data     (default: promptfoo-data)
  PROMPTFOO_RESULTS_CONTAINER_NAME  results/configs (default: promptfoo-results)
The promptfoo CLI only reads/writes local files, so the local folders stay the working copy:
test data is pulled from blob before runs, and results/configs are pushed to blob after each job.
"""

from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path
from typing import Any

from fastapi import HTTPException

try:
    from azure.storage.blob import BlobServiceClient
except Exception:  # pragma: no cover - optional dependency
    BlobServiceClient = None

try:
    from azure.identity import DefaultAzureCredential
except Exception:  # pragma: no cover - optional dependency
    DefaultAzureCredential = None

logger = logging.getLogger(__name__)

SAFE_NAME = re.compile(r"^[A-Za-z0-9][\w.-]{0,150}$")
DEFAULT_DATA_CONTAINER = "promptfoo-data"
DEFAULT_RESULTS_CONTAINER = "promptfoo-results"
RESULT_SUBDIRS = ("configs", ".meta")
PULL_INTERVAL_SECONDS = 30


def safe_join(base: Path, name: str) -> Path:
    """Join a user-supplied file name onto base; HTTP 400 on anything that could escape base."""
    if not isinstance(name, str):
        raise HTTPException(status_code=400, detail="Invalid file name.")
    cleaned = os.path.basename(name.replace("\\", "/"))
    if cleaned != name or cleaned in {"", ".", ".."} or ".." in cleaned or not SAFE_NAME.fullmatch(cleaned):
        raise HTTPException(status_code=400, detail="Invalid file name.")
    base_dir = os.path.realpath(base)
    full_path = os.path.realpath(os.path.join(base_dir, cleaned))
    if not full_path.startswith(base_dir + os.sep):
        raise HTTPException(status_code=400, detail="Path traversal attempt detected.")
    return Path(full_path)


def _local_target(base: Path, relative: str, subdirs: tuple[str, ...]) -> Path | None:
    """Map a blob name (relative to its prefix) to a local file, allowing only known subfolders."""
    parts = relative.split("/")
    try:
        if len(parts) == 1:
            return safe_join(base, parts[0])
        if len(parts) == 2 and parts[0] in subdirs:
            folder = base / parts[0]
            folder.mkdir(parents=True, exist_ok=True)
            return safe_join(folder, parts[1])
    except HTTPException:
        pass
    logger.warning("Skipping blob with unsafe name: %s", relative)
    return None


def _container_client(container: str, create: bool) -> Any:
    if BlobServiceClient is None:
        raise RuntimeError("azure-storage-blob is not installed")
    conn = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
    if conn:
        service = BlobServiceClient.from_connection_string(conn)
    else:
        if DefaultAzureCredential is None:
            raise RuntimeError("azure-identity is required for managed identity access")
        account = os.environ["AZURE_STORAGE_ACCOUNT_NAME"]
        service = BlobServiceClient(account_url=f"https://{account}.blob.core.windows.net", credential=DefaultAzureCredential())
    client = service.get_container_client(container)
    if create and not client.exists():
        client.create_container()
    return client


class PromptfooStorage:
    def __init__(self, data_dir: Path, results_dir: Path, data_client: Any = None, results_client: Any = None):
        self.data_dir = data_dir
        self.results_dir = results_dir
        conn = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
        account = os.getenv("AZURE_STORAGE_ACCOUNT_NAME")
        self.results_container = os.getenv("PROMPTFOO_RESULTS_CONTAINER_NAME") or DEFAULT_RESULTS_CONTAINER
        self.data_container = os.getenv("PROMPTFOO_DATA_CONTAINER_NAME") or DEFAULT_DATA_CONTAINER
        self.enabled = bool(conn or account) or results_client is not None
        self._data_client = data_client
        self._results_client = results_client
        self._last_pull = 0.0

    def describe(self) -> dict[str, Any]:
        if not self.enabled:
            return {"mode": "local", "data_dir": str(self.data_dir), "results_dir": str(self.results_dir)}
        return {"mode": "azure", "data_container": self.data_container, "results_container": self.results_container}

    def _results(self) -> Any:
        if self._results_client is None:
            self._results_client = _container_client(self.results_container, create=True)
        return self._results_client

    def _data(self) -> Any:
        if self._data_client is None:
            self._data_client = _container_client(self.data_container, create=True)
        return self._data_client

    def _download(self, client: Any, base: Path, subdirs: tuple[str, ...], overwrite: bool) -> int:
        base.mkdir(parents=True, exist_ok=True)
        count = 0
        for blob in client.list_blobs():
            target = _local_target(base, blob.name, subdirs)
            if target is None or (target.exists() and not overwrite):
                continue
            target.write_bytes(client.get_blob_client(blob.name).download_blob().readall())
            count += 1
        return count

    def pull_data(self) -> None:
        """Refresh local test data from blob; the bundled/local copy stays as fallback."""
        if not self.enabled:
            return
        try:
            count = self._download(self._data(), self.data_dir, (), overwrite=True)
            logger.info("Pulled %d promptfoo data file(s) from container %s", count, self.data_container)
        except Exception:
            logger.exception("Could not pull promptfoo data from Azure; using local %s", self.data_dir)

    def pull_results(self, force: bool = False) -> None:
        """Fetch results/configs written by other replicas or before a restart."""
        if not self.enabled or (not force and time.monotonic() - self._last_pull < PULL_INTERVAL_SECONDS):
            return
        self._last_pull = time.monotonic()
        try:
            self._download(self._results(), self.results_dir, RESULT_SUBDIRS, overwrite=False)
        except Exception:
            logger.exception("Could not pull promptfoo results from Azure; showing local results only")

    def push(self, paths: list[Path]) -> None:
        if not self.enabled:
            return
        root = Path(os.path.realpath(self.results_dir))
        for path in paths:
            try:
                relative = Path(os.path.realpath(path)).relative_to(root).as_posix()
            except ValueError:
                logger.warning("Not uploading %s: outside %s", path, root)
                continue
            try:
                with path.open("rb") as handle:
                    self._results().get_blob_client(relative).upload_blob(handle, overwrite=True)
            except Exception:
                logger.exception("Could not upload %s to Azure; it remains available locally", relative)
