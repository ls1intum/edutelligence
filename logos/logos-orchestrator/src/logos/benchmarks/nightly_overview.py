"""Read-only preview of the next nightly rotation, using scheduler eligibility."""

from datetime import timedelta

from logos.benchmarks.nightly import MAX_PAIRS_PER_NIGHT
from logos.maintenance_window import MaintenanceWindow, maintenance_node_limit


def overview(schedules, scheduler, now, *, recovery_pending=False, claimed_count=None):
    """Preview candidates, not reservations: readiness may change before admission."""
    window = MaintenanceWindow.from_env()
    _, end = window.bounds(now)
    claimed = sum(row["last_run_date"] == now.date() for row in schedules)
    if claimed_count is not None:
        claimed = claimed_count
    next_day = now.date()
    if now >= end - timedelta(minutes=10) or claimed >= MAX_PAIRS_PER_NIGHT:
        next_day += timedelta(days=1)
        claimed = 0
    blocked = recovery_pending or any(row.get("recovery") for row in schedules)
    remaining = MAX_PAIRS_PER_NIGHT - claimed
    result = []
    providers = {}
    for row in schedules:
        state, reason = "disabled", "Nightly runs are disabled"
        recent = row["last_run_date"] is not None and 0 <= (now.date() - row["last_run_date"]).days <= 7
        success = recent and any(item.get("status") == "success" for item in row.get("report", []))
        if success and row["enabled"]:
            state, reason = "recent", "Successful benchmark within the last 7 days"
        if row.get("recovery"):
            state, reason = "blocked", "Worker recovery is pending"
            if row.get("status") in {"running", "preparing"}:
                state, reason = "busy", "Worker is reserved for a benchmark or restoration"
        elif row["enabled"]:
            if blocked:
                state, reason = "blocked", "Nightly rotation waits for the reserved worker"
            elif row["last_run_date"] == next_day:
                state, reason = (
                    ("recent", "Already tested in this window")
                    if success
                    else ("waiting", "Already attempted in this window")
                )
            else:
                try:
                    target, _, _ = scheduler.target_lane(row["model_provider_id"], disable_missing=False)
                    providers[row["model_provider_id"]] = target["provider_id"]
                    state, reason = "queued", "Later in the nightly rotation"
                except RuntimeError as exc:
                    state, reason = "blocked", str(exc)
        result.append(
            {
                "model_id": row["model_id"],
                "model_provider_id": row["model_provider_id"],
                "provider_name": row["provider_name"],
                "state": state,
                "reason": reason,
                "last_run_date": row["last_run_date"],
                "recent_success": success,
            }
        )
    pending = [item for item in result if item["state"] == "queued"]
    while pending and remaining > 0:
        wave = set()
        deferred = []
        for item in pending:
            provider = providers[item["model_provider_id"]]
            if remaining <= 0 or len(wave) >= maintenance_node_limit() or provider in wave:
                deferred.append(item)
                continue
            item["state"] = "next"
            item["reason"] = "Candidate for the next window; subject to worker availability and calibration"
            wave.add(provider)
            remaining -= 1
        pending = deferred
    return {"schedules": result, "next_date": next_day, "window": window.describe()}
