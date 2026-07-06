from fastapi import HTTPException, Request

from logos.auth import authenticate_api_key
from logos.dbutils.dbmanager import DBManager


def _fetch_role(key_value: str) -> str | None:
    with DBManager() as db:
        user = db.get_user_by_api_key(key_value)
    return user["role"] if user else None


def require_logos_admin_key(logos_key: str, db=None) -> None:
    if db is not None:
        user = db.get_user_by_api_key(logos_key)
        role = user["role"] if user else None
    else:
        role = _fetch_role(logos_key)
    if role != "logos_admin":
        raise HTTPException(status_code=403, detail="Logos Admin access required")


def require_logos_admin(request: Request) -> str:
    context = authenticate_api_key(dict(request.headers))
    role = getattr(context, "role", None) or _fetch_role(context.key_value)

    if role != "logos_admin":
        raise HTTPException(status_code=403, detail="Logos Admin access required")

    return context.key_value


def require_app_admin_or_above(request: Request) -> str:
    context = authenticate_api_key(dict(request.headers))
    role = getattr(context, "role", None) or _fetch_role(context.key_value)
    if role not in {"app_admin", "logos_admin"}:
        raise HTTPException(status_code=403, detail="App Admin access required")
    return context.key_value


def require_logos_admin_or_team_owner(team_id: int, request: Request, db) -> str:
    context = authenticate_api_key(dict(request.headers))
    role = getattr(context, "role", None) or _fetch_role(context.key_value)
    if role == "logos_admin":
        return context.key_value
    if role == "app_admin" and db.is_team_owner(team_id, context.user_id):
        return context.key_value
    raise HTTPException(status_code=403, detail="Logos Admin or team owner access required")
