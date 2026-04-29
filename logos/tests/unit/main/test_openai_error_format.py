"""Unit tests for logos.errors: openai_error_response, coerce_upstream_error,
classify_upstream_message, and raise_openai_error."""

import json
import pytest
from fastapi import HTTPException
from fastapi.responses import JSONResponse

from logos.errors import (
    classify_upstream_message,
    coerce_upstream_error,
    openai_error_response,
    raise_openai_error,
    UpstreamStreamError,
    _error_type_for_status,
)


# ── _error_type_for_status ───────────────────────────────────────────────────


class TestErrorTypeForStatus:
    def test_400(self):
        assert _error_type_for_status(400) == "invalid_request_error"

    def test_401(self):
        assert _error_type_for_status(401) == "authentication_error"

    def test_403(self):
        assert _error_type_for_status(403) == "permission_error"

    def test_404(self):
        assert _error_type_for_status(404) == "not_found_error"

    def test_409(self):
        assert _error_type_for_status(409) == "conflict_error"

    def test_422(self):
        assert _error_type_for_status(422) == "invalid_request_error"

    def test_429(self):
        assert _error_type_for_status(429) == "rate_limit_error"

    def test_504(self):
        assert _error_type_for_status(504) == "timeout_error"

    def test_500(self):
        assert _error_type_for_status(500) == "api_error"

    def test_502(self):
        assert _error_type_for_status(502) == "api_error"

    def test_unknown_4xx_falls_back_to_invalid_request(self):
        assert _error_type_for_status(418) == "invalid_request_error"

    def test_unknown_5xx_falls_back_to_api_error(self):
        assert _error_type_for_status(503) == "api_error"


# ── classify_upstream_message ────────────────────────────────────────────────


class TestClassifyUpstreamMessage:
    def test_vllm_maximum_context_length(self):
        msg = "This model's maximum context length is 4096 tokens."
        t, c = classify_upstream_message(msg)
        assert t == "invalid_request_error"
        assert c == "context_length_exceeded"

    def test_exceeds_model_maximum_context_length(self):
        msg = "Input exceeds model's maximum context length of 8192 tokens"
        t, c = classify_upstream_message(msg)
        assert t == "invalid_request_error"
        assert c == "context_length_exceeded"

    def test_context_length_exceeded_substring(self):
        msg = "context length exceeded"
        t, c = classify_upstream_message(msg)
        assert t == "invalid_request_error"
        assert c == "context_length_exceeded"

    def test_case_insensitive(self):
        msg = "MAXIMUM CONTEXT LENGTH is 4096"
        t, c = classify_upstream_message(msg)
        assert t == "invalid_request_error"
        assert c == "context_length_exceeded"

    def test_unrecognised_returns_none_none(self):
        t, c = classify_upstream_message("some unrelated error")
        assert t is None
        assert c is None

    def test_empty_string(self):
        t, c = classify_upstream_message("")
        assert t is None
        assert c is None


# ── coerce_upstream_error ────────────────────────────────────────────────────


