import importlib
import time

import httpx
import pytest
from fastapi import HTTPException
from huggingface_hub.errors import GatedRepoError, HFValidationError, RepositoryNotFoundError

from logos import hf_reachability
from logos.dbutils.dbrequest import HfReachabilityRequest


class _FakeApi:
    raises: Exception | None = None
    calls: list[tuple[str, object]] = []

    def auth_check(self, repo_id, *, token=None):
        _FakeApi.calls.append((repo_id, token))
        if _FakeApi.raises is not None:
            raise _FakeApi.raises


@pytest.fixture
def fake_api(monkeypatch):
    _FakeApi.raises = None
    _FakeApi.calls = []
    monkeypatch.setattr("huggingface_hub.HfApi", _FakeApi)
    monkeypatch.delenv("HF_TOKEN", raising=False)
    return _FakeApi


async def test_reachable_repository(fake_api):
    result = await hf_reachability.check_hf_reachability("  org/model ")

    assert result.hf_repo_id == "org/model"
    assert result.status == hf_reachability.STATUS_REACHABLE
    assert result.reason_code is None
    assert fake_api.calls == [("org/model", False)]


@pytest.mark.parametrize(
    ("error", "reason_code"),
    [
        (GatedRepoError("gated"), hf_reachability.REASON_MODEL_GATED),
        (RepositoryNotFoundError("missing"), hf_reachability.REASON_MODEL_NOT_FOUND_OR_UNAUTHORIZED),
    ],
)
async def test_rejections_use_the_worker_reason_codes(fake_api, error, reason_code):
    fake_api.raises = error

    result = await hf_reachability.check_hf_reachability("org/model")

    assert result.status == hf_reachability.STATUS_REJECTED
    assert result.reason_code == reason_code


async def test_malformed_repo_id_is_rejected_before_asking_the_hub(fake_api, monkeypatch):
    def _invalid(repo_id):
        raise HFValidationError(f"bad id {repo_id}")

    monkeypatch.setattr("huggingface_hub.utils.validate_repo_id", _invalid)

    result = await hf_reachability.check_hf_reachability("bad//repo id")

    assert result.status == hf_reachability.STATUS_REJECTED
    assert result.reason_code == hf_reachability.REASON_INVALID_REPO_ID
    assert fake_api.calls == []


async def test_hub_failure_is_unknown_not_a_verdict(fake_api):
    fake_api.raises = httpx.ConnectError("proxy.internal.example:3128 refused")

    result = await hf_reachability.check_hf_reachability("org/model")

    assert result.status == hf_reachability.STATUS_UNKNOWN
    assert result.reason_code is None
    assert "proxy.internal" not in result.detail


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("7.5", 7.5), ("", 15.0), ("abc", 15.0), ("0", 15.0), ("-3", 15.0), ("nan", 15.0), ("inf", 15.0)],
)
def test_timeout_env_falls_back_to_default_when_invalid(monkeypatch, raw, expected):
    monkeypatch.setenv("LOGOS_HF_REACHABILITY_TIMEOUT_S", raw)

    assert hf_reachability._timeout_from_env() == expected


async def test_slow_hub_times_out_as_unknown(fake_api, monkeypatch):
    monkeypatch.setattr(hf_reachability, "_TIMEOUT_S", 0.05)
    monkeypatch.setattr(_FakeApi, "auth_check", lambda self, repo_id, token=None: time.sleep(0.5))

    result = await hf_reachability.check_hf_reachability("org/model")

    assert result.status == hf_reachability.STATUS_UNKNOWN
    assert "did not answer" in result.detail


async def test_central_hf_token_is_used(fake_api, monkeypatch):
    monkeypatch.setenv("HF_TOKEN", " hf_secret ")

    await hf_reachability.check_hf_reachability("org/model")

    assert fake_api.calls == [("org/model", "hf_secret")]


async def test_endpoint_requires_the_internal_secret(monkeypatch):
    internal = importlib.import_module("logos.routers.internal")
    monkeypatch.setattr(internal, "_INTERNAL_SECRET", "expected")

    class _Request:
        headers = {"authorization": "Bearer wrong"}

    with pytest.raises(HTTPException) as error:
        await internal.internal_hf_reachability(HfReachabilityRequest(hf_repo_id="org/model"), _Request())
    assert error.value.status_code == 401


async def test_endpoint_returns_the_check_result(fake_api, monkeypatch):
    internal = importlib.import_module("logos.routers.internal")
    monkeypatch.setattr(internal, "_require_internal_secret", lambda _: None)
    fake_api.raises = GatedRepoError("gated")

    response = await internal.internal_hf_reachability(HfReachabilityRequest(hf_repo_id="org/model"), object())

    body = response.body.decode()
    assert '"status":"rejected"' in body
    assert '"reason_code":"model-gated"' in body
    assert '"hf_repo_id":"org/model"' in body


def test_request_rejects_an_empty_repo_id():
    with pytest.raises(ValueError):
        HfReachabilityRequest(hf_repo_id="")
