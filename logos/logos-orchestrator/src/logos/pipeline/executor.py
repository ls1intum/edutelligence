# src/logos/pipeline/executor.py
"""
Backend execution - makes HTTP calls to AI providers.

The Executor is a pure HTTP client that makes streaming or synchronous requests.
"""

import json
import logging
from dataclasses import dataclass
from typing import Any, AsyncIterator, Callable, Dict, Optional

import httpx

from logos.errors import UpstreamStreamError, coerce_upstream_error

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
    status_code: Optional[int] = None


@dataclass
class StreamingExecutionStatus:
    """Mutable terminal status shared with a streaming response consumer."""

    error: Optional[str] = None


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
        on_response_start: Optional[Callable[[int, Dict[str, str]], None]] = None,
        status: Optional[StreamingExecutionStatus] = None,
    ) -> AsyncIterator[bytes]:
        """
        Execute streaming HTTP request and yield response chunks.

        Args:
            url: Full URL to make request to
            headers: HTTP headers (including auth, content-type, etc.)
            payload: Request body (will have stream=True injected)
            on_headers: Optional callback invoked with response headers (headers dict only)
            on_response_start: Optional callback invoked with (status_code, headers) before
                any chunks are yielded; allows callers to detect non-2xx early.
            status: Optional mutable terminal status populated when a transport
                failure occurs after response bytes have already been yielded.

        Yields:
            Upstream response bytes without reconstructing their framing.

        Raises:
            UpstreamStreamError: If the upstream returns a non-2xx status before
                streaming begins.

        A transport failure before any response bytes are received is re-raised
        so callers can avoid committing an empty successful response. Once bytes
        have been delivered, they cannot be retracted. For SSE responses, the
        generator starts a new frame and emits a best-effort error followed by
        ``data: [DONE]``; clients may still report the preceding partial upstream
        event as malformed. Other streaming formats terminate without appending
        foreign protocol bytes.
        """
        # Force streaming
        payload = self._streaming_payload(url, payload)

        logger.info(f"Streaming request to {url}")

        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as resp:
                resp_headers = dict(resp.headers)
                if on_response_start:
                    on_response_start(resp.status_code, resp_headers)
                if on_headers:
                    on_headers(resp_headers)

                if resp.status_code >= 400:
                    # Collect full error body before yielding anything.
                    # Raise UpstreamStreamError so the caller can decide:
                    # - return a proper JSONResponse with the correct HTTP status, or
                    # - fall back to an SSE error frame if already mid-stream.
                    body_bytes = await resp.aread()
                    try:
                        body = json.loads(body_bytes)
                    except json.JSONDecodeError:
                        body = {"error": body_bytes.decode(errors="replace")[:500]}
                    logger.error(f"Streaming request to {url} failed: " f"status={resp.status_code}, body={body}")
                    raise UpstreamStreamError(resp.status_code, body)

                content_type = resp_headers.get("content-type", "")
                media_type = content_type.split(";", 1)[0].strip().lower()
                is_sse = media_type == "text/event-stream"
                yielded_bytes = False
                try:
                    # Preserve upstream byte framing. SSE uses blank lines to
                    # delimit events, and local providers may stream NDJSON;
                    # reconstructing either format line-by-line changes it.
                    async for chunk in resp.aiter_bytes():
                        if chunk:
                            yielded_bytes = True
                            yield chunk
                except Exception as exc:
                    # Before the first byte, propagate the failure so the caller
                    # can still return an HTTP error. Afterwards, append only
                    # protocol-compatible recovery frames; non-SSE streams
                    # terminate without introducing foreign framing.
                    logger.error(f"Mid-stream error from {url}: {exc}")
                    if not yielded_bytes:
                        raise
                    if status is not None:
                        status.error = str(exc)
                    if not is_sse:
                        return
                    _, error_body = coerce_upstream_error(500, {"error": str(exc)})
                    yield b"\n\n"
                    yield f"data: {json.dumps(error_body)}\n\n".encode()
                    yield b"data: [DONE]\n\n"

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
                logger.error(
                    f"Failed to decode JSON from {url}, status={response.status_code}, text={response.text[:200]}"
                )
                return ExecutionResult(
                    success=False,
                    response=None,
                    error=f"Invalid JSON response (status {response.status_code}): {response.text[:200]}",
                    usage={},
                    is_streaming=False,
                    headers=dict(response.headers),
                    status_code=response.status_code,
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
                status_code=response.status_code,
            )

        except Exception as e:
            logger.error(f"Exception during request to {url}: {type(e).__name__}: {e}")
            return ExecutionResult(
                success=False,
                response=None,
                error=f"{type(e).__name__}: {str(e)}",
                usage={},
                is_streaming=False,
                status_code=None,
            )

    @staticmethod
    def _streaming_payload(url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Prepare the payload for a streaming request.

        ``stream_options.include_usage`` is a Chat-Completions-only parameter:
        the Responses API rejects it as unknown and instead always reports
        usage in its terminal ``response.completed`` event, so it is skipped
        for ``/responses`` upstreams (both OpenAI ``/v1/responses`` and Azure
        ``/openai/responses``).
        """
        if Executor._is_responses_url(url):
            return {**payload, "stream": True}
        return {**payload, "stream": True, "stream_options": {"include_usage": True}}

    @staticmethod
    def _is_responses_url(url: str) -> bool:
        """Whether the upstream URL targets a Responses API endpoint."""
        path = (url or "").split("?", 1)[0].rstrip("/")
        return path.endswith("/responses")

    @staticmethod
    def _extract_usage(response: Dict[str, Any]) -> Dict[str, int]:
        """Extract usage tokens from response body."""
        usage = response.get("usage", {})
        result = {}
        for key, value in usage.items():
            if isinstance(value, int) and "details" not in key:
                result[key] = value
        return result
