from __future__ import annotations

import pytest
from fastapi import HTTPException

from logos import auth


def _api_key_row(key: str = "lg-test-abc") -> dict:
    return {
        "id": 5,
        "key_value": key,
        "name": "My Key",
        "key_type": "application",
        "team_id": 2,
        "user_id": 3,
        "environment": "prod",
        "log": "BILLING",
        "settings": None,
        "default_priority": 10,
    }


class _FakeDBManager:
    def __init__(self, row):
        self.row = row
        self.seen_key = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get_api_key_by_value(self, key_value: str):
        self.seen_key = key_value
        return self.row


def _patch_db(monkeypatch, row):
    fake_db = _FakeDBManager(row)
    monkeypatch.setattr(auth, "DBManager", lambda: fake_db)
    return fake_db


def test_authenticate_api_key_returns_auth_context(monkeypatch):
    fake_db = _patch_db(monkeypatch, _api_key_row("lg-test-abc"))

    ctx = auth.authenticate_api_key({"logos-key": "lg-test-abc"})

    assert fake_db.seen_key == "lg-test-abc"
    assert ctx.key_value == "lg-test-abc"
    assert ctx.api_key_id == 5
    assert ctx.api_key_name == "My Key"
    assert ctx.key_type == "application"
    assert ctx.team_id == 2
    assert ctx.user_id == 3
    assert ctx.environment == "prod"
    assert ctx.log_level == "BILLING"
    assert ctx.settings == {}
    assert ctx.default_priority == 10


def test_authenticate_api_key_invalid_key_raises_401(monkeypatch):
    fake_db = _patch_db(monkeypatch, None)

    with pytest.raises(HTTPException) as exc:
        auth.authenticate_api_key({"logos-key": "bad-key"})

    assert fake_db.seen_key == "bad-key"
    assert exc.value.status_code == 401


def test_authenticate_api_key_missing_key_raises_401(monkeypatch):
    _patch_db(monkeypatch, None)

    with pytest.raises(HTTPException) as exc:
        auth.authenticate_api_key({})

    assert exc.value.status_code == 401


def test_authenticate_logos_key_shim_returns_key_and_api_key_id(monkeypatch):
    _patch_db(monkeypatch, _api_key_row("lg-test-abc"))

    ctx = auth.authenticate_api_key({"logos-key": "lg-test-abc"})

    assert ctx.key_value == "lg-test-abc"
    assert ctx.api_key_id == 5
