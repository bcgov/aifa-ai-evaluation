"""Shared Azure AI Search helpers for local apps and evaluations.

This module is intentionally lightweight and reusable across the project. It
normalizes Azure AI Search service endpoints and exposes a minimal client for
retrieving the top relevant chunks from an index.
"""

from __future__ import annotations

import os
from typing import Any, Iterable
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient


def normalize_search_endpoint(endpoint: str | None) -> str:
    """Return the Azure AI Search service root without the index/search path.

    Accepts endpoints such as:
      - https://resource.search.windows.net
      - https://resource.search.windows.net/indexes/my-index/docs/search?api-version=...
    and returns the clean service root.
    """
    if not endpoint:
        return ""

    value = endpoint.strip().rstrip("/")
    if not value:
        return ""

    parsed = urlparse(value)
    if not parsed.scheme or not parsed.netloc:
        return value

    # If the URL is already a service root, keep it as-is.
    if parsed.path in ("", "/"):
        return value

    # Strip /indexes/<name>/docs/search or any similar search path.
    path_parts = [part for part in parsed.path.split("/") if part]
    if len(path_parts) >= 3 and path_parts[0] == "indexes":
        cleaned = urlunparse(
            (
                parsed.scheme,
                parsed.netloc,
                "",
                "",
                "",
                "",
            )
        )
        return cleaned

    # If a custom path was passed, preserve the host but remove the path.
    return urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))


class SharedSearchClient:
    """Thin Azure AI Search wrapper for retrieving relevant chunks."""

    def __init__(
        self,
        endpoint: str | None = None,
        api_key: str | None = None,
        index_name: str | None = None,
        *,
        top: int = 5,
        query_type: str = "simple",
    ) -> None:
        self.endpoint = normalize_search_endpoint(endpoint or os.getenv("AZURE_SEARCH_ENDPOINT", ""))
        self.api_key = api_key or os.getenv("AZURE_SEARCH_API_KEY", "")
        self.index_name = index_name or os.getenv("AZURE_SEARCH_INDEX_NAME", "")
        self.top = int(top or 5)
        self.query_type = query_type or "simple"

        if not self.endpoint or not self.api_key or not self.index_name:
            raise ValueError(
                "Azure AI Search requires AZURE_SEARCH_ENDPOINT, AZURE_SEARCH_API_KEY, and AZURE_SEARCH_INDEX_NAME."
            )

        self.client = SearchClient(
            endpoint=self.endpoint,
            index_name=self.index_name,
            credential=AzureKeyCredential(self.api_key),
        )

    def search(self, query: str, *, top: int | None = None) -> list[dict[str, Any]]:
        """Return the top matches as JSON-serializable dictionaries."""
        results: list[dict[str, Any]] = []
        search_kwargs: dict[str, Any] = {"top": top or self.top, "query_type": self.query_type}
        for item in self.client.search(search_text=query, **search_kwargs):
            if isinstance(item, dict):
                results.append(dict(item))
            else:
                results.append({"content": str(item)})
        return results

    def search_text(self, query: str, *, top: int | None = None) -> str:
        """Return concatenated search text for evaluation and prompt contexts."""
        hits = self.search(query, top=top)
        if not hits:
            return ""

        chunks: list[str] = []
        for item in hits:
            for key in ("content", "text", "chunk", "content_text", "body"):
                value = item.get(key)
                if value:
                    chunks.append(str(value))
                    break
            else:
                chunks.append(str(item))
        return "\n\n".join(chunks)


def build_search_context(query: str, *, endpoint: str | None = None, api_key: str | None = None, index_name: str | None = None, top: int = 5) -> str:
    """Convenience helper for shared retrieval from any app."""
    client = SharedSearchClient(endpoint=endpoint, api_key=api_key, index_name=index_name, top=top)
    return client.search_text(query)
