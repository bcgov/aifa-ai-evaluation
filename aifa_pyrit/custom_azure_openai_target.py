"""Custom Azure OpenAI Chat Target for PyRIT with proper API key authentication."""

import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import Optional

# We intentionally use httpx instead of aiohttp here because the repo's Azure-dev workflow
# routes outbound OpenAI traffic through SOCKS5h via environment variables (for example,
# HTTPS_PROXY=socks5h://127.0.0.1:8081). httpx honors that env-driven proxy configuration
# reliably without hard-coding Azure-dev vs local-dev logic into the app. This keeps the
# same endpoint/settings working across local laptop dev and bastion/Azure tunnel access.
import httpx
from pyrit.memory.central_memory import CentralMemory
from pyrit.memory.sqlite_memory import SQLiteMemory
from pyrit.prompt_target import PromptTarget
from pyrit.prompt_target.common.target_configuration import TargetConfiguration
from pyrit.prompt_target.common.target_capabilities import TargetCapabilities
from pyrit.models import Message
import structlog

from aifa_pyrit.config import normalize_azure_openai_endpoint

logger = structlog.get_logger(__name__)


class CustomAzureOpenAITarget(PromptTarget):
    @staticmethod
    def _resolve_proxy_url() -> str | None:
        """Return the active proxy URL for outbound HTTPS traffic.

        This supports the same env-driven switch used by the repo's local Azure dev flow:
        - Azure dev via SOCKS5h tunnel: export HTTPS_PROXY=socks5h://127.0.0.1:8081
        - Local direct access: unset HTTP_PROXY/HTTPS_PROXY/ALL_PROXY
        """
        for key in ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy"):
            value = os.getenv(key)
            if value:
                return value
        return None

    @staticmethod
    def _format_azure_error_message(status_code: int, response_text: str) -> str:
        """Convert Azure model responses into a clear, actionable error string."""
        default_msg = f"Azure OpenAI request failed with HTTP {status_code}."
        try:
            payload = json.loads(response_text or "{}")
        except json.JSONDecodeError:
            return f"{default_msg} Details: {response_text.strip() or 'No response body returned.'}"

        error = payload.get("error") or payload
        code = error.get("code") if isinstance(error, dict) else None
        message = error.get("message") if isinstance(error, dict) else str(error)

        if code or message:
            summary = message or code or "Azure policy rejected the request"
            if isinstance(code, str) and code.lower() in {"content_filter", "responsibleaipolicyviolation"}:
                return (
                    "Azure OpenAI blocked the request due to safety policy filtering "
                    f"(HTTP {status_code}, code={code}). Details: {summary}"
                )
            if "Public access is disabled" in str(summary):
                return (
                    "Azure OpenAI request was blocked by private-endpoint/network policy "
                    f"(HTTP {status_code}, code={code}). Details: {summary}"
                )
            return f"Azure OpenAI request failed with HTTP {status_code} (code={code}). Details: {summary}"

        return default_msg
    """Custom target for Azure OpenAI with proper api-key header authentication."""

    # Declare capabilities for this target
    _DEFAULT_CONFIGURATION: TargetConfiguration = TargetConfiguration(
        capabilities=TargetCapabilities(
            supports_multi_turn=True,
            supports_editable_history=True,
            supports_system_prompt=True,
        )
    )

    @staticmethod
    def _ensure_memory_initialized() -> None:
        """Initialize PyRIT central memory if it is not already configured."""
        try:
            CentralMemory.get_memory_instance()
            return
        except ValueError:
            pass

        db_path = Path(tempfile.gettempdir()) / "pyrit-central-memory.sqlite"
        CentralMemory.set_memory_instance(SQLiteMemory(db_path=db_path, silent=True))

    def __init__(
        self,
        *,
        endpoint: str,
        api_key: str,
        deployment: str = "gpt-5.1",
        api_version: str = "2024-10-21",
        timeout: int = 30,
    ):
        """
        Initialize custom Azure OpenAI target.
        
        Args:
            endpoint: Base endpoint URL (without /openai/deployments path)
            api_key: API key for authentication
            deployment: Model deployment name
            api_version: Azure API version
            timeout: Request timeout in seconds
        """
        self._ensure_memory_initialized()
        super().__init__()
        self.endpoint = normalize_azure_openai_endpoint(endpoint)
        self.api_key = api_key
        self.deployment = deployment
        self.api_version = api_version
        self.timeout = timeout
        
        logger.info(
            "custom_azure_openai_target_initialized",
            endpoint=self.endpoint,
            deployment=deployment,
            api_version=api_version,
        )

    async def _send_prompt_to_target_async(
        self,
        *,
        normalized_conversation: list[Message],
    ) -> list[Message]:
        """
        Send prompt to Azure OpenAI endpoint and get response.
        
        Args:
            normalized_conversation: List of Message objects in conversation
            
        Returns:
            List of Message objects with response
        """
        try:
            # Get the last user message from the conversation
            last_message = None
            for msg in reversed(normalized_conversation):
                if hasattr(msg, 'api_role') and msg.api_role == "user":
                    last_message = msg
                    break
            
            if not last_message:
                error_response = Message.from_prompt(
                    prompt="No user message found in conversation",
                    role="assistant"
                )
                return [error_response]
            
            # Extract prompt text from message
            prompt = str(last_message.get_value())
            
            # Construct full URL for Azure OpenAI
            url = f"{self.endpoint}/openai/deployments/{self.deployment}/chat/completions?api-version={self.api_version}"
            
            # Build request payload
            # Convert message history to Azure OpenAI format
            messages = []
            for msg in normalized_conversation:
                messages.append({
                    "role": msg.api_role,
                    "content": str(msg.get_value())
                })
            
            payload = {"messages": messages}
            
            # Headers with proper API key authentication
            headers = {
                "Content-Type": "application/json",
                "api-key": self.api_key,
            }
            
            logger.info(
                "sending_azure_openai_request",
                url=url,
                num_messages=len(messages),
            )
            
            # Make async request.
            # httpx honors SOCKS5h proxy env vars without changing the Azure endpoint names,
            # which keeps Azure-dev and local-dev swapping clean and portable.
            proxy = self._resolve_proxy_url()
            async with httpx.AsyncClient(
                proxy=proxy,
                trust_env=True,
                timeout=httpx.Timeout(self.timeout),
            ) as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers=headers,
                )
                if response.status_code != 200:
                    error_text = response.text
                    error_msg = self._format_azure_error_message(response.status_code, error_text)
                    logger.error(
                        "azure_openai_request_failed",
                        status=response.status_code,
                        error=error_text,
                        formatted_message=error_msg,
                    )
                    error_response = Message.from_prompt(
                        prompt=error_msg,
                        role="assistant"
                    )
                    return [error_response]

                result = response.json()

                # Extract response content
                response_content = result["choices"][0]["message"]["content"]

                logger.info(
                    "azure_openai_request_success",
                    response_length=len(response_content),
                )

                # Create response message
                response_message = Message.from_prompt(
                    prompt=response_content,
                    role="assistant"
                )

                return [response_message]
                    
        except Exception as e:
            error_msg = f"Error querying Azure OpenAI: {str(e)}"
            logger.error(
                "azure_openai_request_exception",
                error=str(e),
            )
            error_response = Message.from_prompt(
                prompt=error_msg,
                role="assistant"
            )
            return [error_response]

    @property
    def prompt_target_name(self) -> str:
        """Return target name."""
        return "CustomAzureOpenAI"

