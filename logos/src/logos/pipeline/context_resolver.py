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

    def resolve_context(self, model_id: int) -> Optional[ExecutionContext]:
        """
        Resolve all DB information needed to execute a request.

        This includes:
        - Model endpoint and configuration
        - Provider base URL and type
        - API key for the specific model/provider pair

        Args:
            model_id: The ID of the model to execute.

        Returns:
            `ExecutionContext` with all details, or `None` if resolution fails (e.g. missing key).
        """
        with DBManager() as db:
            model = db.get_model(model_id)
            if not model:
                logger.error(f"Model {model_id} not found in DB")
                return None

            provider = db.get_provider_to_model(model_id)
            if not provider:
                logger.error(f"No provider linked to model {model_id}")
                return None

            auth_name = (provider.get("auth_name") or "").strip()
            auth_format = provider.get("auth_format") or ""

            api_key = db.get_key_to_model_provider(model_id, provider["id"])
            if not api_key and (auth_name or auth_format):
                logger.error(f"No API key for model {model_id} / provider {provider['id']}")
                return None

        forward_url = self._merge_url(provider["base_url"], model["endpoint"])

        return ExecutionContext(
            model_id=model_id,
            provider_id=provider["id"],
            provider_name=provider["name"],
            forward_url=forward_url,
            auth_header=auth_name,
            auth_value=auth_format.format(api_key or ""),
            model_name=model["name"],
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
