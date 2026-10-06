"""Monthly budget enforcement, shared by the request pipeline and the Batch API."""

from typing import TYPE_CHECKING, Optional

from fastapi import HTTPException

if TYPE_CHECKING:  # pragma: no cover - typing only
    from logos.auth import AuthContext
    from logos.dbutils.dbmanager import DBManager


def check_monthly_budget(
    db: "DBManager",
    auth: "AuthContext",
    is_cloud: bool,
    month_start: str,
    provider_id: Optional[int] = None,
    check_team: bool = True,
) -> None:
    """
    Raise HTTPException(402) if this key/team is over its monthly budget.

    Only cloud usage is metered (logosnode/local providers have no configured
    token pricing in token_prices, so they always cost $0), so this is a
    no-op when the request that actually got scheduled isn't routing to a
    cloud provider at all. Called post-scheduling (see _execute_resource_mode)
    with the real resolved provider type, not a guess from the permission list --
    that's what lets this be exact for mixed cloud+local keys instead of only
    for pure-type ones.

    When ``provider_id`` is set, a ``team_provider_budgets`` row for the team
    takes that provider out of the default team monthly bucket (null limit =
    sponsored / unlimited for that provider alone; every non-null limit,
    including 0, is enforced).

    ``check_team=False`` checks only the key's own budget; it is for callers
    that do not know the provider yet and leave the team check to each request
    once its provider is resolved.
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
        if check_team and auth.team_id is not None:
            _check_team_budget(db, auth.team_id, month_start, provider_id)

        personal_limit = db.get_api_key_budget_limit(auth.api_key_id)
        if personal_limit is not None:
            personal_used = db.get_api_key_budget_usage(auth.api_key_id, month_start)
            if personal_used >= personal_limit:
                raise HTTPException(status_code=402, detail="Personal monthly budget exceeded.")


def _check_team_budget(db: "DBManager", team_id: int, month_start: str, provider_id: Optional[int]) -> None:
    if provider_id is not None:
        exists, provider_limit = db.get_team_provider_budget(team_id, provider_id)
        if exists:
            if provider_limit is not None:
                provider_used = db.get_team_provider_budget_usage(team_id, provider_id, month_start)
                if provider_used >= provider_limit:
                    raise HTTPException(
                        status_code=402, detail="Team monthly budget exceeded for this provider. Contact your admin."
                    )
            return

    team_info = db.get_team(team_id)
    if team_info and team_info.get("team_monthly_budget_micro_cents"):
        team_limit = team_info["team_monthly_budget_micro_cents"]
        if provider_id is not None:
            team_used = db.get_team_default_budget_usage(team_id, month_start)
        else:
            team_used = db.get_team_budget_usage(team_id, month_start)
        if team_used >= team_limit:
            raise HTTPException(status_code=402, detail="Team monthly budget exceeded. Contact your admin.")
