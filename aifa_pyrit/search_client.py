"""Azure AI Search client for retrieval.

This module remains backwards-compatible with the rest of the project while reusing
an app-shared search helper for common access patterns.
"""

import logging
from typing import Optional

from aifa_pyrit.config import settings
from shared.search_client import SharedSearchClient

logger = logging.getLogger(__name__)


class AzureSearchContextRetriever:
    """Backward-compatible search wrapper around the shared Azure Search utility."""

    def __init__(
        self,
        endpoint: Optional[str] = None,
        api_key: Optional[str] = None,
        index_name: Optional[str] = None,
    ):
        self.endpoint = endpoint or settings.azure_search_endpoint
        self.api_key = api_key or settings.azure_search_api_key
        self.index_name = index_name or settings.azure_search_index_name

        self.top = settings.azure_search_top
        self.trim_length = settings.azure_search_trim_length
        self.enable_trimming = settings.azure_search_enable_trimming
        self.include_total_count = settings.azure_search_include_total_count
        self.query_type = settings.azure_search_query_type

        if not self.endpoint or not self.api_key or not self.index_name:
            raise ValueError(
                "Azure Search configuration missing: endpoint, api_key, and index_name are required"
            )

        self.client = SharedSearchClient(
            endpoint=self.endpoint,
            api_key=self.api_key,
            index_name=self.index_name,
            top=self.top,
            query_type=self.query_type,
        )
        logger.info(
            "Search retriever initialized - endpoint: %s, index: %s, query_type: %s",
            self.endpoint,
            self.index_name,
            self.query_type,
        )

    def retrieve_context(self, query: str) -> str:
        """Return the search result text for a query."""
        text = self.client.search_text(query, top=self.top)
        if not text:
            return "No results found."
        if self.enable_trimming:
            return text[: self.trim_length]
        return text
