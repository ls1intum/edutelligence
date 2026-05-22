from __future__ import annotations

import pytest
from unittest.mock import MagicMock
from fastapi import HTTPException
import logos.role_auth as role_auth

def _make_request(key: str) -> MagicMock:
    req = MagicMock()
    req.headers = {"logos-key": key}
    return req

@pytest.fixture(autouse=True)
def patch_auth(monkeypatch):
    ctx = MagicMock()
    ctx.key_value = "key"
    ctx.api_key_id = 1
    ctx.role = None
    monkeypatch.setattr(role_auth, "authenticate_api_key", lambda h: ctx)

def test_require_logos_admin_key_passes_for_admin(monkeypatch):
    db = MagicMock()
    db.get_user_by_api_key.return_value = {"role": "logos_admin"}
    role_auth.require_logos_admin_key("key", db)

def test_require_logos_admin_key_rejects_app_admin(monkeypatch):
    db = MagicMock()
    db.get_user_by_api_key.return_value = {"role": "app_admin"}
    with pytest.raises(Exception):
        role_auth.require_logos_admin_key("key", db)

def test_require_logos_admin_key_rejects_service_key(monkeypatch):
    db = MagicMock()
    db.get_user_by_api_key.return_value = None
    with pytest.raises(Exception):
        role_auth.require_logos_admin_key("key", db)

def test_require_app_admin_or_above_passes_for_app_admin(monkeypatch):
    monkeypatch.setattr(role_auth, "_fetch_role", lambda key: "app_admin")
    result = role_auth.require_app_admin_or_above(_make_request("key"))
    assert result == "key"

def test_require_app_admin_or_above_passes_for_logos_admin(monkeypatch):
    monkeypatch.setattr(role_auth, "_fetch_role", lambda key: "logos_admin")
    result = role_auth.require_app_admin_or_above(_make_request("key"))
    assert result == "key"

def test_require_app_admin_or_above_rejects_developer(monkeypatch):
    monkeypatch.setattr(role_auth, "_fetch_role", lambda key: "app_developer")
    with pytest.raises(HTTPException) as exc:
        role_auth.require_app_admin_or_above(_make_request("key"))
    assert exc.value.status_code == 403

def test_require_logos_admin_or_team_owner_passes_for_logos_admin(monkeypatch):
    monkeypatch.setattr(role_auth, "_fetch_role", lambda key: "logos_admin")
    db = MagicMock()
    result = role_auth.require_logos_admin_or_team_owner(42, _make_request("key"), db)
    assert result == "key"
    db.is_team_owner.assert_not_called()


def test_require_logos_admin_or_team_owner_passes_for_app_admin_owner(monkeypatch):
    monkeypatch.setattr(role_auth, "_fetch_role", lambda key: "app_admin")
    db = MagicMock()
    db.is_team_owner.return_value = True
    result = role_auth.require_logos_admin_or_team_owner(42, _make_request("key"), db)
    assert result == "key"


def test_require_logos_admin_or_team_owner_rejects_app_admin_non_owner(monkeypatch):
    monkeypatch.setattr(role_auth, "_fetch_role", lambda key: "app_admin")
    db = MagicMock()
    db.is_team_owner.return_value = False
    with pytest.raises(HTTPException) as exc:
        role_auth.require_logos_admin_or_team_owner(42, _make_request("key"), db)
    assert exc.value.status_code == 403


def test_require_logos_admin_or_team_owner_rejects_developer(monkeypatch):
    monkeypatch.setattr(role_auth, "_fetch_role", lambda key: "app_developer")
    db = MagicMock()
    with pytest.raises(HTTPException) as exc:
        role_auth.require_logos_admin_or_team_owner(42, _make_request("key"), db)
    assert exc.value.status_code == 403