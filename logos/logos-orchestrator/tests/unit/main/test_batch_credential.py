"""Scoped batch credentials: what the proxy sends instead of the user's key.

The shipped setup reaches the orchestrator over plain HTTP, so the user's
long-lived key value may not cross that hop. The credential is the substitute:
bound to one key, short-lived, and verifiable without trusting the wire.
"""

from __future__ import annotations

import datetime

import pytest

from logos import batch_credential


@pytest.fixture
def secret(monkeypatch):
    monkeypatch.setenv("LOGOS_INTERNAL_SECRET", "internal-secret")


def test_issue_and_resolve_round_trip(secret):
    credential, ttl = batch_credential.issue_batch_credential(5)
    assert ttl == batch_credential.BATCH_CREDENTIAL_TTL_S
    assert credential.startswith(batch_credential.BATCH_CREDENTIAL_PREFIX)
    assert batch_credential.resolve_batch_credential(credential) == 5


def test_a_credential_only_works_with_the_same_secret(monkeypatch):
    monkeypatch.setenv("LOGOS_INTERNAL_SECRET", "first")
    credential, _ = batch_credential.issue_batch_credential(5)
    monkeypatch.setenv("LOGOS_INTERNAL_SECRET", "second")
    assert batch_credential.resolve_batch_credential(credential) is None


def test_a_credential_stops_at_its_expiry(secret):
    past = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        seconds=batch_credential.BATCH_CREDENTIAL_TTL_S + 10
    )
    credential, _ = batch_credential.issue_batch_credential(5, now=past)
    assert batch_credential.resolve_batch_credential(credential) is None


def test_a_credential_a_few_seconds_old_is_still_live(secret):
    past = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=1)
    credential, _ = batch_credential.issue_batch_credential(5, now=past)
    assert batch_credential.resolve_batch_credential(credential) == 5


def test_two_credentials_for_one_key_are_distinct(secret):
    a, _ = batch_credential.issue_batch_credential(5)
    b, _ = batch_credential.issue_batch_credential(5)
    assert a != b  # the nonce keeps the two hand-outs distinguishable


def test_a_tampered_credential_does_not_resolve(secret):
    credential, _ = batch_credential.issue_batch_credential(5)
    prefix, signature = credential.rsplit(".", 1)
    flipped = ("A" if signature[0] != "A" else "B") + signature[1:]
    assert batch_credential.resolve_batch_credential(prefix + flipped) is None


def test_values_that_are_not_credentials_resolve_to_none(secret):
    assert batch_credential.resolve_batch_credential("lg-plain-key") is None
    assert batch_credential.resolve_batch_credential(batch_credential.BATCH_CREDENTIAL_PREFIX + "garbage") is None
    assert batch_credential.resolve_batch_credential("") is None
    assert batch_credential.resolve_batch_credential(None) is None


def test_without_a_secret_nothing_is_issued_or_verified(monkeypatch):
    monkeypatch.delenv("LOGOS_INTERNAL_SECRET", raising=False)
    with pytest.raises(RuntimeError):
        batch_credential.issue_batch_credential(5)
    assert batch_credential.resolve_batch_credential("bc1.anything.else") is None
