"""Settings for the promptfoo service, loaded from environment variables / promptfoo/.env."""

from __future__ import annotations

from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Judge model (llm-rubric grading), reached through the local grader proxy
    audit_llm_api_key: str = Field(default="", validation_alias="audit_llm_API_KEY")
    audit_llm_endpoint: str = Field(default="", validation_alias="AUDIT_LLM_ENDPOINT")
    audit_llm_api_version: str = Field(default="2024-10-21", validation_alias="AUDIT_LLM_API_VERSION")
    audit_llm_deployment: str = Field(
        default="gpt-4",
        validation_alias=AliasChoices("AUDIT_LLM_DEPLOYMENT", "audit_llm_chat_deployment_name"),
    )

    # Attack-generation model (red-team commands)
    adversarial_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("ADVERSARIAL_API_KEY", "ADVERSARIAL_OPENAI_API_KEY", "AUDIT_LLM_ADVERSARIAL_API_KEY"),
    )

    # System under test (the AIFA backend, reached over WebSocket)
    backend_api_url: str = Field(default="http://localhost:8000", validation_alias="BACKEND_API_URL")
    backend_api_timeout: int = Field(default=30, validation_alias="BACKEND_API_TIMEOUT")
    backend_client_id: str = Field(default="11111111-1111-4111-8111-111111111111", validation_alias="BACKEND_CLIENT_ID")
    backend_application_id: int = Field(default=234554, validation_alias="BACKEND_APPLICATION_ID")
    backend_step_number: str = Field(default="step2-Eligibility", validation_alias="BACKEND_STEP_NUMBER")

    # Absolute path: a bare ".env" resolves against the cwd, which is the repo root for uvicorn.
    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parents[1] / ".env"),
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()
