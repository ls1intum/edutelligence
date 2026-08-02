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
from logos.request_content import httpx_multipart_parts, is_multipart_payload, set_payload_field

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """Result of backend execution."""

    success: bool
    response: Any
    error: Optional[str]
    usage: Dict[str, int]
    is_streaming: bool
    headers: Optional[Dict[str, str]] = None
    status_code: Optional[int] = None
    raw_body: Optional[bytes] = None
    content_type: Optional[str] = None


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

        Yields:
            Byte chunks of the response body (SSE format).  For non-2xx upstream
            responses the generator emits a single OpenAI-spec error SSE frame
            followed by ``data: [DONE]`` and then stops.
        """
        # Force streaming
        payload = self._streaming_payload(url, payload)

        logger.info(f"Streaming request to {url}")

        request_kwargs = self._request_kwargs(payload)
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("POST", url, headers=headers, **request_kwargs) as resp:
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

                try:
                    # Preserve upstream byte framing. In particular, SSE uses
                    # blank lines to delimit events; aiter_lines() would discard
                    # those separators and merge transcription events.
                    async for chunk in resp.aiter_bytes():
                        if chunk:
                            yield chunk
                except Exception as exc:
                    # Mid-stream error: append an error SSE frame so clients
                    # can detect the problem without a silent stream cut-off.
                    logger.error(f"Mid-stream error from {url}: {exc}")
                    _, error_body = coerce_upstream_error(500, {"error": str(exc)})
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
        # This execution path is also used for async jobs, which cannot relay
        # an upstream event stream. Keep the forwarded JSON or multipart form
        # unambiguously non-streaming.
        payload = set_payload_field(payload, "stream", False)

        logger.info(f"Sync request to {url}")

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    headers=headers,
                    timeout=None,  # No timeout to handle long-running LLM requests and cold starts
                    **self._request_kwargs(payload),
                )

            logger.debug(f"Response status: {response.status_code}, headers: {dict(response.headers)}")

            content_type = response.headers.get("content-type")
            raw_body = None
            is_successful_multipart = response.status_code < 400 and is_multipart_payload(payload)
            media_type = (content_type or "").partition(";")[0].strip().lower()
            is_json_response = not media_type or media_type == "application/json" or media_type.endswith("+json")
            if is_successful_multipart and not is_json_response:
                body = response.text
                raw_body = response.content
            else:
                try:
                    body = response.json()
                except json.JSONDecodeError:
                    if is_successful_multipart:
                        body = response.text
                        raw_body = response.content
                    elif response.status_code < 400:
                        logger.error(
                            f"Failed to decode JSON from {url}, "
                            f"status={response.status_code}, text={response.text[:200]}"
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
                    else:
                        body = {"error": response.text[:500]}

            usage = self._extract_usage(body)

            is_success = response.status_code < 400
            error_msg = body.get("error") if not is_success and isinstance(body, dict) else None

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
                raw_body=raw_body,
                content_type=content_type,
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
        if is_multipart_payload(payload) or Executor._is_responses_url(url):
            return set_payload_field(payload, "stream", True)
        return {**payload, "stream": True, "stream_options": {"include_usage": True}}

    @staticmethod
    def _request_kwargs(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Build mutually exclusive ``httpx`` JSON or multipart arguments."""
        if is_multipart_payload(payload):
            data, files = httpx_multipart_parts(payload)
            # Passing a list of tuples through httpx's ``data=`` uses a
            # synchronous iterator, which AsyncClient rejects. Text form parts
            # represented as filename-less ``files=`` tuples preserve duplicate
            # OpenAI fields (e.g. timestamp_granularities[]) and remain async-safe.
            form_parts = [(name, (None, value)) for name, value in data]
            return {"files": [*form_parts, *files]}
        return {"json": payload}

    @staticmethod
    def _is_responses_url(url: str) -> bool:
        """Whether the upstream URL targets a Responses API endpoint."""
        path = (url or "").split("?", 1)[0].rstrip("/")
        return path.endswith("/responses")

    @staticmethod
    def _extract_usage(response: Any) -> Dict[str, int]:
        """Extract usage tokens from response body."""
        if not isinstance(response, dict):
            return {}
        usage = response.get("usage", {})
        result = {}
        for key, value in usage.items():
            if isinstance(value, int) and "details" not in key:
                result[key] = value
        return result
