# src/logos/pipeline/context_resolver.py
"""
Context resolution - prepares execution inputs from database lookups.

Separates the "what to execute" (context resolution) from "how to execute" (executor).
"""

from dataclasses import dataclass
from typing import Optional, Dict, Any, Tuple
import logging

from logos.dbutils.dbmanager import DBManager


logger = logging.getLogger(__name__)


@dataclass
class ExecutionContext:
    """Everything needed to execute a request - resolved from DB."""
    model_id: int
    provider_id: int
    provider_name: str
    forward_url: str
    auth_header: str
    auth_value: str
    model_name: str


class ContextResolver:
    """
    Resolves execution context from database.

    Responsibilities:
    - Look up model/provider/API key from DB
    - Construct forward URL and auth headers
    - Return all info needed for HTTP execution

    NOT responsible for:
    - Making HTTP calls (that's the Executor's job)
    """

    def resolve_context(
        self,
        model_id: int,
        provider_id: int,
        logos_key: Optional[str] = None,
        profile_id: Optional[int] = None
    ) -> Optional[ExecutionContext]:
        """
        Resolve all DB information needed to execute a request with authorization verification.

        This includes:
        - Model endpoint and configuration
        - Provider base URL and type
        - API key for the specific model/provider pair
        - Authorization check (if logos_key and profile_id provided)

        Args:
            model_id: The ID of the model to execute.
            provider_id: The ID of the provider (currently unused, for future extension)
            logos_key: User's logos key (for authorization check)
            profile_id: Profile ID (for authorization check)

        Returns:
            `ExecutionContext` with all details, or `None` if resolution fails (e.g. missing key, unauthorized).
        """
        with DBManager() as db:
            # AUTHORIZATION CHECK: Verify user has access to this deployment (defense in depth)
            auth_info = db.get_auth_info_to_deployment(model_id, provider_id, profile_id)
            if not auth_info:
                logger.error(f"No deployment auth info for model={model_id}, provider={provider_id}, profile={profile_id}")
                return None

            auth_name = (auth_info.get("auth_name") or "").strip()
            auth_format = auth_info.get("auth_format") or ""
            api_key = auth_info.get("api_key")

            if not api_key and (auth_name or auth_format):
                logger.error(f"No API key for model {model_id} / provider {provider_id}")
                return None

        provider_name = auth_info["provider_name"]
        model_name = auth_info["model_name"]
        endpoint = auth_info["endpoint"]
        base_url = auth_info["base_url"]
        forward_url = self._merge_url(base_url, endpoint)

        return ExecutionContext(
            model_id=model_id,
            provider_id=provider_id,
            provider_name=provider_name,
            forward_url=forward_url,
            auth_header=auth_name,
            auth_value=auth_format.format(api_key or ""),
            model_name=model_name,
        )


    @staticmethod
    def prepare_headers_and_payload(
            context: ExecutionContext,
        payload: Dict[str, Any]
    ) -> Tuple[Dict[str, str], Dict[str, Any]]:
        """
        Prepare HTTP headers and potentially modify payload based on context.

        Args:
            context: Execution context with auth info
            payload: Original request payload

        Returns:
            Tuple of (headers, modified_payload)
        """
        headers = {"Content-Type": "application/json"}
        if context.auth_header and context.auth_value:
            headers[context.auth_header] = context.auth_value

        # OpenWebUI requires model name injection
        if "openwebui" in context.provider_name.lower() or "ollama" in context.provider_name.lower():
            payload = {**payload, "model": context.model_name}

        return headers, payload


    @staticmethod
    def _merge_url(base_url: str, endpoint: str) -> str:
        """Merge base URL and endpoint path."""
        if endpoint.startswith("http"):
            return endpoint
        base = base_url.rstrip("/")
        path = endpoint.lstrip("/")
        return f"{base}/{path}"