class TestCoerceUpstreamError:
    """Schema invariant: result always has shape {"error": {"message": str, "type": str, ...}}"""

    def _assert_schema(self, body: dict):
        assert "error" in body, "top-level 'error' key missing"
        err = body["error"]
        assert isinstance(err.get("message"), str), "message must be a string"
        assert isinstance(err.get("type"), str), "type must be a string"

    # ── well-formed OpenAI-shape input ────────────────────────────────────

    def test_preserves_well_formed_error(self):
        body = {"error": {"message": "bad input", "type": "invalid_request_error", "code": "model_not_found"}}
        sc, result = coerce_upstream_error(400, body)
        assert sc == 400
        self._assert_schema(result)
        assert result["error"]["message"] == "bad input"
        assert result["error"]["code"] == "model_not_found"

    def test_preserves_provider_type_when_set(self):
        body = {"error": {"message": "rate limit", "type": "rate_limit_error", "param": None}}
        sc, result = coerce_upstream_error(429, body)
        assert sc == 429
        assert result["error"]["type"] == "rate_limit_error"

    def test_adds_missing_type_from_status(self):
        body = {"error": {"message": "bad input"}}
        sc, result = coerce_upstream_error(400, body)
        assert sc == 400
        assert result["error"]["type"] == "invalid_request_error"

    # ── context-length correction (500 → 400) ────────────────────────────

    def test_context_length_in_well_formed_body_corrects_500_to_400(self):
        body = {"error": {
            "message": "maximum context length is 4096 tokens, got 8000",
            "type": "server_error",
        }}
        sc, result = coerce_upstream_error(500, body)
        assert sc == 400, "must downgrade 500→400 for context-length errors"
        assert result["error"]["type"] == "invalid_request_error"
        assert result["error"]["code"] == "context_length_exceeded"

    def test_context_length_in_raw_string_corrects_500_to_400(self):
        sc, result = coerce_upstream_error(
            500, "maximum context length is 4096, got 5000 tokens"
        )
        assert sc == 400
        self._assert_schema(result)
        assert result["error"]["code"] == "context_length_exceeded"

    def test_context_length_on_400_stays_400(self):
        sc, __result = coerce_upstream_error(
            400, "maximum context length exceeded"
        )
        assert sc == 400

    # ── plain-string body ─────────────────────────────────────────────────

    def test_plain_string_body(self):
        sc, result = coerce_upstream_error(503, "Service unavailable")
        assert sc == 503
        self._assert_schema(result)
        assert "Service unavailable" in result["error"]["message"]

    def test_dict_with_string_error_key(self):
        sc, result = coerce_upstream_error(500, {"error": "internal failure"})
        assert sc == 500
        self._assert_schema(result)
        assert "internal failure" in result["error"]["message"]

    def test_bytes_body(self):
        _sc, result = coerce_upstream_error(500, b"some error bytes")
        self._assert_schema(result)
        assert "some error bytes" in result["error"]["message"]

    def test_none_body(self):
        _sc, result = coerce_upstream_error(500, None)
        self._assert_schema(result)

    def test_truncates_long_messages(self):
        long_msg = "x" * 1000
        __sc, result = coerce_upstream_error(500, long_msg)
        assert len(result["error"]["message"]) <= 503  # 500 chars + "..."


# ── openai_error_response ────────────────────────────────────────────────────


class TestOpenaiErrorResponse:
    def test_basic(self):
        resp = openai_error_response(400, "bad request")
        assert isinstance(resp, JSONResponse)
        assert resp.status_code == 400
        body = json.loads(resp.body)
        assert body["error"]["message"] == "bad request"
        assert body["error"]["type"] == "invalid_request_error"
        assert "param" not in body["error"]
        assert "code" not in body["error"]

    def test_with_code_and_param(self):
        resp = openai_error_response(
            400, "context too long",
            code="context_length_exceeded",
            param="messages",
        )
        body = json.loads(resp.body)
        assert body["error"]["code"] == "context_length_exceeded"
        assert body["error"]["param"] == "messages"

    def test_with_explicit_type(self):
        resp = openai_error_response(200, "ok", type_="custom_type")
        body = json.loads(resp.body)
        assert body["error"]["type"] == "custom_type"

    def test_500_maps_to_api_error(self):
        resp = openai_error_response(500, "internal error")
        body = json.loads(resp.body)
        assert body["error"]["type"] == "api_error"

    def test_status_code_preserved(self):
        resp = openai_error_response(429, "too many requests")
        assert resp.status_code == 429


# ── raise_openai_error ───────────────────────────────────────────────────────


class TestRaiseOpenaiError:
    def test_raises_http_exception(self):
        with pytest.raises(HTTPException) as exc_info:
            raise_openai_error(404, "Not found", code="model_not_found")
        exc = exc_info.value
        assert exc.status_code == 404
        assert isinstance(exc.detail, dict)
        assert "error" in exc.detail
        assert exc.detail["error"]["code"] == "model_not_found"
        assert exc.detail["error"]["type"] == "not_found_error"

    def test_with_param(self):
        with pytest.raises(HTTPException) as exc_info:
            raise_openai_error(422, "Invalid param", param="model", code="invalid_model")
        assert exc_info.value.detail["error"]["param"] == "model"

    def test_explicit_type_overrides_derivation(self):
        with pytest.raises(HTTPException) as exc_info:
            raise_openai_error(400, "custom", type_="my_error_type")
        assert exc_info.value.detail["error"]["type"] == "my_error_type"


# ── UpstreamStreamError ──────────────────────────────────────────────────────


class TestUpstreamStreamError:
    def test_attributes(self):
        err = UpstreamStreamError(429, {"error": {"message": "rate limited"}})
        assert err.status_code == 429
        assert err.body == {"error": {"message": "rate limited"}}
        assert "429" in str(err)
