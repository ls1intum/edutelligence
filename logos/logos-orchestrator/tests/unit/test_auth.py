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


def test_authenticate_api_key_preserves_zero_default_priority(monkeypatch):
    """A key without a configured priority stays 0 (falls back to policy in the pipeline)."""
    row = _api_key_row("lg-test-zero")
    row["default_priority"] = 0

    _patch_db(monkeypatch, row)

    ctx = auth.authenticate_api_key({"logos-key": "lg-test-zero"})

    assert ctx.default_priority == 0


def test_authenticate_api_key_missing_default_priority_defaults_to_zero(monkeypatch):
    row = _api_key_row("lg-test-noprio")
    del row["default_priority"]

    _patch_db(monkeypatch, row)

    ctx = auth.authenticate_api_key({"logos-key": "lg-test-noprio"})

    assert ctx.default_priority == 0


def test_authenticate_logos_key_shim_returns_key_and_api_key_id(monkeypatch):
    _patch_db(monkeypatch, _api_key_row("lg-test-abc"))

    ctx = auth.authenticate_api_key({"logos-key": "lg-test-abc"})

    assert ctx.key_value == "lg-test-abc"
    assert ctx.api_key_id == 5


class _CredentialDB:
    """A database in which the header value is a credential, not a key value."""

    def __init__(self, row):
        self.row = row
        self.seen_by_id = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_api_key_by_value(self, key_value):
        return None  # it is a credential, so the plain lookup finds nothing

    def get_api_key_by_id(self, api_key_id):
        self.seen_by_id = api_key_id
        return self.row if self.row is not None and self.row["id"] == api_key_id else None


def _patch_credential_db(monkeypatch, row):
    from logos import batch_credential

    fake = _CredentialDB(row)
    monkeypatch.setattr(auth, "DBManager", lambda: fake)
    monkeypatch.setenv("LOGOS_INTERNAL_SECRET", "internal")
    credential, _ = batch_credential.issue_batch_credential(row["id"]) if row else (None, None)
    return fake, credential


def test_a_scoped_batch_credential_resolves_to_the_keys_own_row(monkeypatch):
    # The proxy presents the credential in place of the key value; the
    # context carries the key's own value, because the batch lines re-enter
    # the pipeline as the key.
    fake, credential = _patch_credential_db(monkeypatch, _api_key_row("lg-secret-value"))

    ctx = auth.authenticate_batch_api_key({"logos_key": credential})

    assert fake.seen_by_id == 5
    assert ctx.key_value == "lg-secret-value"
    assert ctx.api_key_id == 5


def test_the_batch_path_still_accepts_the_plain_key_value(monkeypatch):
    # Scripts call the Batch API with the key itself; the credential is an
    # addition for the internal proxy, not a replacement.
    _patch_db(monkeypatch, _api_key_row("lg-secret-value"))

    ctx = auth.authenticate_batch_api_key({"logos_key": "lg-secret-value"})

    assert ctx.key_value == "lg-secret-value"
    assert ctx.api_key_id == 5


def test_a_dead_or_tampered_credential_is_a_401_like_any_bad_key(monkeypatch):
    fake, credential = _patch_credential_db(monkeypatch, _api_key_row("lg-secret-value"))

    # The key the credential names is gone (revoked after the hand-out): the
    # row lookup is what kills it, at presentation time.
    fake.row = None
    with pytest.raises(HTTPException) as exc:
        auth.authenticate_batch_api_key({"logos_key": credential})
    assert exc.value.status_code == 401

    # A credential no one here signed: it never reaches the key lookup.
    fake.row = _api_key_row("lg-secret-value")
    fake.seen_by_id = None
    with pytest.raises(HTTPException) as exc:
        auth.authenticate_batch_api_key({"logos_key": credential + "x"})
    assert exc.value.status_code == 401
    assert fake.seen_by_id is None


def test_the_global_key_auth_refuses_a_batch_credential(monkeypatch):
    # The credential is a batch-only bearer: every other route authenticates
    # with key values alone, so it must 401 there — otherwise it would open
    # ordinary inference (and, for an admin-owned key, the role-gated routes)
    # for its whole TTL.
    fake, credential = _patch_credential_db(monkeypatch, _api_key_row("lg-secret-value"))

    with pytest.raises(HTTPException) as exc:
        auth.authenticate_api_key({"logos_key": credential})

    assert exc.value.status_code == 401
    # It is not even resolved: the global path does not know about it.
    assert fake.seen_by_id is None
