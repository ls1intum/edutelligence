from typing import Dict, Optional, Tuple
from dataclasses import dataclass

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

    Use this for admin/stats endpoints that don't need profile authorization.
    For model execution endpoints, use `authenticate_with_profile()` instead.

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


@dataclass
class AuthContext:
    """Complete authentication and authorization context."""
    logos_key: str
    process_id: int
    profile_id: int
    profile_name: str


def select_profile(
    headers: Dict[str, str],
    process_id: int
) -> Tuple[int, str]:
    """
    Select profile from headers or use default.

    Profile selection logic:
    1. If 'use_profile' header exists → use that profile (verify it belongs to process)
    2. Otherwise → use first available profile for the process

    Args:
        headers: Request headers
        process_id: Authenticated process ID

    Returns:
        Tuple of (profile_id, profile_name)

    Raises:
        HTTPException(400): No profile specified and no profiles available
        HTTPException(403): Specified profile doesn't belong to this process
        HTTPException(404): Specified profile not found
    """
    with DBManager() as db:
        if "use_profile" in headers:
            # Explicit profile selection
            try:
                profile_id = int(headers["use_profile"])
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail="use_profile header must be an integer"
                )

            profile_info = db.get_profile(profile_id)
            if not profile_info:
                raise HTTPException(
                    status_code=404,
                    detail=f"Profile {profile_id} not found"
                )

            # Security: Verify profile belongs to this process
            if profile_info["process_id"] != process_id:
                raise HTTPException(
                    status_code=403,
                    detail="Profile does not belong to your process"
                )

            return profile_id, profile_info["name"]

        else:
            # No explicit profile → use first available
            profiles = db.get_profiles_for_process(process_id)
            if not profiles:
                raise HTTPException(
                    status_code=400,
                    detail="No profiles available for this process"
                )

            return profiles[0]["id"], profiles[0]["name"]


def authenticate_with_profile(headers: Dict[str, str]) -> AuthContext:
    """
    Complete authentication + profile selection in one call.

    Use this for all model execution endpoints (including jobs).
    For admin endpoints that only need process auth, use `authenticate_logos_key()`.

    Returns:
        AuthContext with logos_key, process_id, profile_id, and profile_name

    Raises:
        HTTPException(401): Invalid or missing logos key
        HTTPException(400): No profiles available
        HTTPException(403): Profile doesn't belong to process
        HTTPException(404): Profile not found

    Example:
        ```python
        @app.post("/v1/chat/completions")
        async def chat(request: Request):
            auth = authenticate_with_profile(dict(request.headers))
            # auth.logos_key, auth.process_id, auth.profile_id available
            models = get_models_by_profile(auth.logos_key, auth.profile_id)
            ...
        ```
    """
    # Step 1: Authenticate logos_key
    logos_key, process_id = authenticate_logos_key(headers)

    # Step 2: Select profile
    profile_id, profile_name = select_profile(headers, process_id)

    return AuthContext(
        logos_key=logos_key,
        process_id=process_id,
        profile_id=profile_id,
        profile_name=profile_name
    )
