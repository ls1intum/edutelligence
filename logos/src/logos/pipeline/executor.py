# src/logos/pipeline/executor.py
"""
Backend execution - resolves DB paths, makes API calls.
"""

from dataclasses import dataclass
from typing import Dict, Any, Optional, AsyncIterator, Callable
import httpx
import json
import logging

from logos.dbutils.dbmanager import DBManager


logger = logging.getLogger(__name__)


@dataclass
class ExecutionContext:
    """Everything needed to execute a request."""
    model_id: int
    provider_id: int
    provider_name: str
    forward_url: str
    auth_header: str
    auth_value: str
    model_name: str


@dataclass
class ExecutionResult:
    """Result of backend execution."""
    success: bool
    response: Optional[Dict[str, Any]]
    error: Optional[str]
    usage: Dict[str, int]
    is_streaming: bool
    headers: Optional[Dict[str, str]] = None


class Executor:
    """
    Resolves execution context from DB and calls backends.
    
    Responsibilities:
    - Look up model/provider/API key from DB
    - Construct forward URL and auth headers
    - Make sync or streaming HTTP calls
    - Parse responses and extract usage
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
            
            api_key = db.get_key_to_model_provider(model_id, provider["id"])
            if not api_key:
                logger.error(f"No API key for model {model_id} / provider {provider['id']}")
                return None
        
        forward_url = self._merge_url(provider["base_url"], model["endpoint"])
        
        return ExecutionContext(
            model_id=model_id,
            provider_id=provider["id"],
            provider_name=provider["name"],
            forward_url=forward_url,
            auth_header=provider["auth_name"],
            auth_value=provider["auth_format"].format(api_key),
            model_name=model["name"],
        )
    
    async def execute_streaming(
        self,
        context: ExecutionContext,
        payload: Dict[str, Any],
        on_headers: Optional[Callable[[Dict[str, str]], None]] = None,
    ) -> AsyncIterator[bytes]:
        """
        Execute streaming request and yield response chunks.
        
        Args:
            context: Execution properties (URL, auth, etc.).
            payload: Request body.
            on_headers: Optional callback invoked with response headers (for rate limits).
            
        Yields:
            Byte chunks of the response body.
        """
        headers = {
            context.auth_header: context.auth_value,
            "Content-Type": "application/json",
        }
        
        # Inject model name for OpenWebUI
        if "openwebui" in context.provider_name.lower():
            payload = {**payload, "model": context.model_name}
        
        payload["stream"] = True
        payload["stream_options"] = {"include_usage": True}
        
        logger.info(f"Stream-Executing request to {context.forward_url} (model: {context.model_name})")
        
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST", 
                context.forward_url, 
                headers=headers, 
                json=payload
            ) as resp:
                if on_headers:
                    on_headers(dict(resp.headers))
                
                async for line in resp.aiter_lines():
                    if line:
                        yield (line + "\n").encode()
    
    async def execute_sync(
        self,
        context: ExecutionContext,
        payload: Dict[str, Any],
    ) -> ExecutionResult:
        """
        Execute synchronous (non-streaming) request.
        
        Args:
            context: Execution properties.
            payload: Request body.
            
        Returns:
            ExecutionResult containing response body, usage stats, and headers.
        """
        headers = {
            context.auth_header: context.auth_value,
            "Content-Type": "application/json",
        }
        
        if "openwebui" in context.provider_name.lower():
            payload = {**payload, "model": context.model_name}
        
        payload["stream"] = False
        
        logger.info(f"Sync-Executing request to {context.forward_url} (model: {context.model_name})")
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    context.forward_url,
                    headers=headers,
                    json=payload,
                    timeout=30,
                )
            
            try:
                body = response.json()
            except json.JSONDecodeError:
                return ExecutionResult(
                    success=False,
                    response=None,
                    error=response.text,
                    usage={},
                    is_streaming=False,
                    headers=dict(response.headers),
                )
            
            usage = self._extract_usage(body)
            
            return ExecutionResult(
                success=response.status_code < 400,
                response=body,
                error=body.get("error") if response.status_code >= 400 else None,
                usage=usage,
                is_streaming=False,
                headers=dict(response.headers),
            )
            
        except Exception as e:
            return ExecutionResult(
                success=False,
                response=None,
                error=str(e),
                usage={},
                is_streaming=False,
            )
    
    async def execute_direct_streaming(
        self,
        forward_url: str,
        headers: Dict[str, str],
        payload: Dict[str, Any],
        on_headers: Optional[Callable[[Dict[str, str]], None]] = None,
    ) -> AsyncIterator[bytes]:
        """
        Execute streaming request directly (PROXY MODE - no ExecutionContext needed).

        This is used for PROXY mode where we bypass classification/scheduling
        and forward directly to a provider.

        Args:
            forward_url: Full URL to forward the request to.
            headers: HTTP headers (including auth).
            payload: Request body.
            on_headers: Optional callback invoked with response headers.

        Yields:
            Byte chunks of the response body.
        """
        payload = {**payload, "stream": True, "stream_options": {"include_usage": True}}

        logger.info(f"Direct-Stream-Executing request to {forward_url}")

        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST",
                forward_url,
                headers=headers,
                json=payload
            ) as resp:
                if on_headers:
                    on_headers(dict(resp.headers))

                async for line in resp.aiter_lines():
                    if line:
                        yield (line + "\n").encode()

    async def execute_direct_sync(
        self,
        forward_url: str,
        headers: Dict[str, str],
        payload: Dict[str, Any],
    ) -> ExecutionResult:
        """
        Execute synchronous request directly (PROXY MODE - no ExecutionContext needed).

        This is used for PROXY mode where we bypass classification/scheduling
        and forward directly to a provider.

        Args:
            forward_url: Full URL to forward the request to.
            headers: HTTP headers (including auth).
            payload: Request body.

        Returns:
            ExecutionResult containing response body, usage stats, and headers.
        """
        payload = {**payload, "stream": False}

        logger.info(f"Direct-Sync-Executing request to {forward_url}")

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    forward_url,
                    headers=headers,
                    json=payload,
                    timeout=30,
                )

            try:
                body = response.json()
            except json.JSONDecodeError:
                return ExecutionResult(
                    success=False,
                    response=None,
                    error=response.text,
                    usage={},
                    is_streaming=False,
                    headers=dict(response.headers),
                )

            usage = self._extract_usage(body)

            return ExecutionResult(
                success=response.status_code < 400,
                response=body,
                error=body.get("error") if response.status_code >= 400 else None,
                usage=usage,
                is_streaming=False,
                headers=dict(response.headers),
            )

        except Exception as e:
            return ExecutionResult(
                success=False,
                response=None,
                error=str(e),
                usage={},
                is_streaming=False,
            )

    def _merge_url(self, base_url: str, endpoint: str) -> str:
        if endpoint.startswith("http"):
            return endpoint
        base = base_url.rstrip("/")
        path = endpoint.lstrip("/")
        return f"{base}/{path}"

    def _extract_usage(self, response: Dict[str, Any]) -> Dict[str, int]:
        usage = response.get("usage", {})
        result = {}
        for key, value in usage.items():
            if isinstance(value, int) and "details" not in key:
                result[key] = value
        return result
