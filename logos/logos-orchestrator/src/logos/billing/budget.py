"""Monthly budget enforcement, shared by the request pipeline and the Batch API."""

from typing import TYPE_CHECKING

from fastapi import HTTPException

if TYPE_CHECKING:  # pragma: no cover - typing only
    from logos.auth import AuthContext
    from logos.dbutils.dbmanager import DBManager


def check_monthly_budget(db: "DBManager", auth: "AuthContext", is_cloud: bool, month_start: str) -> None:
    """
    Raise HTTPException(402) if this key/team is over its monthly budget.

    Only cloud usage is metered (logosnode/local providers have no configured
    token pricing in token_prices, so they always cost $0), so this is a
    no-op when the request that actually got scheduled isn't routing to a
    cloud provider at all. Called post-scheduling (see _execute_resource_mode)
    with the real resolved provider type, not a guess from the permission list --
    that's what lets this be exact for mixed cloud+local keys instead of only
    for pure-type ones.
    """
    if not is_cloud:
        return

    key_type = getattr(auth, "key_type", "user")

    if key_type == "application":
        app_budget_limit = db.get_api_key_budget_limit(auth.api_key_id)
        if app_budget_limit is not None:
            app_used = db.get_api_key_budget_usage(auth.api_key_id, month_start)
            if app_used >= app_budget_limit:
                raise HTTPException(status_code=402, detail="Application monthly budget exceeded.")
    else:
        if auth.team_id is not None:
            team_info = db.get_team(auth.team_id)
            if team_info and team_info.get("team_monthly_budget_micro_cents"):
                team_limit = team_info["team_monthly_budget_micro_cents"]
                team_used = db.get_team_budget_usage(auth.team_id, month_start)
                if team_used >= team_limit:
                    raise HTTPException(status_code=402, detail="Team monthly budget exceeded. Contact your admin.")

        personal_limit = db.get_api_key_budget_limit(auth.api_key_id)
        if personal_limit is not None:
            personal_used = db.get_api_key_budget_usage(auth.api_key_id, month_start)
            if personal_used >= personal_limit:
                raise HTTPException(status_code=402, detail="Personal monthly budget exceeded.")
