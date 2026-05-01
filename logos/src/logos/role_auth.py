from fastapi import HTTPException, Request

from logos.auth import authenticate_logos_key
from logos.dbutils.dbmanager import DBManager


def _fetch_role(logos_key: str) -> str | None:
    with DBManager() as db:
        user = db.get_user_by_logos_key(logos_key)
    return user["role"] if user else None


def require_logos_admin_key(logos_key: str, db=None) -> None:
    if db is not None:
        user = db.get_user_by_logos_key(logos_key)
        role = user["role"] if user else None
    else:
        role = _fetch_role(logos_key)
    if role != "logos_admin":
        raise HTTPException(status_code=403, detail="Logos Admin access required")


def require_logos_admin(request: Request) -> str:
    logos_key, _ = authenticate_logos_key(dict(request.headers))
    require_logos_admin_key(logos_key)
    return logos_key


def require_app_admin_or_above(request: Request) -> str:
    logos_key, _ = authenticate_logos_key(dict(request.headers))
    if _fetch_role(logos_key) not in {"app_admin", "logos_admin"}:
        raise HTTPException(status_code=403, detail="App Admin access required")
    return logos_key


def get_current_user(request: Request) -> str:
    logos_key, _ = authenticate_logos_key(dict(request.headers))
    return logos_key