"""The /internal/batch_credentials endpoint.

The Spring webservice names the key by id — its ownership check already ran
against the caller — and gets back a short-lived credential bound to that one
key. The user's key value never crosses the internal hop.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from logos import batch_credential
from logos.routers import internal as main_mod

KEY_ROW = {
    "id": 5,
    "key_value": "lg-5",
    "name": "k",
    "key_type": "application",
    "team_id": 2,
    "user_id": 3,
    "environment": "prod",
    "log": "BILLING",
    "settings": None,
    "default_priority": 1,
}


def _make_request(body: str, authorization: str = "") -> MagicMock:
    request = MagicMock()
    request.headers.get = lambda key, default="": authorization if key == "authorization" else default

    async def _json():
        return json.loads(body)

    request.json = _json
    return request


class _KeyDB:
    def __init__(self, row):
        self.row = row

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_api_key_by_id(self, api_key_id):
        return self.row if self.row is not None and self.row["id"] == api_key_id else None


def _patch(monkeypatch, row):
    monkeypatch.setattr(main_mod, "_INTERNAL_SECRET", "secret")
    monkeypatch.setattr(main_mod, "DBManager", lambda: _KeyDB(row))
    monkeypatch.setenv("LOGOS_INTERNAL_SECRET", "secret")


@pytest.mark.asyncio
async def test_the_endpoint_requires_the_internal_secret(monkeypatch):
    monkeypatch.setattr(main_mod, "_INTERNAL_SECRET", None)
    with pytest.raises(HTTPException) as exc:
        await main_mod.internal_batch_credentials(_make_request('{"api_key_id": 5}'))
    assert exc.value.status_code == 403

    _patch(monkeypatch, None)
    with pytest.raises(HTTPException) as exc:
        await main_mod.internal_batch_credentials(_make_request('{"api_key_id": 5}', authorization="Bearer wrong"))
    assert exc.value.status_code == 401


@pytest.mark.parametrize(
    "body",
    [
        "{}",  # no id
        '{"api_key_id": "5"}',  # not an int
        '{"api_key_id": true}',  # a bool is an int in Python and not an id
        "[5]",  # not an object
    ],
)
@pytest.mark.asyncio
async def test_a_body_without_an_integer_key_id_is_a_400(monkeypatch, body):
    _patch(monkeypatch, KEY_ROW)
    with pytest.raises(HTTPException) as exc:
        await main_mod.internal_batch_credentials(_make_request(body, authorization="Bearer secret"))
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_a_key_the_orchestrator_does_not_know_is_a_404(monkeypatch):
    _patch(monkeypatch, None)
    with pytest.raises(HTTPException) as exc:
        await main_mod.internal_batch_credentials(_make_request('{"api_key_id": 5}', authorization="Bearer secret"))
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_the_credential_comes_back_bound_to_the_named_key(monkeypatch):
    _patch(monkeypatch, KEY_ROW)

    result = await main_mod.internal_batch_credentials(
        _make_request('{"api_key_id": 5}', authorization="Bearer secret")
    )

    assert result["expires_in"] == batch_credential.BATCH_CREDENTIAL_TTL_S
    # The answer is a credential, not the key: the value stays in the database.
    assert "lg-5" not in result["credential"]
    assert batch_credential.resolve_batch_credential(result["credential"]) == 5
