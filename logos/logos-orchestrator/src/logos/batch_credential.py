"""Scoped, short-lived credentials for the batch proxy.

The Spring webservice sits on the internal network next to the orchestrator
and proxies the UI's batch pages to the Batch API as the caller's own key.
That key is a long-lived secret: the shipped Compose setup reaches the
orchestrator over plain HTTP, so sending the key value on that hop would put
the user's own credential on a cleartext wire.

So the webservice never sends the key itself. It names the key by id to the
secret-gated internal endpoint (its ownership check has already run), and the
orchestrator answers with a scoped credential: bound to that one key, valid
for a few minutes, and verifiable without a round trip. The Batch API accepts
the credential where it accepts a key value, and resolves it through the
key's own row — which is also what re-checks, at presentation time, that the
key is still active.
"""

import base64
import datetime
import hashlib
import hmac
import json
import logging
import os
import secrets
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# How long a handed-out credential stays good. Long enough for the upload and
# the batch creation it serves; short enough that a credential read off the
# internal network stops working quickly.
BATCH_CREDENTIAL_TTL_S = int(os.getenv("LOGOS_BATCH_CREDENTIAL_TTL_S", "300"))

# What marks a value as a scoped credential rather than a key value: the key
# lookup tries the plain interpretation first, and only falls back to this.
BATCH_CREDENTIAL_PREFIX = "bc1."


def _signing_secret() -> str:
    # The same shared secret that gates /internal/*: it is already the trust
    # root between the webservice and the orchestrator, so the credential
    # rides on it instead of a second secret to configure. Read per call so a
    # test (or a restart with a changed secret) is picked up without a reload.
    return os.getenv("LOGOS_INTERNAL_SECRET", "")


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def issue_batch_credential(api_key_id: int, now: Optional[datetime.datetime] = None) -> Tuple[str, int]:
    """A scoped credential for one key: ``(credential, ttl_seconds)``.

    Raises RuntimeError when no internal secret is configured: without it the
    credential would be verifiable by nobody, and issuing one would only make
    the failure look like it is in the key.
    """
    secret = _signing_secret()
    if not secret:
        raise RuntimeError("No internal secret configured; no batch credential can be issued.")
    issued = now or datetime.datetime.now(datetime.timezone.utc)
    expires_at = int(issued.timestamp()) + BATCH_CREDENTIAL_TTL_S
    payload = _b64encode(
        json.dumps({"kid": int(api_key_id), "exp": expires_at, "nonce": secrets.token_hex(8)}, sort_keys=True).encode()
    )
    signature = _b64encode(hmac.new(secret.encode("utf-8"), payload.encode("ascii"), hashlib.sha256).digest())
    return f"{BATCH_CREDENTIAL_PREFIX}{payload}.{signature}", BATCH_CREDENTIAL_TTL_S


def resolve_batch_credential(credential: str) -> Optional[int]:
    """The api_key_id a credential names, or None when it is not one of ours.

    None covers every way a value can fail to be a live credential — wrong
    shape, signature that does not match, expiry passed, no secret
    configured — and the caller treats it exactly like an unknown key.
    """
    if not isinstance(credential, str) or not credential.startswith(BATCH_CREDENTIAL_PREFIX):
        return None
    secret = _signing_secret()
    if not secret:
        return None
    body = credential[len(BATCH_CREDENTIAL_PREFIX) :]
    try:
        payload, signature = body.rsplit(".", 1)
        expected = _b64encode(hmac.new(secret.encode("utf-8"), payload.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            return None
        record = json.loads(_b64decode(payload))
        api_key_id = int(record["kid"])
        expires_at = int(record["exp"])
    except (ValueError, KeyError, TypeError):
        return None
    if expires_at < datetime.datetime.now(datetime.timezone.utc).timestamp():
        return None
    return api_key_id
