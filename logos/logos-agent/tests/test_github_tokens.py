"""Minting and caching of short-lived GitHub App installation tokens.

The module under test is pure — the tests hand it credential material and a
stubbed GitHub API — and pin the requests it makes: which endpoint, which
lifetime is asked for, and which token comes back. The rest is the contract
a minted token must keep: it resolves the app's installation, is cached
while it is good, and is re-minted rather than handed out with minutes of
life left.
"""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from app import github_tokens
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

_REPO = "ls1intum/edutelligence"
_APP_ID = "41234"


@pytest.fixture()
def rsa_key():
    """A generated app keypair: the private PEM is the credential."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    return key, pem


@pytest.fixture(autouse=True)
def _clean_token_cache():
    # The cache is module state: every test starts from a service that has
    # not minted yet, and leaves it that way.
    github_tokens.reset()
    yield
    github_tokens.reset()


class FakeResponse:
    def __init__(self, status_code, payload=None, text="", headers=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text
        self.headers = headers or {}

    def json(self):
        return self._payload


def fake_github(monkeypatch, *, install_status=200, install_id="815", post_status=201, post_payloads=None):
    """Point the module's HTTP client at a stub that records every call.

    ``post_payloads`` scripts the mint answers in order; when the calls
    outlast the script, the last answer repeats. Unscripted answers name a
    token of their own, so the tests can tell one mint from the next.

    The lookup answers the way GitHub does: 200 with the installation object
    itself (``id`` at the top level), or an empty 204 when the app is not
    installed on the repository.
    """
    calls: list = []
    mints = 0

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, headers=None, params=None):
            calls.append({"method": "GET", "url": url, "headers": headers or {}})
            if install_status == 200:
                return FakeResponse(200, {"id": int(install_id), "account": {"login": "ls1intum"}})
            if install_status == 204:
                return FakeResponse(204)
            return FakeResponse(install_status, text="no such installation")

        async def post(self, url, headers=None, json=None):
            nonlocal mints
            mints += 1
            calls.append({"method": "POST", "url": url, "headers": headers or {}, "json": json})
            if post_payloads is not None:
                payload = post_payloads[min(mints - 1, len(post_payloads) - 1)]
            else:
                expires = datetime.now(timezone.utc) + timedelta(seconds=1800)
                payload = {
                    "token": f"ghs-mint-{mints}",
                    "expires_at": expires.isoformat().replace("+00:00", "Z"),
                }
            return FakeResponse(post_status, payload, text="" if post_status == 201 else "forbidden")

    monkeypatch.setattr(github_tokens.httpx, "AsyncClient", FakeClient)
    return calls


def test_the_app_jwt_names_the_app_and_stays_within_the_limit(rsa_key):
    key, _ = rsa_key
    now = datetime(2026, 10, 6, 12, 0, 0, tzinfo=timezone.utc)

    signed = github_tokens.app_jwt(_APP_ID, key, now=now)

    # Freeze time validation: this token is issued against a fixed clock and
    # would otherwise expire permanently against wall-clock decoding.
    claims = jwt.decode(
        signed, key.public_key(), algorithms=["RS256"], options={"verify_exp": False, "verify_iat": False}
    )
    # GitHub allows ten minutes for this JWT. The claims stay inside that,
    # and the issue time is back-dated, so clock skew cannot read as a token
    # issued in the future.
    assert claims["iss"] == _APP_ID
    assert claims["exp"] - claims["iat"] == 300
    assert claims["iat"] == int(now.timestamp()) - 30
    assert claims["exp"] == int(now.timestamp()) + 270


def test_the_key_comes_as_pem_or_its_base64(rsa_key):
    # The base64 form keeps the value on one line, which an environment
    # file and a compose interpolation are friendlier to — so both must
    # parse to the same key.
    key, pem = rsa_key
    fingerprint = key.public_key().public_numbers()
    encoded = base64.b64encode(pem.encode()).decode()

    for given in (pem, encoded):
        parsed = github_tokens.parse_private_key(given)
        assert parsed.public_key().public_numbers() == fingerprint


def test_a_key_that_is_not_a_key_is_refused():
    for given in ("", "   ", "definitely-not-a-key"):
        with pytest.raises(github_tokens.CredentialError):
            github_tokens.parse_private_key(given)


def test_a_key_of_another_family_is_refused_before_signing():
    # GitHub App JWTs are RS256 against an RSA key. An Ed25519 key must be
    # refused here, not handed to the signer under a mismatched algorithm.
    key = Ed25519PrivateKey.generate()

    with pytest.raises(github_tokens.CredentialError, match="RSA"):
        github_tokens.app_jwt(_APP_ID, key)


async def test_the_first_call_mints_for_the_repositorys_installation(monkeypatch, rsa_key):
    key, pem = rsa_key
    calls = fake_github(monkeypatch)

    token = await github_tokens.installation_token(app_id=_APP_ID, private_key=pem, repo_slug=_REPO)

    assert token == "ghs-mint-1"
    assert [c["url"] for c in calls] == [
        f"https://api.github.com/repos/{_REPO}/installation",
        "https://api.github.com/app/installations/815/access_tokens",
    ]
    assert calls[1]["json"]["expires_in"] == github_tokens.DEFAULT_TTL_S
    assert calls[1]["json"]["repositories"] == ["edutelligence"]
    # What authenticates the request is the app's own signature — a JWT the
    # app's public key verifies, issued by the app's id — not any stored
    # bearer token.
    claims = jwt.decode(
        calls[0]["headers"]["Authorization"].removeprefix("Bearer "),
        key.public_key(),
        algorithms=["RS256"],
        options={"verify_exp": False, "verify_iat": False},
    )
    assert claims["iss"] == _APP_ID


async def test_the_cached_token_is_reused_while_it_is_good(monkeypatch, rsa_key):
    _, pem = rsa_key
    calls = fake_github(monkeypatch)

    first = await github_tokens.installation_token(app_id=_APP_ID, private_key=pem, repo_slug=_REPO)
    second = await github_tokens.installation_token(app_id=_APP_ID, private_key=pem, repo_slug=_REPO)

    assert first == second
    assert len([c for c in calls if c["method"] == "POST"]) == 1


async def test_a_configured_installation_skips_the_lookup(monkeypatch, rsa_key):
    _, pem = rsa_key
    calls = fake_github(monkeypatch)

    await github_tokens.installation_token(app_id=_APP_ID, private_key=pem, installation_id="4242", repo_slug=_REPO)

    assert [c["url"] for c in calls] == ["https://api.github.com/app/installations/4242/access_tokens"]


async def test_a_token_with_little_life_left_is_reminted(monkeypatch, rsa_key):
    import hashlib
    import time

    _, pem = rsa_key

    def iso(moment):
        return moment.isoformat().replace("+00:00", "Z")

    # Bind the lock to this test's event loop before seeding the cache:
    # installation_token's first call otherwise clears _cache when it
    # notices a new loop, and the remint path would never see this entry.
    github_tokens._lock_for_current_loop()
    # Seed a cached token that has already fallen below the refresh margin —
    # a freshly minted answer that short is refused, so the remint path is
    # exercised from the cache boundary.
    identity = (
        _APP_ID,
        _REPO,
        _REPO.strip().lower(),
        hashlib.sha256(pem.encode("utf-8")).digest(),
    )
    github_tokens._cache[identity] = ("ghs-first", time.time() + 60)
    calls = fake_github(
        monkeypatch,
        post_payloads=[
            {"token": "ghs-second", "expires_at": iso(datetime.now(timezone.utc) + timedelta(seconds=1800))},
        ],
    )

    second = await github_tokens.installation_token(app_id=_APP_ID, private_key=pem, repo_slug=_REPO)

    assert second == "ghs-second"
    assert len([c for c in calls if c["method"] == "POST"]) == 1


async def test_a_cached_token_that_cannot_cover_the_helper_timeout_is_reminted(monkeypatch, rsa_key):
    # 301 seconds clears the default 300-second refresh margin, but a helper
    # that may run for 600 seconds needs more than that left when it starts.
    _, pem = rsa_key

    def iso(moment):
        return moment.isoformat().replace("+00:00", "Z")

    helper_needed = 600 + github_tokens.HELPER_STARTUP_OVERHEAD_S
    calls = fake_github(
        monkeypatch,
        post_payloads=[
            {"token": "ghs-short", "expires_at": iso(datetime.now(timezone.utc) + timedelta(seconds=301))},
            {"token": "ghs-long", "expires_at": iso(datetime.now(timezone.utc) + timedelta(seconds=1800))},
        ],
    )

    first = await github_tokens.installation_token(app_id=_APP_ID, private_key=pem, repo_slug=_REPO)
    reused = await github_tokens.installation_token(app_id=_APP_ID, private_key=pem, repo_slug=_REPO)
    for_helper = await github_tokens.installation_token(
        app_id=_APP_ID,
        private_key=pem,
        repo_slug=_REPO,
        min_remaining_s=helper_needed,
    )

    assert (first, reused, for_helper) == ("ghs-short", "ghs-short", "ghs-long")
    assert len([c for c in calls if c["method"] == "POST"]) == 2
    assert calls[-1]["json"]["expires_in"] >= helper_needed


async def test_other_credentials_do_not_inherit_the_cached_token(monkeypatch, rsa_key):
    # A caller that swaps credentials — another installation, another key —
    # must not hand out a token minted for the other one.
    _, pem = rsa_key
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other_pem = other.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    fake_github(monkeypatch)

    first = await github_tokens.installation_token(
        app_id=_APP_ID, private_key=pem, installation_id="11", repo_slug=_REPO
    )
    second = await github_tokens.installation_token(
        app_id=_APP_ID, private_key=pem, installation_id="12", repo_slug=_REPO
    )
    third = await github_tokens.installation_token(
        app_id=_APP_ID, private_key=other_pem, installation_id="11", repo_slug=_REPO
    )

    assert [first, second, third] == ["ghs-mint-1", "ghs-mint-2", "ghs-mint-3"]


async def test_missing_credential_material_is_refused_before_any_request(monkeypatch):
    calls = fake_github(monkeypatch)

    with pytest.raises(github_tokens.CredentialError, match="both"):
        await github_tokens.installation_token(app_id=_APP_ID, private_key="", repo_slug=_REPO)
    with pytest.raises(github_tokens.CredentialError, match="not a number"):
        await github_tokens.installation_token(app_id="not-a-number", private_key="whatever", repo_slug=_REPO)

    assert calls == []


async def test_the_asked_lifetime_is_clamped_to_whats_accepted(monkeypatch, rsa_key):
    _, pem = rsa_key
    calls = fake_github(monkeypatch)

    await github_tokens.installation_token(app_id=_APP_ID, private_key=pem, repo_slug=_REPO, ttl_s=999999)
    github_tokens.reset()
    await github_tokens.installation_token(app_id=_APP_ID, private_key=pem, repo_slug=_REPO, ttl_s=5)

    # GitHub mints at most an hour, and an ask shorter than the refresh
    # margin would re-mint on every call. Only POSTs carry a json body —
    # the lookup GET must not be indexed here.
    assert [c["json"] for c in calls if c["method"] == "POST"] == [
        {"expires_in": github_tokens.MAX_TTL_S, "repositories": ["edutelligence"]},
        {"expires_in": github_tokens.MIN_TTL_S, "repositories": ["edutelligence"]},
    ]


async def test_an_installation_github_will_not_name_is_an_error(monkeypatch, rsa_key):
    _, pem = rsa_key
    fake_github(monkeypatch, install_status=404)

    with pytest.raises(github_tokens.CredentialError, match="could not find the app's installation"):
        await github_tokens.installation_token(app_id=_APP_ID, private_key=pem, repo_slug=_REPO)


async def test_an_app_that_is_not_installed_is_an_error_before_any_mint(monkeypatch, rsa_key):
    _, pem = rsa_key
    calls = fake_github(monkeypatch, install_status=204)

    with pytest.raises(github_tokens.CredentialError, match="not installed"):
        await github_tokens.installation_token(app_id=_APP_ID, private_key=pem, repo_slug=_REPO)

    assert [c["method"] for c in calls] == ["GET"]
    assert [c for c in calls if c["method"] == "POST"] == []


async def test_a_refused_mint_is_an_error(monkeypatch, rsa_key):
    _, pem = rsa_key
    fake_github(monkeypatch, post_status=403)

    with pytest.raises(github_tokens.CredentialError, match="403"):
        await github_tokens.installation_token(app_id=_APP_ID, private_key=pem, repo_slug=_REPO)


async def test_a_mint_answer_without_a_token_is_an_error(monkeypatch, rsa_key):
    _, pem = rsa_key
    fake_github(monkeypatch, post_payloads=[{"expires_at": "2026-10-06T13:00:00Z"}])

    with pytest.raises(github_tokens.CredentialError, match="without a token"):
        await github_tokens.installation_token(app_id=_APP_ID, private_key=pem, repo_slug=_REPO)


async def test_an_unreachable_api_is_a_credential_error(monkeypatch, rsa_key):
    _, pem = rsa_key

    class Unreachable:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, *args, **kwargs):
            raise github_tokens.httpx.ConnectError("no route to host")

        async def post(self, *args, **kwargs):
            raise github_tokens.httpx.ConnectError("no route to host")

    monkeypatch.setattr(github_tokens.httpx, "AsyncClient", Unreachable)

    with pytest.raises(github_tokens.CredentialError, match="could not reach the GitHub API"):
        await github_tokens.installation_token(app_id=_APP_ID, private_key=pem, repo_slug=_REPO)
