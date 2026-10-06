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
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

_REPO = "ls1intum/edutelligence"
_APP_ID = "41234"


@pytest.fixture()
def ed25519():
    """A generated app keypair: the private PEM is the credential."""
    key = Ed25519PrivateKey.generate()
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


def fake_github(monkeypatch, *, install_status=204, install_id="815", post_status=201, post_payloads=None):
    """Point the module's HTTP client at a stub that records every call.

    ``post_payloads`` scripts the mint answers in order; when the calls
    outlast the script, the last answer repeats. Unscripted answers name a
    token of their own, so the tests can tell one mint from the next.
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
            if install_status == 204:
                return FakeResponse(204, headers={"X-GitHub-Installation-Id": install_id})
            if install_status == 200:
                return FakeResponse(
                    200, {"installation": {"id": install_id}}, headers={"X-GitHub-Installation-Id": install_id}
                )
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


def test_the_app_jwt_names_the_app_and_stays_within_the_limit(ed25519):
    key, _ = ed25519
    now = datetime(2026, 10, 6, 12, 0, 0, tzinfo=timezone.utc)

    signed = github_tokens.app_jwt(_APP_ID, key, now=now)

    claims = jwt.decode(signed, key.public_key(), algorithms=["ES256"])
    # GitHub allows ten minutes for this JWT. The claims stay inside that,
    # and the issue time is back-dated, so clock skew cannot read as a token
    # issued in the future.
    assert claims["iss"] == _APP_ID
    assert claims["exp"] - claims["iat"] == 300
    assert claims["iat"] == int(now.timestamp()) - 30


def test_the_key_comes_as_pem_or_its_base64(ed25519):
    # The base64 form keeps the value on one line, which an environment
    # file and a compose interpolation are friendlier to — so both must
    # parse to the same key.
    key, pem = ed25519
    fingerprint = key.public_key().public_bytes(encoding=Encoding.Raw, format=PublicFormat.Raw)
    encoded = base64.b64encode(pem.encode()).decode()

    for given in (pem, encoded):
        parsed = github_tokens.parse_private_key(given)
        assert parsed.public_key().public_bytes(encoding=Encoding.Raw, format=PublicFormat.Raw) == fingerprint


def test_a_key_that_is_not_a_key_is_refused():
    for given in ("", "   ", "definitely-not-a-key"):
        with pytest.raises(github_tokens.CredentialError):
            github_tokens.parse_private_key(given)


async def test_the_first_call_mints_for_the_repositorys_installation(monkeypatch, ed25519):
    key, pem = ed25519
    calls = fake_github(monkeypatch)

    token = await github_tokens.installation_token(app_id=_APP_ID, private_key=pem, repo_slug=_REPO)

    assert token == "ghs-mint-1"
    assert [c["url"] for c in calls] == [
        f"https://api.github.com/repos/{_REPO}/installation",
        "https://api.github.com/app/installations/815/access_tokens",
    ]
    assert calls[1]["json"] == {"expires_in": github_tokens.DEFAULT_TTL_S}
    # What authenticates the request is the app's own signature — a JWT the
    # app's public key verifies, issued by the app's id — not any stored
    # bearer token.
    claims = jwt.decode(
        calls[0]["headers"]["Authorization"].removeprefix("Bearer "), key.public_key(), algorithms=["ES256"]
    )
    assert claims["iss"] == _APP_ID


async def test_the_cached_token_is_reused_while_it_is_good(monkeypatch, ed25519):
    _, pem = ed25519
    calls = fake_github(monkeypatch)

    first = await github_tokens.installation_token(app_id=_APP_ID, private_key=pem, repo_slug=_REPO)
    second = await github_tokens.installation_token(app_id=_APP_ID, private_key=pem, repo_slug=_REPO)

    assert first == second
    assert len([c for c in calls if c["method"] == "POST"]) == 1


async def test_a_configured_installation_skips_the_lookup(monkeypatch, ed25519):
    _, pem = ed25519
    calls = fake_github(monkeypatch)

    await github_tokens.installation_token(app_id=_APP_ID, private_key=pem, installation_id="4242", repo_slug=_REPO)

    assert [c["url"] for c in calls] == ["https://api.github.com/app/installations/4242/access_tokens"]


async def test_a_token_with_little_life_left_is_reminted(monkeypatch, ed25519):
    _, pem = ed25519

    def iso(moment):
        return moment.isoformat().replace("+00:00", "Z")

    calls = fake_github(
        monkeypatch,
        post_payloads=[
            {"token": "ghs-first", "expires_at": iso(datetime.now(timezone.utc) + timedelta(seconds=60))},
            {"token": "ghs-second", "expires_at": iso(datetime.now(timezone.utc) + timedelta(seconds=1800))},
        ],
    )

    first = await github_tokens.installation_token(app_id=_APP_ID, private_key=pem, repo_slug=_REPO)
    second = await github_tokens.installation_token(app_id=_APP_ID, private_key=pem, repo_slug=_REPO)

    # Sixty seconds of life are less than the refresh margin: the helper a
    # first token went into might still be pushing when it lapses.
    assert (first, second) == ("ghs-first", "ghs-second")
    assert len([c for c in calls if c["method"] == "POST"]) == 2


async def test_other_credentials_do_not_inherit_the_cached_token(monkeypatch, ed25519):
    # A caller that swaps credentials — another installation, another key —
    # must not hand out a token minted for the other one.
    _, pem = ed25519
    other = Ed25519PrivateKey.generate()
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


async def test_the_asked_lifetime_is_clamped_to_whats_accepted(monkeypatch, ed25519):
    _, pem = ed25519
    calls = fake_github(monkeypatch)

    await github_tokens.installation_token(app_id=_APP_ID, private_key=pem, repo_slug=_REPO, ttl_s=999999)
    github_tokens.reset()
    await github_tokens.installation_token(app_id=_APP_ID, private_key=pem, repo_slug=_REPO, ttl_s=5)

    # GitHub mints at most an hour, and an ask shorter than the refresh
    # margin would re-mint on every call.
    assert [c["json"] for c in calls] == [
        {"expires_in": github_tokens.MAX_TTL_S},
        {"expires_in": github_tokens.MIN_TTL_S},
    ]


async def test_an_installation_github_will_not_name_is_an_error(monkeypatch, ed25519):
    _, pem = ed25519
    fake_github(monkeypatch, install_status=404)

    with pytest.raises(github_tokens.CredentialError, match="could not find the app's installation"):
        await github_tokens.installation_token(app_id=_APP_ID, private_key=pem, repo_slug=_REPO)


async def test_a_refused_mint_is_an_error(monkeypatch, ed25519):
    _, pem = ed25519
    fake_github(monkeypatch, post_status=403)

    with pytest.raises(github_tokens.CredentialError, match="403"):
        await github_tokens.installation_token(app_id=_APP_ID, private_key=pem, repo_slug=_REPO)


async def test_a_mint_answer_without_a_token_is_an_error(monkeypatch, ed25519):
    _, pem = ed25519
    fake_github(monkeypatch, post_payloads=[{"expires_at": "2026-10-06T13:00:00Z"}])

    with pytest.raises(github_tokens.CredentialError, match="without a token"):
        await github_tokens.installation_token(app_id=_APP_ID, private_key=pem, repo_slug=_REPO)


async def test_an_unreachable_api_is_a_credential_error(monkeypatch, ed25519):
    _, pem = ed25519

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
