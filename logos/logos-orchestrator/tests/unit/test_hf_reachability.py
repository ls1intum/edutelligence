import importlib

import httpx
import pytest
from fastapi import HTTPException
from huggingface_hub.errors import GatedRepoError, HFValidationError, RepositoryNotFoundError

from logos import hf_reachability
from logos.dbutils.dbrequest import HfReachabilityRequest


@pytest.fixture
def hub(monkeypatch):
    """Serve the auth-check request from ``hub.handler``; record each request."""

    class _Hub:
        requests: list[httpx.Request] = []
        timeouts: list[httpx.Timeout] = []

        @staticmethod
        def handler(request):
            return httpx.Response(200, json={})

    def _client():
        client = httpx.AsyncClient(
            timeout=hf_reachability._TIMEOUT_S,
            transport=httpx.MockTransport(lambda request: _Hub.requests.append(request) or _Hub.handler(request)),
        )
        _Hub.timeouts.append(client.timeout)
        return client

    monkeypatch.setattr(hf_reachability, "_new_client", _client)
    monkeypatch.delenv("HF_TOKEN", raising=False)
    return _Hub


def _raise_for(error):
    def _raise(response, endpoint_name=None):
        if response.status_code >= 400:
            raise error

    return _raise


async def test_reachable_repository(hub):
    result = await hf_reachability.check_hf_reachability("  org/model ")

    assert result.hf_repo_id == "org/model"
    assert result.status == hf_reachability.STATUS_REACHABLE
    assert result.reason_code is None
    assert [str(r.url) for r in hub.requests] == ["https://huggingface.co/api/models/org/model/auth-check"]
    assert "authorization" not in hub.requests[0].headers


async def test_request_is_bounded_by_the_configured_timeout(hub, monkeypatch):
    monkeypatch.setattr(hf_reachability, "_TIMEOUT_S", 3.0)

    await hf_reachability.check_hf_reachability("org/model")

    assert hub.timeouts[0].read == 3.0


@pytest.mark.parametrize(
    ("status_code", "error", "reason_code"),
    [
        (403, GatedRepoError("gated"), hf_reachability.REASON_MODEL_GATED),
        (401, RepositoryNotFoundError("missing"), hf_reachability.REASON_MODEL_NOT_FOUND_OR_UNAUTHORIZED),
    ],
)
async def test_rejections_use_the_worker_reason_codes(hub, monkeypatch, status_code, error, reason_code):
    hub.handler = staticmethod(lambda request: httpx.Response(status_code))
    monkeypatch.setattr("huggingface_hub.utils.hf_raise_for_status", _raise_for(error))

    result = await hf_reachability.check_hf_reachability("org/model")

    assert result.status == hf_reachability.STATUS_REJECTED
    assert result.reason_code == reason_code


async def test_malformed_repo_id_is_rejected_before_asking_the_hub(hub, monkeypatch):
    def _invalid(repo_id):
        raise HFValidationError(f"bad id {repo_id}")

    monkeypatch.setattr("huggingface_hub.utils.validate_repo_id", _invalid)

    result = await hf_reachability.check_hf_reachability("bad//repo id")

    assert result.status == hf_reachability.STATUS_REJECTED
    assert result.reason_code == hf_reachability.REASON_INVALID_REPO_ID
    assert hub.requests == []


async def test_hub_failure_is_unknown_not_a_verdict(hub):
    def _refuse(request):
        raise httpx.ConnectError("proxy.internal.example:3128 refused", request=request)

    hub.handler = staticmethod(_refuse)

    result = await hf_reachability.check_hf_reachability("org/model")

    assert result.status == hf_reachability.STATUS_UNKNOWN
    assert result.reason_code is None
    assert "proxy.internal" not in result.detail


async def test_slow_hub_times_out_as_unknown(hub):
    def _slow(request):
        raise httpx.ReadTimeout("timed out", request=request)

    hub.handler = staticmethod(_slow)

    result = await hf_reachability.check_hf_reachability("org/model")

    assert result.status == hf_reachability.STATUS_UNKNOWN
    assert "did not answer" in result.detail


async def test_central_hf_token_is_used(hub, monkeypatch):
    monkeypatch.setenv("HF_TOKEN", " hf_secret ")

    await hf_reachability.check_hf_reachability("org/model")

    assert hub.requests[0].headers["authorization"] == "Bearer hf_secret"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("7.5", 7.5), ("", 15.0), ("abc", 15.0), ("0", 15.0), ("-3", 15.0), ("nan", 15.0), ("inf", 15.0)],
)
def test_timeout_env_falls_back_to_default_when_invalid(monkeypatch, raw, expected):
    monkeypatch.setenv("LOGOS_HF_REACHABILITY_TIMEOUT_S", raw)

    assert hf_reachability._timeout_from_env() == expected


async def test_endpoint_requires_the_internal_secret(monkeypatch):
    internal = importlib.import_module("logos.routers.internal")
    monkeypatch.setattr(internal, "_INTERNAL_SECRET", "expected")

    class _Request:
        headers = {"authorization": "Bearer wrong"}

    with pytest.raises(HTTPException) as error:
        await internal.internal_hf_reachability(HfReachabilityRequest(hf_repo_id="org/model"), _Request())
    assert error.value.status_code == 401


async def test_endpoint_returns_the_check_result(hub, monkeypatch):
    internal = importlib.import_module("logos.routers.internal")
    monkeypatch.setattr(internal, "_require_internal_secret", lambda _: None)
    hub.handler = staticmethod(lambda request: httpx.Response(403))
    monkeypatch.setattr("huggingface_hub.utils.hf_raise_for_status", _raise_for(GatedRepoError("gated")))

    response = await internal.internal_hf_reachability(HfReachabilityRequest(hf_repo_id="org/model"), object())

    body = response.body.decode()
    assert '"status":"rejected"' in body
    assert '"reason_code":"model-gated"' in body
    assert '"hf_repo_id":"org/model"' in body


def test_request_rejects_an_empty_repo_id():
    with pytest.raises(ValueError):
        HfReachabilityRequest(hf_repo_id="")
