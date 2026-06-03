from dataclasses import dataclass
from typing import Dict, Optional

from fastapi import HTTPException

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
    default_priority: int = 1
    cloud_rl: Optional[dict] = None
    local_rl: Optional[dict] = None


def authenticate_api_key(headers: Optional[Dict[str, str]]) -> AuthContext:
    logos_key = _resolve_logos_key(headers)
    with DBManager() as db:
        row = db.get_api_key_by_value(logos_key)

    if row is None:
        raise HTTPException(status_code=401, detail="Invalid or inactive logos key")

    k_type = row["key_type"]
    if hasattr(k_type, "value"):
        k_type = k_type.value

    return AuthContext(
        key_value=logos_key,
        api_key_id=row["id"],
        api_key_name=row["name"],
        key_type=str(k_type),
        team_id=row["team_id"],
        user_id=row["user_id"],
        environment=row["environment"],
        log_level=row.get("log") or "BILLING",
        settings=row.get("settings") if row.get("settings") is not None else {},
        default_priority=row.get("default_priority") or 1,
    )


def authenticate_with_context(headers: Dict[str, str]) -> AuthContext:
    """
    Complete authentication for model execution endpoints.

    Equivalent to the old authenticate_with_profile(), but returns a richer AuthContext.

    Raises:
        HTTPException(401): Invalid or missing key.
    """
    return authenticate_api_key(headers)
