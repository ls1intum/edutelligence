"""Admin-only nightly benchmark activation and status."""

from fastapi import APIRouter, HTTPException, Request

import logos.main as main
from logos.benchmarks import nightly_store as store
from logos.benchmarks.guidellm_runner import extract_serving_configuration
from logos.benchmarks.nightly import local_now, parameter_plan
from logos.benchmarks.nightly_overview import overview
from logos.dbutils.dbmanager import DBManager
from logos.dbutils.dbrequest import NightlyStatusRequest, NightlyUpdateRequest
from logos.maintenance_window import MaintenanceWindow, maintenance_node_limit
from logos.routers.internal import _require_internal_secret

router = APIRouter(prefix="/internal/model_benchmarks/nightly", tags=["admin"])


def target_for(pair_id):
    with DBManager() as db:
        target = db.get_model_provider_benchmark_target(pair_id)
    if not target or target["provider_type"] != "logosnode":
        raise HTTPException(status_code=400, detail="Nightly benchmarks require a Logos worker")
    return target


@router.post("/status")
async def nightly_status(data: NightlyStatusRequest, request: Request):
    _require_internal_secret(request)
    target = target_for(data.model_provider_id)
    result = store.status(data.model_provider_id)
    snapshot = main._logosnode_registry.peek_runtime_snapshot(target["provider_id"])
    result["plan"] = [
        run.model_dump() for run in parameter_plan(extract_serving_configuration(snapshot, target["model_name"]))
    ]
    result["window"] = MaintenanceWindow.from_env().describe()
    result["timezone"] = result["window"]["timezone"]
    result["max_maintenance_nodes"] = maintenance_node_limit()
    return result


@router.post("/configure")
async def configure_nightly(data: NightlyUpdateRequest, request: Request):
    _require_internal_secret(request)
    target = target_for(data.model_provider_id)
    if data.enabled:
        snapshot = main._logosnode_registry.peek_runtime_snapshot(target["provider_id"]) or {}
        if not (snapshot.get("runtime") or {}).get("supports_benchmark_restart"):
            raise HTTPException(status_code=409, detail="Update and connect this worker before enabling nightly runs")
    try:
        result = store.set_enabled(data.model_provider_id, data.enabled, data.expected_enabled)
        result["window"] = MaintenanceWindow.from_env().describe()
        result["max_maintenance_nodes"] = maintenance_node_limit()
        return result
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/overview")
async def nightly_overview(request: Request):
    _require_internal_secret(request)
    if main._nightly_scheduler is None:
        raise HTTPException(status_code=503, detail="Nightly scheduler is starting")
    now = local_now()
    return overview(
        store.overview_rows(),
        main._nightly_scheduler,
        now,
        recovery_pending=store.has_recovery(),
        claimed_count=store.claimed_today(now.date()),
    )
