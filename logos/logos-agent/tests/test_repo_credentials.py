"""Interoperability of LOGOS_REPO_CREDENTIALS_KEY decoding with Java Base64."""

from __future__ import annotations

import base64

from app import repo_credentials


def test_aes_key_accepts_url_safe_alphabet(monkeypatch):
    # 32 bytes whose standard encoding would contain +/; use URL-safe form
    # with -/_ so Java Locale.ROOT Base64 URL decoder accepts it too.
    raw = bytes([0xFF, 0xFF, 0xFF]) + bytes(29)
    url_safe = base64.urlsafe_b64encode(raw).decode("ascii")
    assert "-" in url_safe or "_" in url_safe
    monkeypatch.setenv(repo_credentials.ENV_KEY, url_safe)
    monkeypatch.delenv(repo_credentials.ENV_DEV_FALLBACK, raising=False)
    key = repo_credentials._aes_key()
    assert key == raw


def test_aes_key_rejects_without_secret(monkeypatch):
    monkeypatch.delenv(repo_credentials.ENV_KEY, raising=False)
    monkeypatch.delenv(repo_credentials.ENV_DEV_FALLBACK, raising=False)
    assert repo_credentials._aes_key() is None
