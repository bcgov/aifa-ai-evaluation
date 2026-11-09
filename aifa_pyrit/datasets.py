from __future__ import annotations

import json
import logging
import os
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Any

from aifa_pyrit.storage import BlobServiceClient, DefaultAzureCredential, pyrit_data_container

logger = logging.getLogger(__name__)
DATA_DIR = Path(__file__).resolve().parents[1] / "data"
DEFAULT_DATASET_ID = "saved-test-cases"


class DatasetUnavailableError(RuntimeError):
    pass


def _azure_configured() -> bool:
    return bool(os.getenv("AZURE_STORAGE_CONNECTION_STRING") or os.getenv("AZURE_STORAGE_ACCOUNT_NAME"))


@contextmanager
def _container():
    if BlobServiceClient is None:
        raise DatasetUnavailableError("Azure Blob Storage SDK is unavailable.")
    connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
    if connection_string:
        with BlobServiceClient.from_connection_string(connection_string) as service:
            yield service.get_container_client(pyrit_data_container())
    else:
        if DefaultAzureCredential is None:
            raise DatasetUnavailableError("Azure Identity SDK is unavailable.")
        with (
            DefaultAzureCredential() as credential,
            BlobServiceClient(
                account_url=f"https://{os.environ['AZURE_STORAGE_ACCOUNT_NAME']}.blob.core.windows.net",
                credential=credential,
            ) as service,
        ):
            yield service.get_container_client(pyrit_data_container())


def _cases(content: str | bytes) -> list[dict[str, Any]]:
    payload = json.loads(content)
    cases = payload.get("test_cases") if isinstance(payload, dict) else None
    if not isinstance(cases, list) or not cases:
        raise ValueError("Dataset must contain a nonempty test_cases array.")
    names = set()
    for case in cases:
        if not isinstance(case, dict) or any(
            not isinstance(case.get(field), str) or not case[field].strip() for field in ("name", "query")
        ):
            raise ValueError("Each test case must have a nonempty name and query.")
        if case["name"] in names:
            raise ValueError("Dataset contains duplicate case names.")
        names.add(case["name"])
    return cases


def list_datasets() -> list[dict[str, Any]]:
    datasets = []

    def include(name: str, content: str | bytes, source: str) -> None:
        try:
            cases = _cases(content)
        except ValueError:
            logger.warning("Skipping invalid test-case dataset: %s", name)
            return
        datasets.append({"id": f"{source}:{name}", "name": name, "case_count": len(cases), "source": source})

    if _azure_configured():
        try:
            with _container() as container:
                for blob in container.list_blobs():
                    if blob.name.endswith(".json"):
                        include(blob.name, container.download_blob(blob.name).readall(), "azure")
        except Exception as exc:
            logger.exception("Unable to list PyRIT datasets in container %s", pyrit_data_container())
            raise DatasetUnavailableError("Cannot read PyRIT datasets from Blob Storage. Check storage configuration, permissions, and networking.") from exc
    else:
        for path in sorted(DATA_DIR.glob("*.json")):
            include(path.name, path.read_bytes(), "local")
    return sorted(datasets, key=lambda dataset: dataset["name"])


def load_dataset(dataset_id: str) -> list[dict[str, Any]]:
    source = "azure" if _azure_configured() else "local"
    if dataset_id == DEFAULT_DATASET_ID:
        dataset_id = f"{source}:red_team_test_cases.json"
    prefix, separator, name = dataset_id.partition(":")
    path = PurePosixPath(name)
    if not separator or prefix != source or not name.endswith(".json") or path.is_absolute() or ".." in path.parts or "\\" in name:
        raise ValueError("Unknown dataset.")
    if source == "local":
        if len(path.parts) != 1:
            raise ValueError("Unknown dataset.")
        return _cases((DATA_DIR / name).read_bytes())
    try:
        with _container() as container:
            return _cases(container.download_blob(name).readall())
    except ValueError:
        raise
    except Exception as exc:
        from azure.core.exceptions import ResourceNotFoundError

        if isinstance(exc, ResourceNotFoundError):
            raise FileNotFoundError(name) from exc
        logger.exception("Unable to load PyRIT dataset: %s", name)
        raise DatasetUnavailableError("Cannot read the selected Blob dataset. Check storage configuration, permissions, and networking.") from exc