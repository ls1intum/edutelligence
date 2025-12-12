from typing import Dict, Optional, Tuple

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


def authenticate_logos_key(headers: Optional[Dict[str, str]]) -> Tuple[str, int]:
    """
    Validate the logos key from request headers and return `(key, process_id)`.

    Params:
        headers: Request headers containing the logos key (case-insensitive lookup).

    Returns:
        Tuple of the resolved logos key and its associated process_id.

    Raises:
        HTTPException(401): When the key is missing or invalid.
    """
    logos_key = _resolve_logos_key(headers)
    with DBManager() as db:
        result, status = db.get_process_id(logos_key)
    if status != 200:
        raise HTTPException(status_code=401, detail="Invalid logos key")
    return logos_key, int(result["result"])
