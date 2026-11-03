"""Configuration management for evaluation application."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from urllib.parse import urlparse

from pydantic import AliasChoices, Field

# pydantic-settings is an optional runtime dependency in some environments.
# Try to import it, but fall back to using pydantic.BaseModel as a minimal
# compatibility shim so the app can start even if the package isn't installed.
try:
    from pydantic_settings import BaseSettings, SettingsConfigDict  # type: ignore
except Exception:
    from pydantic import BaseModel as BaseSettings

    class SettingsConfigDict(dict):
        pass


def _endpoint_hostname(endpoint: str) -> str:
    if not endpoint:
        return ""
    parsed = urlparse(endpoint.strip())
    host = parsed.hostname or ""
    return host.lower()


def normalize_audit_llm_endpoint(endpoint: str) -> str:
    """Normalize Azure OpenAI resource URLs to the base resource root.

    Azure resources are commonly configured as either:
    - https://resource.openai.azure.com
    - https://resource.openai.azure.com/openai/v1
    - https://resource.services.ai.azure.com/openai/v1

    The REST endpoint used by the custom target needs the resource root, while PyRIT's
    OpenAIChatTarget expects the /openai/v1 form. This helper strips any trailing
    /openai or /openai/v1 suffix so callers can consistently build the correct URLs.
    """
    if not endpoint:
        return endpoint

    value = endpoint.strip().rstrip("/")
    lowered = value.lower()
    for suffix in ("/openai/v1", "/openai"):
        if lowered.endswith(suffix):
            return value[: -len(suffix)]
    return value


def is_foundry_openai_endpoint(endpoint: str) -> bool:
    """True for Azure AI Foundry OpenAI-compatible service endpoints."""
    value = (endpoint or "").strip()
    if not value:
        return False

    parsed = urlparse(value)
    hostname = (parsed.hostname or "").lower()
    path = (parsed.path or "").lower()

    if hostname == "services.ai.azure.com" or hostname.endswith(".services.ai.azure.com"):
        return True
    if hostname and hostname.endswith(".openai.azure.com"):
        return False
    return "/openai/v1" in path and bool(hostname)


def build_chat_completion_url(endpoint: str, deployment: str, api_version: str) -> str:
    """Return the full chat-completions URL for either legacy Azure OpenAI or Foundry endpoints."""
    base = normalize_audit_llm_endpoint(endpoint)
    if not base or not deployment:
        return base
    if is_foundry_openai_endpoint(endpoint):
        return f"{base.rstrip('/')}/openai/v1/chat/completions"
    return f"{base.rstrip('/')}/openai/deployments/{deployment}/chat/completions?api-version={api_version}"


def build_chat_request_headers(api_key: str, endpoint: str) -> dict[str, str]:
    """Return the correct auth headers for the configured endpoint contract."""
    sanitized_api_key = (api_key or "").strip()
    headers = {"Content-Type": "application/json"}
    if is_foundry_openai_endpoint(endpoint):
        headers["Authorization"] = f"Bearer {sanitized_api_key}"
        return headers
    headers["api-key"] = sanitized_api_key
    return headers


def ensure_audit_llm_v1_endpoint(endpoint: str) -> str:
    """Return an endpoint in the format expected by PyRIT's OpenAIChatTarget."""
    normalized = normalize_audit_llm_endpoint(endpoint)
    if not normalized:
        return normalized
    if normalized.lower().endswith("/openai/v1"):
        return normalized
    return f"{normalized}/openai/v1"


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    # Azure OpenAI Configuration
    audit_llm_api_key: str = Field(default="", validation_alias="AUDIT_LLM_API_KEY")
    audit_llm_endpoint: str = Field(default="", validation_alias="AUDIT_LLM_ENDPOINT")
    audit_llm_api_version: str = Field(
        default="2024-02-15-preview",
        validation_alias="AUDIT_LLM_API_VERSION",
    )
    # Accept both env names:
    # - AUDIT_LLM_DEPLOYMENT (our .env.example)
    # - AUDIT_LLM_chat_deployment_name (common in Azure AI SDK samples)
    audit_llm_deployment: str = Field(
        default="gpt-4",
        validation_alias=AliasChoices(
            "AUDIT_LLM_DEPLOYMENT", "audit_llm_chat_deployment_name"
        ),
    )

    # Azure OpenAI Adversarial Endpoint Configuration (for attack generation)
    # Support both legacy names and the explicit adversarial-openai names used by the red-team setup.
    adversarial_endpoint: str = Field(
        default="",
        validation_alias=AliasChoices(
            "ADVERSARIAL_ENDPOINT",
            "ADVERSARIAL_OPENAI_ENDPOINT",
            "AUDIT_LLM_ADVERSARIAL_ENDPOINT",
        ),
    )
    adversarial_api_key: str = Field(
        default="",
        validation_alias=AliasChoices(
            "ADVERSARIAL_API_KEY",
            "ADVERSARIAL_OPENAI_API_KEY",
            "AUDIT_LLM_ADVERSARIAL_API_KEY",
        ),
    )
    adversarial_deployment: str = Field(
        default="gpt-4",
        validation_alias=AliasChoices(
            "ADVERSARIAL_DEPLOYMENT",
            "ADVERSARIAL_OPENAI_DEPLOYMENT",
            "AUDIT_LLM_ADVERSARIAL_DEPLOYMENT",
        ),
    )
    adversarial_api_version: str = Field(
        default="2024-10-21",
        validation_alias=AliasChoices(
            "ADVERSARIAL_API_VERSION",
            "ADVERSARIAL_OPENAI_API_VERSION",
            "AUDIT_LLM_ADVERSARIAL_API_VERSION",
        ),
    )

    # Backend API Configuration
    backend_api_url: str = Field(
        default="http://localhost:8000",
        validation_alias="BACKEND_API_URL",
    )
    backend_api_timeout: int = Field(default=30, validation_alias="BACKEND_API_TIMEOUT")
    backend_client_id: str = Field(
        default="11111111-1111-4111-8111-111111111111",
        validation_alias="BACKEND_CLIENT_ID",
    )
    backend_application_id: int = Field(
        default=234554,
        validation_alias="BACKEND_APPLICATION_ID",
    )
    backend_step_number: str = Field(
        default="step2-Eligibility",
        validation_alias="BACKEND_STEP_NUMBER",
    )

    # Evaluation Configuration
    evaluation_run_name: str = Field(
        default="evaluation_run",
        validation_alias="EVALUATION_RUN_NAME",
    )
    evaluation_scenario: str = Field(
        default="basic_evaluation",
        validation_alias="EVALUATION_SCENARIO",
    )

    # Logging
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")

    # Proxy settings
    http_proxy: str = Field(default="", validation_alias=AliasChoices("HTTP_PROXY", "http_proxy"))
    https_proxy: str = Field(default="", validation_alias=AliasChoices("HTTPS_PROXY", "https_proxy"))
    all_proxy: str = Field(default="", validation_alias=AliasChoices("ALL_PROXY", "all_proxy"))
    red_team_proxy_url: str = Field(
        default="",
        validation_alias=AliasChoices("RED_TEAM_PROXY_URL", "PROXY_URL", "proxy_url"),
    )

    # Optional extra evaluators. Leave empty for the minimal PyRIT scoring workflow.
    enabled_evaluators: str = Field(
        default="",
        validation_alias="ENABLED_EVALUATORS",
    )  # Comma-separated list of evaluator names to run; empty disables Azure-specific evaluators

    # Azure AI Project Configuration (required for ViolenceEvaluator)
    azure_ai_project: Optional[str] = Field(
        default="https://ai-services-hub-test-foundry.services.ai.azure.com/api/projects/wlrs-water-form-assistant-project",
        validation_alias="AZURE_AI_PROJECT",
    )  # Azure AI project endpoint URL or connection string

    # Azure AI Search Configuration
    azure_search_endpoint: str = Field(
        default="https://css-ai-dev-aisearch.search.windows.net",
        validation_alias="AZURE_SEARCH_ENDPOINT",
    )
    azure_search_api_key: str = Field(
        default="",
        validation_alias="AZURE_SEARCH_API_KEY",
    )
    azure_search_index_name: str = Field(
        default="rag-bc-waterpermit-dev",
        validation_alias="AZURE_SEARCH_INDEX_NAME",
    )
    azure_search_top: int = Field(
        default=3,
        validation_alias="AZURE_SEARCH_TOP",
    )
    azure_search_trim_length: int = Field(
        default=500,
        validation_alias="AZURE_SEARCH_TRIM_LENGTH",
    )
    azure_search_enable_trimming: bool = Field(
        default=True,
        validation_alias="AZURE_SEARCH_ENABLE_TRIMMING",
    )
    azure_search_include_total_count: bool = Field(
        default=True,
        validation_alias="AZURE_SEARCH_INCLUDE_TOTAL_COUNT",
    )
    azure_search_query_type: str = Field(
        default="simple",
        validation_alias="AZURE_SEARCH_QUERY_TYPE",
    )
    azure_search_semantic_configuration: str = Field(
        default="default",
        validation_alias="AZURE_SEARCH_SEMANTIC_CONFIGURATION",
    )
    azure_search_query_caption: str = Field(
        default="extractive",
        validation_alias="AZURE_SEARCH_QUERY_CAPTION",
    )
    azure_search_query_answer: str = Field(
        default="extractive",
        validation_alias="AZURE_SEARCH_QUERY_ANSWER",
    )
    azure_search_query_answer_count: int = Field(
        default=3,
        validation_alias="AZURE_SEARCH_QUERY_ANSWER_COUNT",
    )
    azure_search_query_language: str = Field(
        default="en-us",
        validation_alias="AZURE_SEARCH_QUERY_LANGUAGE",
    )

    model_config = SettingsConfigDict(
        env_file=[
            str(Path(__file__).resolve().with_name(".env")),
            str(Path(__file__).resolve().parents[1] / ".env"),
        ],
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # prevents crash if env contains keys we don't model
    )
    groundedness_threshold: float = Field(
        default=0.5,
        validation_alias="GROUNDEDNESS_THRESHOLD",
    )
    
    code_vulnerability_threshold: float = Field(
        default=0.8,
        validation_alias="CODE_VULNERABILITY_THRESHOLD",
    )

    # PyRIT Red-Teaming Configuration
    enable_red_team: bool = Field(
        default=False,
        validation_alias="ENABLE_RED_TEAM",
    )
    
    red_team_threat_models: str = Field(
        default="jailbreak,prompt_injection,data_exfiltration",
        validation_alias="RED_TEAM_THREAT_MODELS",
    )  # Comma-separated list of threat models to test
    
    red_team_max_iterations: int = Field(
        default=5,
        validation_alias="RED_TEAM_MAX_ITERATIONS",
    )  # Max attack chains per threat model
    
    red_team_timeout_seconds: int = Field(
        default=300,
        validation_alias="RED_TEAM_TIMEOUT_SECONDS",
    )  # Timeout per red-team test
    
    red_team_vulnerability_threshold: float = Field(
        default=0.3,
        validation_alias="RED_TEAM_VULNERABILITY_THRESHOLD",
    )  # Score above this = vulnerable

    def validate_config(self) -> bool:
        """Validate required configuration"""
        if not self.audit_llm_api_key:
            raise ValueError("AUDIT_LLM_API_KEY is required")
        if not self.audit_llm_endpoint:
            raise ValueError("AUDIT_LLM_ENDPOINT is required")
        if not self.backend_api_url:
            raise ValueError("BACKEND_API_URL is required")
        return True

    def use_azure_search(self) -> bool:
        """Check if Azure Search is configured."""
        return bool(
            self.azure_search_endpoint
            and self.azure_search_api_key
            and self.azure_search_index_name
        )


def sync_runtime_proxy_env() -> None:
    """Mirror configured proxy settings into os.environ so downstream HTTP clients use them."""
    proxy_candidates = [
        ("HTTPS_PROXY", settings.https_proxy or settings.red_team_proxy_url),
        ("https_proxy", settings.https_proxy or settings.red_team_proxy_url),
        ("HTTP_PROXY", settings.http_proxy or settings.red_team_proxy_url),
        ("http_proxy", settings.http_proxy or settings.red_team_proxy_url),
        ("ALL_PROXY", settings.all_proxy or settings.red_team_proxy_url),
        ("all_proxy", settings.all_proxy or settings.red_team_proxy_url),
    ]
    for key, value in proxy_candidates:
        if value:
            os.environ[key] = value
            if key.upper() == "HTTPS_PROXY":
                os.environ.setdefault("https_proxy", value)
            elif key.upper() == "HTTP_PROXY":
                os.environ.setdefault("http_proxy", value)
            elif key.upper() == "ALL_PROXY":
                os.environ.setdefault("all_proxy", value)


# Global settings instance
settings = Settings()
sync_runtime_proxy_env()
