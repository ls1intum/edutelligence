"""OpenAI-spec error response helpers.

Every user-facing error from Logos's API must conform to the OpenAI error
shape so that OpenAI-spec clients (openai-python, opencode, …) can correctly
decide whether to retry or surface the error to the user.

Shape::

    {"error": {"message": "...", "type": "...", "param": "...", "code": "..."}}
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import HTTPException
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class UpstreamStreamError(Exception):
    """Raised by ``Executor.execute_streaming`` when the upstream returns a
    non-2xx status *before* emitting any SSE chunks.

    Catching this in the streaming caller allows it to return a proper
    ``JSONResponse`` (with the correct HTTP status code) rather than a
    ``StreamingResponse`` with an embedded error frame and HTTP 200.
    """

    def __init__(self, status_code: int, body: Any) -> None:
        super().__init__(f"Upstream returned HTTP {status_code}")
        self.status_code = status_code
        self.body = body


# ── Status-code → OpenAI error type mapping ──────────────────────────────────

_STATUS_TO_TYPE: dict[int, str] = {
    400: "invalid_request_error",
    401: "authentication_error",
    403: "permission_error",
    404: "not_found_error",
    409: "conflict_error",
    422: "invalid_request_error",
    429: "rate_limit_error",
    504: "timeout_error",
}
_DEFAULT_TYPE = "api_error"  # 5xx and anything else not in the table


def _error_type_for_status(status_code: int) -> str:
    """Return the OpenAI error ``type`` string for *status_code*."""
    if status_code in _STATUS_TO_TYPE:
        return _STATUS_TO_TYPE[status_code]
    if 400 <= status_code < 500:
        return "invalid_request_error"
    return _DEFAULT_TYPE


# ── Pattern-based classification ─────────────────────────────────────────────

_CTX_LENGTH_PATTERNS = (
    "maximum context length",
    "exceeds model's maximum context length",
    "exceeds the model's context window",
    "context length exceeded",
    "this model's maximum context length",
)


def classify_upstream_message(message: str) -> tuple[str | None, str | None]:
    """Return ``(type, code)`` for a well-known upstream error message.

    Currently detects:

    - vLLM / OpenAI context-length errors →
      ``("invalid_request_error", "context_length_exceeded")``

    Returns ``(None, None)`` for unrecognised messages.
    """
    lower = message.lower()
    for pat in _CTX_LENGTH_PATTERNS:
        if pat in lower:
            return ("invalid_request_error", "context_length_exceeded")
    return (None, None)


# ── Error normalisation ───────────────────────────────────────────────────────


def coerce_upstream_error(status_code: int, body: Any) -> tuple[int, dict]:
    """Normalise an upstream provider response to an OpenAI-shape error dict.

    Also corrects the HTTP status code when the upstream was incorrectly
    sending a 5xx for a context-length exceeded error (downgraded to 400).

    Args:
        status_code: HTTP status code from the upstream.
        body:        Response body – may be a dict (already OpenAI-shaped or
                     not), a string, bytes, or anything else.

    Returns:
        ``(corrected_status_code, {"error": {"message": …, "type": …, …}})``
    """
    # ── 1. Try to extract an existing OpenAI-shape error ─────────────────
    if isinstance(body, dict):
        existing = body.get("error")
        if isinstance(existing, dict) and isinstance(existing.get("message"), str):
            # Provider already sent an OpenAI-shape error – preserve it,
            # but still apply context-length status correction.
            err: dict[str, Any] = dict(existing)
            err.setdefault("type", _error_type_for_status(status_code))
            # Detect context-length even when the status code is wrong
            inferred_type, inferred_code = classify_upstream_message(err["message"])
            if inferred_code:
                err.setdefault("code", inferred_code)
                if status_code >= 500:
                    status_code = 400
                    err["type"] = inferred_type
            return status_code, {"error": err}

    # ── 2. Synthesise from status code + raw body ─────────────────────────
    if isinstance(body, str):
        raw_message = body
    elif isinstance(body, bytes):
        raw_message = body.decode(errors="replace")
    elif isinstance(body, dict):
        # body has an "error" key but it's a plain string (common in some paths)
        raw_error = body.get("error")
        if isinstance(raw_error, str):
            raw_message = raw_error
        else:
            raw_message = json.dumps(body)
    else:
        raw_message = str(body) if body is not None else ""

    # Trim very long messages to avoid leaking internal details
    if len(raw_message) > 500:
        raw_message = raw_message[:497] + "..."

    inferred_type, inferred_code = classify_upstream_message(raw_message)
    error_type = inferred_type or _error_type_for_status(status_code)

    if inferred_code and status_code >= 500:
        # Upstream sent 500 for a context-length problem – correct to 400
        status_code = 400

    error_obj: dict[str, Any] = {
        "message": raw_message or f"Upstream returned HTTP {status_code}",
        "type": error_type,
    }
    if inferred_code:
        error_obj["code"] = inferred_code

    return status_code, {"error": error_obj}


# ── Response builders ─────────────────────────────────────────────────────────


def openai_error_response(
    status_code: int,
    message: str,
    *,
    code: str | None = None,
    param: str | None = None,
    type_: str | None = None,
) -> JSONResponse:
    """Build a ``JSONResponse`` whose body conforms to the OpenAI error spec.

    Args:
        status_code: HTTP status code for the response.
        message:     Human-readable error message.
        code:        Optional snake_case error code (e.g. ``context_length_exceeded``).
        param:       Optional name of the offending request field.
        type_:       OpenAI error type; derived from *status_code* when omitted.
    """
    error: dict[str, Any] = {
        "message": message,
        "type": type_ or _error_type_for_status(status_code),
    }
    if param is not None:
        error["param"] = param
    if code is not None:
        error["code"] = code
    return JSONResponse(content={"error": error}, status_code=status_code)


def raise_openai_error(
    status_code: int,
    message: str,
    *,
    code: str | None = None,
    param: str | None = None,
    type_: str | None = None,
) -> None:
    """Raise an ``HTTPException`` whose *detail* is a ready-made OpenAI error dict.

    The global exception handler in ``main.py`` recognises ``detail`` dicts that
    already carry an ``"error"`` key and passes them through unchanged.
    """
    error: dict[str, Any] = {
        "message": message,
        "type": type_ or _error_type_for_status(status_code),
    }
    if param is not None:
        error["param"] = param
    if code is not None:
        error["code"] = code
    raise HTTPException(status_code=status_code, detail={"error": error})
