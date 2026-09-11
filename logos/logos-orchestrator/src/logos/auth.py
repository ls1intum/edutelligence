from dataclasses import dataclass
from typing import Any, Dict, Optional

from fastapi import HTTPException

from logos import batch_credential
from logos.dbutils.dbmanager import DBManager


def _get_header_value(headers: Dict[str, str], name: str) -> Optional[str]:
    """Return a header value using case-insensitive matching."""
    for key, value in headers.items():
        if key.lower() == name.lower():
            return value
    return None


def _resolve_logos_key(headers: Optional[Dict[str, str]], required: bool = True) -> Optional[str]:
    """
    Extract the caller's logos key from common header shapes.

    Params:
        headers: Request headers (case-insensitive lookup).
        required: When True, raise if no key is found.

    Returns:
        The resolved logos key string, or None when not required and absent.

    Raises:
        HTTPException(401): When required and no logos key is present.
    """
    headers = headers or {}
    logos_header = _get_header_value(headers, "logos_key") or _get_header_value(headers, "logos-key")
    if logos_header:
        return logos_header
    auth_header = _get_header_value(headers, "authorization")
    if auth_header:
        auth_header = auth_header.strip()
        if auth_header.lower().startswith("bearer "):
            return auth_header[7:].strip()
        return auth_header
    if required:
        raise HTTPException(status_code=401, detail="Missing logos key")
    return None


@dataclass
class AuthContext:
    """Complete authentication and authorization context."""

    key_value: str
    api_key_id: int
    api_key_name: str
    key_type: str
    team_id: Optional[int]
    user_id: Optional[int]
    environment: Optional[str]
    log_level: str
    settings: Optional[dict]
    # Queue priority the key owner configured for this key (1/5/10 scale, see
    # queue.models.Priority). 0 means "not set": the request falls back to the
    # policy-level priority (see pipeline.resolve_queue_priority).
    default_priority: int = 0
    cloud_rl: Optional[dict] = None
    local_rl: Optional[dict] = None


def _resolve_batch_credential(credential: str) -> Optional[Dict[str, Any]]:
    """The key row a scoped batch credential names, or None.

    The webservice's batch proxy authenticates with a short-lived credential
    instead of the user's raw key value (see batch_credential): this turns it
    back into the key's own row. The row lookup is what keeps it honest — a
    key revoked after the credential was handed out stops working the moment
    it is presented again.
    """
    if not isinstance(credential, str) or not credential.startswith(batch_credential.BATCH_CREDENTIAL_PREFIX):
        return None
    api_key_id = batch_credential.resolve_batch_credential(credential)
    if api_key_id is None:
        return None
    with DBManager() as db:
        return db.get_api_key_by_id(api_key_id)


def _auth_context_from_key_row(row: Dict[str, Any]) -> AuthContext:
    k_type = row["key_type"]
    if hasattr(k_type, "value"):
        k_type = k_type.value

    return AuthContext(
        # The key's own value, not what the header carried: for a scoped
        # credential the header holds the credential, and the downstream
        # (batch lines re-enter the pipeline as the key) needs the value.
        key_value=row["key_value"],
        api_key_id=row["id"],
        api_key_name=row["name"],
        key_type=str(k_type),
        team_id=row["team_id"],
        user_id=row["user_id"],
        environment=row["environment"],
        log_level=row.get("log") or "BILLING",
        settings=row.get("settings") if row.get("settings") is not None else {},
        # Preserve 0 (the webservice/UI "not set" sentinel) so the pipeline
        # can fall back to the policy-level priority.
        default_priority=row.get("default_priority") or 0,
    )


def authenticate_api_key(headers: Optional[Dict[str, str]]) -> AuthContext:
    logos_key = _resolve_logos_key(headers)
    with DBManager() as db:
        row = db.get_api_key_by_value(logos_key)
    if row is None:
        raise HTTPException(status_code=401, detail="Invalid or inactive logos key")
    return _auth_context_from_key_row(row)


def authenticate_batch_api_key(headers: Optional[Dict[str, str]]) -> AuthContext:
    """Auth for the Batch API, which also takes the scoped credential.

    The credential resolves to the key's own row here and nowhere else: it is
    a batch-only bearer (the webservice exchanges it for the key instead of
    sending the raw value over the internal hop), and the global key auth
    must keep refusing it, or it would open ordinary inference — and, for an
    admin-owned key, the role-gated routes — for its whole TTL.
    """
    logos_key = _resolve_logos_key(headers)
    with DBManager() as db:
        row = db.get_api_key_by_value(logos_key)
    if row is None:
        # A key value that is not a key value: try the scoped credential the
        # batch proxy exchanged for the key.
        row = _resolve_batch_credential(logos_key)
    if row is None:
        raise HTTPException(status_code=401, detail="Invalid or inactive logos key")
    return _auth_context_from_key_row(row)
