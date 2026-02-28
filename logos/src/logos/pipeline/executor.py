# src/logos/pipeline/executor.py
"""
Backend execution - makes HTTP calls to AI providers.

The Executor is a pure HTTP client that makes streaming or synchronous requests.
"""

from dataclasses import dataclass
from typing import Dict, Any, Optional, AsyncIterator, Callable
import httpx
import json
import logging


logger = logging.getLogger(__name__)


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
    Pure HTTP client for making requests to AI backends.

    Responsibilities:
    - Make sync or streaming HTTP calls
    - Parse responses and extract usage
    """

    async def execute_streaming(
        self,
        url: str,
        headers: Dict[str, str],
        payload: Dict[str, Any],
        on_headers: Optional[Callable[[Dict[str, str]], None]] = None,
    ) -> AsyncIterator[bytes]:
        """
        Execute streaming HTTP request and yield response chunks.

        Args:
            url: Full URL to make request to
            headers: HTTP headers (including auth, content-type, etc.)
            payload: Request body (will have stream=True injected)
            on_headers: Optional callback invoked with response headers

        Yields:
            Byte chunks of the response body (SSE format)
        """
        # Force streaming
        payload = {**payload, "stream": True, "stream_options": {"include_usage": True}}

        logger.info(f"Streaming request to {url}")

        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST",
                url,
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
        url: str,
        headers: Dict[str, str],
        payload: Dict[str, Any],
    ) -> ExecutionResult:
        """
        Execute synchronous (non-streaming) HTTP request.

        Args:
            url: Full URL to make request to
            headers: HTTP headers (including auth, content-type, etc.)
            payload: Request body (will have stream=False injected)

        Returns:
            ExecutionResult containing response body, usage stats, and headers
        """
        # Force non-streaming
        payload = {**payload, "stream": False}

        logger.info(f"Sync request to {url}")

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=None,  # No timeout to handle long-running LLM requests and cold starts
                )

            logger.debug(f"Response status: {response.status_code}, headers: {dict(response.headers)}")

            try:
                body = response.json()
            except json.JSONDecodeError:
                logger.error(f"Failed to decode JSON from {url}, status={response.status_code}, text={response.text[:200]}")
                return ExecutionResult(
                    success=False,
                    response=None,
                    error=f"Invalid JSON response (status {response.status_code}): {response.text[:200]}",
                    usage={},
                    is_streaming=False,
                    headers=dict(response.headers),
                )

            usage = self._extract_usage(body)

            is_success = response.status_code < 400
            error_msg = body.get("error") if not is_success else None

            if not is_success:
                logger.error(f"Request to {url} failed: status={response.status_code}, body={body}")

            return ExecutionResult(
                success=is_success,
                response=body,
                error=error_msg,
                usage=usage,
                is_streaming=False,
                headers=dict(response.headers),
            )

        except Exception as e:
            logger.error(f"Exception during request to {url}: {type(e).__name__}: {e}")
            return ExecutionResult(
                success=False,
                response=None,
                error=f"{type(e).__name__}: {str(e)}",
                usage={},
                is_streaming=False,
            )


    @staticmethod
    def _extract_usage(response: Dict[str, Any]) -> Dict[str, int]:
        """Extract usage tokens from response body."""
        usage = response.get("usage", {})
        result = {}
        for key, value in usage.items():
            if isinstance(value, int) and "details" not in key:
                result[key] = value
        return result
