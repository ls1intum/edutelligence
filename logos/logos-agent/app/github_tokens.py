"""Short-lived GitHub App installation tokens, minted on demand.

The alternative is what a deployment otherwise keeps: a personal access
token of the agent account, in the environment for as long as the token
is not revoked. That is a standing door — publish it in a log, a
transcript, or an environment dump and it stays open. A deployment that
runs the agent account as a GitHub App holds only the app's *signing
key*: it cannot act on its own, it only signs the short request that
mints a token. The tokens minted here live at most an hour, are re-minted
automatically before the previous one lapses, and are what reaches the
helper containers — so a credential that is published by accident stops
being one within its own lifetime.

The module is deliberately ignorant of the service's configuration: the
callers hand in what they read from their own settings, and what comes
back is a bearer token.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import time
from datetime import datetime, timezone

import httpx
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey

_API = "https://api.github.com"

# GitHub will mint no token for longer than an hour.
MAX_TTL_S = 3600
# Long enough to cover the longest single piece of work a token carries
# (a deploy wait runs twenty minutes) without outliving a leaked copy for
# long.
DEFAULT_TTL_S = 1800
# Below this the refresh margin below would be a large share of the
# lifetime itself, and every call would end up re-minting.
MIN_TTL_S = 600
# Default remaining-lifetime floor for short runner API calls: re-mint once
# this much lifetime is left.
_REFRESH_MARGIN_S = 300
# Headroom beyond a helper's wall-clock budget for container start and the
# first authenticated call. Helpers receive a fixed token in their
# environment; refreshing the runner cache cannot refresh it mid-run.
HELPER_STARTUP_OVERHEAD_S = 60
# GitHub allows ten minutes for the app's JWT; five keeps the clock-skew
# allowance small.
_JWT_LIFETIME_S = 300


class CredentialError(RuntimeError):
    """The app's credential is missing or unusable, or GitHub will not mint a token."""


def _clamp_ttl(ttl_s: object) -> int:
    try:
        ttl = int(ttl_s)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        ttl = DEFAULT_TTL_S
    return max(MIN_TTL_S, min(ttl, MAX_TTL_S))


def parse_private_key(raw: str):
    """The app's private key from its environment value.

    Either the PEM directly or its base64 — the latter keeps the value on
    one line, which an environment file and a compose interpolation are
    friendlier to.
    """
    text = (raw or "").strip()
    if not text:
        raise CredentialError("the GitHub App private key is empty")
    if text.startswith("-----BEGIN"):
        pem = text.encode("utf-8")
    else:
        try:
            pem = base64.b64decode(text, validate=True)
        except Exception:
            try:
                pem = base64.urlsafe_b64decode(text)
            except Exception as exc:
                raise CredentialError("the GitHub App private key is neither PEM nor base64") from exc
    try:
        return serialization.load_pem_private_key(pem, password=None)
    except Exception as exc:
        raise CredentialError(f"the GitHub App private key is not a usable private key: {exc}") from exc


def _algorithm(key) -> str:
    # GitHub verifies App JWTs against the App's RSA public key with RS256.
    # Anything else fails at the API; refuse it here so a wrong key never
    # reaches the signer under a mismatched algorithm name.
    if isinstance(key, RSAPrivateKey):
        return "RS256"
    raise CredentialError(
        f"the GitHub App key must be the app's RSA private key (signed with RS256), " f"not a {type(key).__name__}"
    )


def app_jwt(app_id: str, key, now: datetime | None = None) -> str:
    """The user-to-server JWT that authenticates the app itself.

    It names the app in ``iss`` and lives no longer than GitHub allows. It
    is not a credential for acting — only for asking the API to mint one.
    """
    moment = now or datetime.now(timezone.utc)
    issued = int(moment.timestamp()) - 30  # skew, so iat is never "in the future"
    return jwt.encode(
        {"iss": str(app_id), "iat": issued, "exp": issued + _JWT_LIFETIME_S},
        key,
        algorithm=_algorithm(key),
    )


