from __future__ import annotations

import pytest
from unittest.mock import MagicMock
from fastapi import HTTPException
from logos import role_auth


def _make_request(key: str) -> MagicMock:
    req = MagicMock()
    req.headers = {"logos-key": key}
    return req

def test_require_logos_admin_key_passes_for_admin(monkeypatch):
    monkeypatch.setattr(
        role_auth, "_fetch_role", lambda key: "logos_admin"
    )
    role_auth.require_logos_admin_key("admin-key")

def test_require_logos_admin_key_rejects_app_admin(monkeypatch):
    monkeypatch.setattr(
        role_auth, "_fetch_role", lambda key: "app_admin"
    )
    with pytest.raises(HTTPException) as exc:
        role_auth.require_logos_admin_key("not-admin-key")
    assert exc.value.status_code == 403

def test_require_logos_admin_key_rejects_service_key(monkeypatch):
    monkeypatch.setattr(
        role_auth, "_fetch_role", lambda key: None
    )
    with pytest.raises(HTTPException) as exc:
        role_auth.require_logos_admin_key("service-key")
    assert exc.value.status_code == 403

def test_require_app_admin_or_above_passes_for_app_admin(monkeypatch):
    monkeypatch.setattr(role_auth, "authenticate_logos_key", lambda h: ("key", 1))
    monkeypatch.setattr(role_auth, "_fetch_role", lambda key: "app_admin")
    result = role_auth.require_app_admin_or_above(_make_request("key"))
    assert result == "key"

def test_require_app_admin_or_above_passes_for_logos_admin(monkeypatch):
    monkeypatch.setattr(role_auth, "authenticate_logos_key", lambda h: ("key", 1))
    monkeypatch.setattr(role_auth, "_fetch_role", lambda key: "logos_admin")
    result = role_auth.require_app_admin_or_above(_make_request("key"))
    assert result == "key"

def test_require_app_admin_or_above_rejects_developer(monkeypatch):
    monkeypatch.setattr(role_auth, "authenticate_logos_key", lambda h: ("key", 1))
    monkeypatch.setattr(role_auth, "_fetch_role", lambda key: "app_developer")
    with pytest.raises(HTTPException) as exc:
        role_auth.require_app_admin_or_above(_make_request("key"))
    assert exc.value.status_code == 403