def _headers_for(signed: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {signed}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _installation_id_of(response, repo_slug: str) -> str:
    # GET /repos/{owner}/{repo}/installation returns the installation object
    # itself (id at the top level) on 200, or an empty 204 when the app is
    # not installed on that repository.
    if response.status_code == 204:
        raise CredentialError(f"the app is not installed on {repo_slug}")
    if response.status_code != 200:
        raise CredentialError(
            f"could not find the app's installation on {repo_slug} ({response.status_code}): {response.text[:200]}"
        )
    try:
        payload = response.json() or {}
    except Exception:
        payload = {}
    installation_id = payload.get("id") if isinstance(payload, dict) else None
    if not isinstance(installation_id, int) or installation_id < 1:
        raise CredentialError(f"GitHub named no installation for {repo_slug}")
    return str(installation_id)


def _epoch(stamp: object) -> float | None:
    if not isinstance(stamp, str) or not stamp:
        return None
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


# One cache of (token, expires at). The identity of the credential — app
# id, which installation it serves, and the key material it was minted
# with — is part of the key: a caller that swaps credentials must not
# inherit somebody else's token.
_cache: dict[tuple[str, str, bytes], tuple[str, float]] = {}
# A lock per event loop: asyncio primitives remember the loop that first
# used them, and a test suite starts a fresh loop per test.
_lock: tuple[asyncio.AbstractEventLoop, asyncio.Lock] | None = None


def _lock_for_current_loop() -> asyncio.Lock:
    global _lock
    loop = asyncio.get_running_loop()
    if _lock is None or _lock[0] is not loop:
        _lock = (loop, asyncio.Lock())
        _cache.clear()  # a token another loop minted is not usable here
    return _lock[1]


def reset() -> None:
    """Drop the cached token; a service that has not minted yet."""
    _cache.clear()


async def installation_token(
    *,
    app_id: str,
    private_key: str,
    installation_id: str = "",
    repo_slug: str,
    ttl_s: int = DEFAULT_TTL_S,
    min_remaining_s: int = 0,
) -> str:
    """A usable installation token of the app on this repository.

    The cached one is returned while it has more than the required remaining
    lifetime left; otherwise a fresh one is minted and remembered.
    ``min_remaining_s`` raises that floor above the default refresh margin —
    helpers that may run for ``helper_timeout_s`` must ask for at least that
    long plus :data:`HELPER_STARTUP_OVERHEAD_S`, because their token is fixed
    in the container environment. ``installation_id`` may be empty — it is
    then resolved from the repository — and ``ttl_s`` is clamped to what
    GitHub accepts. A freshly minted token that still cannot cover the
    requirement raises :class:`CredentialError`.
    """
    if not (app_id and private_key):
        raise CredentialError("a GitHub App needs both its id and its private key")
    if not app_id.strip().isdigit():
        raise CredentialError(f"the GitHub App id '{app_id}' is not a number")
    try:
        needed = int(min_remaining_s)
    except (TypeError, ValueError):
        needed = 0
    required = max(_REFRESH_MARGIN_S, needed)
    if required > MAX_TTL_S:
        raise CredentialError(
            f"need more than {required}s of installation-token lifetime, but GitHub mints at most {MAX_TTL_S}s"
        )
    ttl = max(_clamp_ttl(ttl_s), required)
    identity = (
        app_id.strip(),
        installation_id.strip() or repo_slug,
        hashlib.sha256(private_key.encode("utf-8")).digest(),
    )
    async with _lock_for_current_loop():
        cached = _cache.get(identity)
        now = time.time()
        if cached is not None and cached[1] - now > required:
            return cached[0]
        token, expires_at = await _mint(
            app_id=app_id.strip(),
            private_key=private_key,
            installation_id=installation_id.strip(),
            repo_slug=repo_slug,
            ttl_s=ttl,
        )
        remaining = expires_at - time.time()
        if remaining <= required:
            raise CredentialError(
                f"minted installation token has only {int(remaining)}s remaining; "
                f"need more than {required}s for the caller"
            )
        _cache[identity] = (token, expires_at)
        return token


async def _mint(
    *, app_id: str, private_key: str, installation_id: str, repo_slug: str, ttl_s: int
) -> tuple[str, float]:
    """One mint: resolve the installation when needed, ask for a token."""
    key = parse_private_key(private_key)
    signed = app_jwt(app_id, key)
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            if not installation_id:
                response = await client.get(f"{_API}/repos/{repo_slug}/installation", headers=_headers_for(signed))
                installation_id = _installation_id_of(response, repo_slug)
            response = await client.post(
                f"{_API}/app/installations/{installation_id}/access_tokens",
                headers=_headers_for(signed),
                json={"expires_in": ttl_s},
            )
    except httpx.HTTPError as exc:
        raise CredentialError(f"could not reach the GitHub API: {exc}") from exc
    if response.status_code != 201:
        raise CredentialError(f"could not mint an installation token ({response.status_code}): {response.text[:200]}")
    payload = response.json()
    token = str((payload or {}).get("token") or "")
    if not token:
        raise CredentialError("GitHub minted a token response without a token")
    expires_at = _epoch(payload.get("expires_at"))
    if expires_at is None:
        # Trust the lifetime asked for when the answer names no expiry.
        expires_at = time.time() + ttl_s
    return token, expires_at
