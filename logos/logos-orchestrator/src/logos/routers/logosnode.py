"""Worker (LogosWorkerNode) provider endpoints under /logosdb/providers/logosnode."""

import asyncio
import datetime
import json
import logging
import os
import secrets
import time
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

import logos.main as _main
from logos.dbutils.dbmanager import DBManager
from logos.dbutils.dbrequest import (
    LogosNodeApplyLanesRequest,
    LogosNodeAuthRequest,
    LogosNodeClearUnsupportedRequest,
    LogosNodeDeleteLaneRequest,
    LogosNodeInvalidateCalibrationRequest,
    LogosNodeModelProfilesRequest,
    LogosNodeReconfigureLaneRequest,
    LogosNodeRegisterRequest,
    LogosNodeResetProfilesRequest,
    LogosNodeSleepLaneRequest,
    LogosNodeStatusRequest,
    LogosNodeWakeLaneRequest,
)
from logos.logosnode_registry import LogosNodeCommandError, LogosNodeOfflineError, LogosNodeSessionConflictError
from logos.logosnode_snapshot import (
    _LOGOSNODE_STATS_STALE_AFTER_SECONDS,
    _build_live_local_provider_sample,
    _parse_iso_datetime,
)
from logos.main import (
    _benchmark_sessions_by_job,
    _cancel_benchmark_job,
    _dispatch_logosnode_command,
    _find_uncalibrated_models_on_provider,
    _normalize_provider_type,
    _resolve_provider_name,
)
from logos.model_profile_store import (
    SYNC_MODEL_PROFILES_ACTION,
    ProfileWriteCache,
    calibration_snapshot,
    effective_profile,
    is_central_profile_payload,
    is_new_local_calibration,
    material_profile,
    overridden_fields,
    persistable_profile,
    profile_digest,
    reported_profile,
)
from logos.role_auth import require_logos_admin_key

logger = logging.getLogger("LogosLogger")

router = APIRouter()

# A worker's merged vLLM /metrics text is otherwise unbounded — several lanes'
# full native exposition text, forwarded as-is. Cap it well above any sane
# per-worker payload so a misbehaving or compromised worker can't inflate the
# orchestrator's own /metrics scrape with an unbounded blob.
_MAX_VLLM_METRICS_BYTES = 4 * 1024 * 1024

_profile_write_cache = ProfileWriteCache()
# (provider_id, model) -> last_measured_epoch already snapshotted
_recorded_calibrations: dict[tuple[int, str], float] = {}
# provider_id -> models whose echo was rejected, awaiting one coalesced push
_pending_resyncs: dict[int, set[str]] = {}
# Lets a push that is already in flight land before a rejected echo re-sends.
_RESYNC_DELAY_SECONDS = 5.0
# A worker that keeps rejecting pushes (its revision ahead of a restored
# database, a model it is calibrating) is re-sent ever more rarely.
_RESYNC_MAX_DELAY_SECONDS = 300.0
# provider_id -> resyncs since its echoes were last accepted
_resync_rounds: dict[int, int] = {}
# provider_id -> newest status not yet written (sample, count-only flag)
_unsaved_samples: dict[int, tuple[Dict[str, Any], bool]] = {}
# provider_id -> the task writing its statuses, one at a time
_sample_writers: dict[int, asyncio.Task] = {}
# provider_id -> runtime timestamp of its previous status
_last_runtime_ts: dict[int, Any] = {}
# provider_id -> monotonic time its last snapshot write started
_last_snapshot_at: dict[int, float] = {}
# A request count change resends the last status with new counters only,
# twice per request; the database keeps at most one of those per interval.
_COUNT_ONLY_SNAPSHOT_SECONDS = 5.0


def _validated_vllm_metrics_text(value: Any, *, provider_id: int) -> str | None:
    """Return *value* if it's an acceptable vllm_metrics payload, else None.

    Rejects (and logs) anything that isn't a string, or a string over
    _MAX_VLLM_METRICS_BYTES, instead of forwarding it into the cache that
    every Prometheus scrape of this orchestrator reads from.
    """
    if not isinstance(value, str):
        logger.warning(
            "Dropping vllm_metrics from provider %s: metrics_text was %s, not a string",
            provider_id,
            type(value).__name__,
        )
        return None
    # Strict, not "ignore"/"surrogatepass": a lone surrogate is valid inside
    # a JSON string escape (e.g. an unpaired \uD800), but prometheus_client's
    # generate_latest() strictly UTF-8-encodes the merged exposition output
    # later — one such character reaching the cache in an otherwise-valid
    # HELP string or label would raise UnicodeEncodeError there and break
    # every scrape of this orchestrator's /metrics, not just this worker's
    # series. Rejecting it here, at the only point that still knows which
    # worker sent it, keeps that failure a dropped update instead of a
    # cluster-wide outage.
    try:
        encoded_length = len(value.encode("utf-8"))
    except UnicodeEncodeError:
        logger.warning(
            "Dropping vllm_metrics from provider %s: metrics_text contains an unpaired surrogate",
            provider_id,
        )
        return None
    if encoded_length > _MAX_VLLM_METRICS_BYTES:
        logger.warning(
            "Dropping oversized vllm_metrics from provider %s (over %d bytes)",
            provider_id,
            _MAX_VLLM_METRICS_BYTES,
        )
        return None
    return value


def _cancel_benchmarks_for_changed_session(provider_id: int, session_id: str | None) -> None:
    for job_id, (job_provider_id, expected_session_id) in list(_benchmark_sessions_by_job.items()):
        if job_provider_id == provider_id and expected_session_id != session_id:
            _cancel_benchmark_job(job_id, "Provider restarted or disconnected")


async def _capture_logosnode_provider_snapshot(
    provider_id: int,
    runtime: Dict[str, Any],
) -> None:
    sample = _build_live_local_provider_sample(
        None,
        {
            "last_heartbeat": runtime.get("timestamp"),
            "runtime": runtime,
        },
    )
    if sample is None:
        return
    # Scheduler signals read every status from memory; only the database
    # write below is coalesced and runs off the receive loop.
    await _main._logosnode_registry.record_runtime_sample(provider_id, sample)
    runtime_ts = runtime.get("timestamp")
    count_only = runtime_ts is not None and _last_runtime_ts.get(provider_id) == runtime_ts
    _last_runtime_ts[provider_id] = runtime_ts
    last_write = _last_snapshot_at.get(provider_id)
    if count_only and last_write is not None and time.monotonic() - last_write < _COUNT_ONLY_SNAPSHOT_SECONDS:
        return
    pending = _unsaved_samples.get(provider_id)
    # A status replaced before its write still owes its profiles.
    _unsaved_samples[provider_id] = (sample, count_only and (pending is None or pending[1]))
    if provider_id in _sample_writers:
        return
    task = asyncio.create_task(_write_status_samples(provider_id))
    _sample_writers[provider_id] = task
    _main._background_tasks.add(task)
    task.add_done_callback(_main._background_tasks.discard)


async def _write_status_samples(provider_id: int) -> None:
    """Write a worker's statuses one at a time, newest first, older dropped."""
    try:
        while (entry := _unsaved_samples.pop(provider_id, None)) is not None:
            sample, count_only = entry
            _last_snapshot_at[provider_id] = time.monotonic()
            persisted = await asyncio.to_thread(_persist_logosnode_status, provider_id, sample, count_only)
            if persisted is None:
                continue
            changed_models, rejected_models = persisted
            if changed_models:
                _schedule_model_profile_push(provider_id, changed_models)
            if rejected_models:
                _schedule_model_profile_resync(provider_id, rejected_models)
            elif not count_only:
                _resync_rounds.pop(provider_id, None)
    finally:
        _sample_writers.pop(provider_id, None)


def _persist_logosnode_status(
    provider_id: int, sample: Dict[str, Any], count_only: bool = False
) -> tuple[list[str], list[str]] | None:
    """Store one status sample; None when even the snapshot failed.

    Returns, as ``_persist_model_profiles``, the models the worker must be
    sent. A count-only status repeats profiles that are already stored.
    """
    timestamp = _parse_iso_datetime(sample.get("timestamp"))
    used_bytes = int(float(sample.get("used_vram_mb") or 0.0) * 1024 * 1024)
    total_vram_mb = sample.get("total_vram_mb")
    total_bytes = None
    if total_vram_mb is not None:
        total_bytes = int(float(total_vram_mb or 0.0) * 1024 * 1024)
    free_vram_mb = sample.get("remaining_vram_mb")
    free_bytes = None
    if free_vram_mb is not None:
        free_bytes = int(float(free_vram_mb or 0.0) * 1024 * 1024)
    runtime_payload = sample.get("runtime_payload") if isinstance(sample.get("runtime_payload"), dict) else {}
    # Profiles live in model_profiles; copying them into every snapshot only
    # grew a column nothing reads.
    snapshot_payload = {key: value for key, value in runtime_payload.items() if key != "model_profiles"}

    changed_models: list[str] = []
    rejected_models: list[str] = []
    try:
        with DBManager() as db:
            db.insert_provider_snapshot(
                provider_id=provider_id,
                snapshot_ts=timestamp,
                total_models_loaded=int(sample.get("models_loaded") or 0),
                total_vram_used_bytes=used_bytes,
                total_memory_bytes=total_bytes,
                free_memory_bytes=free_bytes,
                loaded_models=list(sample.get("loaded_models") or []),
                snapshot_source=str(sample.get("snapshot_source") or "logosnode-runtime"),
                runtime_payload=snapshot_payload,
                scheduler_signals=(
                    sample.get("scheduler_signals") if isinstance(sample.get("scheduler_signals"), dict) else {}
                ),
                poll_success=True,
            )
            model_profiles = runtime_payload.get("model_profiles")
            if not count_only and isinstance(model_profiles, dict) and model_profiles:
                try:
                    changed_models, rejected_models = _persist_model_profiles(db, provider_id, model_profiles)
                except Exception:
                    db.session.rollback()
                    logger.warning(
                        "Failed to upsert model profiles for provider %s, the "
                        "entire row update (base_residency_mb, loaded_vram_mb, "
                        "kv_budget_mb, measurement_count, last_measured_at) is "
                        "lost until this recovers",
                        _resolve_provider_name(provider_id),
                        exc_info=True,
                    )
    except Exception:
        # Persisting a VRAM snapshot must never drop the worker's live session.
        # A missing table (the webservice migration that renames it has not run
        # yet) or a transient database error is logged and the next status
        # message retries; the worker stays connected and the capacity planner
        # degrades to its last known snapshot instead of going dark.
        logger.warning(
            "Failed to persist provider snapshot for %s; worker session stays "
            "connected and the next status message retries",
            _resolve_provider_name(provider_id),
            exc_info=True,
        )
        return None
    return changed_models, rejected_models


def _persist_model_profiles(
    db: DBManager, provider_id: int, model_profiles: Dict[str, Any]
) -> tuple[list[str], list[str]]:
    """Store a worker's echoed profiles in one transaction.

    Returns the models with a new central revision, and the models whose
    echo was rejected as outdated; the worker must be sent both.
    """
    if not is_central_profile_payload(model_profiles):
        _mirror_local_profiles(db, provider_id, model_profiles)
        return [], []
    now = time.monotonic()
    changed: list[str] = []
    rejected: list[str] = []
    written: dict[str, tuple[str, str]] = {}
    recorded: dict[str, float] = {}
    for model_name, echoed in model_profiles.items():
        if not isinstance(echoed, dict):
            continue
        try:
            revision = int(echoed.get("sync_revision") or 0)
        except (TypeError, ValueError):
            continue
        stored = persistable_profile(echoed)
        key_hash = echoed.get("calibration_key_hash") or None
        digest = profile_digest(revision, echoed)
        material = profile_digest(revision, material_profile(echoed))
        if not _profile_write_cache.unchanged(provider_id, model_name, digest, material, now):
            if not db.persist_central_model_profile(
                provider_id,
                model_name,
                stored,
                reported_profile(echoed),
                revision,
                key_hash,
                overridden_fields(echoed),
            ):
                rejected.append(model_name)
                continue
            written[model_name] = (digest, material)
        if not is_new_local_calibration(echoed):
            continue
        epoch = float(echoed["last_measured_epoch"])
        if _recorded_calibrations.get((provider_id, model_name)) == epoch:
            continue
        new_revision = db.record_model_calibration(
            provider_id,
            model_name,
            calibration_snapshot(stored),
            echoed.get("calibration_key") if isinstance(echoed.get("calibration_key"), dict) else None,
            key_hash,
            datetime.datetime.fromtimestamp(epoch, tz=datetime.timezone.utc),
        )
        recorded[model_name] = epoch
        if new_revision is not None:
            changed.append(model_name)
    db.session.commit()
    # Only now: a rolled-back write must not count as stored.
    for model_name, (digest, material) in written.items():
        _profile_write_cache.remember(provider_id, model_name, digest, material, now)
    for model_name in changed:
        _profile_write_cache.forget(provider_id, model_name)
    for model_name, epoch in recorded.items():
        _recorded_calibrations[(provider_id, model_name)] = epoch
    return changed, rejected


def _mirror_local_profiles(db: DBManager, provider_id: int, model_profiles: Dict[str, Any]) -> None:
    """Mirror a worker that still keeps its own profile file."""
    pending = {
        model_name: (data, profile_digest(0, data))
        for model_name, data in model_profiles.items()
        if isinstance(data, dict)
    }
    pending = {
        model_name: entry
        for model_name, entry in pending.items()
        if not _profile_write_cache.unchanged(provider_id, model_name, entry[1])
    }
    if not pending:
        return
    db.upsert_model_profiles(provider_id, {model_name: data for model_name, (data, _) in pending.items()})
    for model_name, (_, digest) in pending.items():
        _profile_write_cache.remember(provider_id, model_name, digest)


def _load_effective_profiles(provider_id: int, model_names: list[str] | None = None) -> Dict[str, Dict[str, Any]]:
    with DBManager() as db:
        rows = db.get_central_model_profiles(provider_id, model_names)
    return {str(row["model_name"]): effective_profile(provider_id, row) for row in rows}


async def _push_model_profiles(
    provider_id: int,
    model_names: list[str] | None = None,
    calibration_key_hashes: Dict[str, str] | None = None,
) -> None:
    """Send the stored profiles to a worker that syncs with the database."""
    if not _main._logosnode_registry.supports_action(provider_id, SYNC_MODEL_PROFILES_ACTION):
        return
    try:
        if calibration_key_hashes:
            await asyncio.to_thread(_update_reported_calibration_keys, provider_id, calibration_key_hashes)
        profiles = await asyncio.to_thread(_load_effective_profiles, provider_id, model_names)
        await _main._logosnode_registry.send_command(
            provider_id,
            SYNC_MODEL_PROFILES_ACTION,
            params={"profiles": profiles},
            timeout_seconds=30,
        )
    except Exception:
        # The worker keeps its current profiles; the next hello pushes again.
        logger.warning(
            "Failed to push model profiles to provider %s",
            _resolve_provider_name(provider_id),
            exc_info=True,
        )


def _update_reported_calibration_keys(provider_id: int, calibration_key_hashes: Dict[str, str]) -> None:
    with DBManager() as db:
        db.update_reported_calibration_keys(provider_id, calibration_key_hashes)


def _schedule_model_profile_push(
    provider_id: int,
    model_names: list[str] | None = None,
    calibration_key_hashes: Dict[str, str] | None = None,
) -> None:
    task = asyncio.create_task(_push_model_profiles(provider_id, model_names, calibration_key_hashes))
    _main._background_tasks.add(task)
    task.add_done_callback(_main._background_tasks.discard)


def _schedule_model_profile_resync(provider_id: int, model_names: list[str]) -> None:
    """Re-send profiles a worker has not adopted, e.g. after a failed push.

    Every status repeats the rejected echo; all of them share one push, and
    each further round without an accepted echo waits twice as long.
    """
    pending = _pending_resyncs.get(provider_id)
    if pending is not None:
        pending.update(model_names)
        return
    _pending_resyncs[provider_id] = set(model_names)
    rounds = _resync_rounds.get(provider_id, 0)
    _resync_rounds[provider_id] = rounds + 1
    delay = min(_RESYNC_DELAY_SECONDS * 2 ** min(rounds, 16), _RESYNC_MAX_DELAY_SECONDS)
    task = asyncio.create_task(_run_model_profile_resync(provider_id, delay))
    _main._background_tasks.add(task)
    task.add_done_callback(_main._background_tasks.discard)


async def _run_model_profile_resync(provider_id: int, delay: float = _RESYNC_DELAY_SECONDS) -> None:
    try:
        await asyncio.sleep(delay)
    finally:
        model_names = _pending_resyncs.pop(provider_id, set())
    if model_names:
        await _push_model_profiles(provider_id, sorted(model_names))


def _string_map(value: Any) -> Dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(k): str(v) for k, v in value.items() if isinstance(v, str) and v}


def _capture_calibration_probe_log(provider_id: int, event: Dict[str, Any]) -> None:
    """Persist a worker's ``calibration_probe_log`` event into the DB.

    Fired once per model per calibration attempt (see
    ``LogosBridgeClient._record_calibration_probe_log`` on the worker side).
    Keeps only the most recent row per (provider_id, model_name) via
    ``upsert_calibration_probe_log``'s ON CONFLICT — mirrors how
    ``upsert_model_profiles`` above keeps one row per (provider_id,
    model_name).
    """
    model_name = str(event.get("model") or "").strip()
    if not model_name:
        return
    recorded_at = _parse_iso_datetime(event.get("timestamp"))
    details_raw = event.get("details")
    payload = json.loads(details_raw) if isinstance(details_raw, str) and details_raw else {}
    if not isinstance(payload, dict):
        return
    # Pop out before it goes into `summary` below — otherwise the (large,
    # deliberately un-truncated) raw log text would be duplicated into both
    # the dedicated `log_text` column and the JSONB summary blob.
    log_text = payload.pop("log_text", None)

    with DBManager() as db:
        db.upsert_calibration_probe_log(provider_id, model_name, recorded_at, payload, log_text)


def _require_root_access(logos_key: str) -> None:
    with DBManager() as db:
        require_logos_admin_key(logos_key, db)


def _logosnode_insecure_dev_mode_enabled() -> bool:
    raw = os.getenv("LOGOS_NODE_DEV_ALLOW_INSECURE_HTTP", "")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _central_hf_token() -> str:
    return os.getenv("HF_TOKEN", "").strip()


def _is_tls_request(request: Request) -> bool:
    if _logosnode_insecure_dev_mode_enabled():
        return True
    if request.url.scheme == "https":
        return True
    forwarded = request.headers.get("x-forwarded-proto", "")
    forwarded_values = [item.strip().lower() for item in forwarded.split(",") if item.strip()]
    return "https" in forwarded_values


def _require_tls_request(request: Request) -> None:
    if not _is_tls_request(request):
        # Name what actually arrived. A worker that dials https:// and still
        # lands here was stripped of its TLS signal somewhere in the proxy
        # chain (an untrusted hop rewrites X-Forwarded-Proto to the plain
        # scheme of its own entrypoint), and without these two values the
        # rejection is indistinguishable from a genuinely cleartext caller.
        raise HTTPException(
            status_code=400,
            detail=(
                "TLS is required for logosnode auth/session endpoints "
                f"(request arrived with scheme={request.url.scheme!r}, "
                f"x-forwarded-proto={request.headers.get('x-forwarded-proto', '')!r}; "
                "if the caller used https, a reverse-proxy hop is dropping the "
                "forwarded headers)"
            ),
        )


def _build_logosnode_ws_url(request: Request, token: str) -> str:
    _require_tls_request(request)
    ws_scheme = "ws" if _logosnode_insecure_dev_mode_enabled() else "wss"
    host = request.headers.get("host", "")
    if not host:
        raise HTTPException(status_code=400, detail="Missing Host header for websocket URL generation")
    return f"{ws_scheme}://{host}/logosdb/providers/logosnode/session?token={token}"


def _is_tls_websocket(websocket: WebSocket) -> bool:
    if _logosnode_insecure_dev_mode_enabled():
        return True
    if websocket.url.scheme in {"wss", "https"}:
        return True
    forwarded = websocket.headers.get("x-forwarded-proto", "")
    forwarded_values = [item.strip().lower() for item in forwarded.split(",") if item.strip()]
    return "https" in forwarded_values or "wss" in forwarded_values


@router.post("/logosdb/providers/logosnode/register", tags=["logosnode"])
async def logosnode_register(data: LogosNodeRegisterRequest):
    """
    Root-only provider bootstrap endpoint for LogosWorkerNode providers.
    """
    _require_root_access(data.logos_key)

    provider_name = (data.provider_name or "").strip()
    if not provider_name:
        raise HTTPException(status_code=400, detail="provider_name is required")

    shared_key = secrets.token_urlsafe(48)
    with DBManager() as db:
        result, code = db.add_provider(
            logos_key=data.logos_key,
            provider_name=provider_name,
            base_url=(data.base_url or "").strip(),
            api_key=shared_key,
            auth_name="",
            auth_format="{}",
            provider_type="logosnode",
            # add_provider rejects a missing privacy_level outright, so omitting
            # it made this endpoint return 400 for every request. The caller
            # states the level (required and validated on the request model) —
            # assuming LOCAL here would hand the most trusted tier to any worker
            # that self-registers, rented hardware included.
            privacy_level=data.privacy_level,
        )

    if code != 200:
        return JSONResponse(status_code=code, content=result)

    provider_id = result.get("provider-id")

    # Create logosnode_provider_keys entry so deployment queries work
    try:
        with DBManager() as db:
            db.sync_logosnode_capabilities(provider_id, [])
    except Exception:
        logger.exception("Failed to create logosnode_provider_keys for provider %s", provider_name)

    return {
        "provider_id": provider_id,
        "provider_name": provider_name,
        "provider_type": "logosnode",
        "shared_key": shared_key,
    }


def _logosnode_provider_for_key(shared_key: str) -> Dict[str, Any]:
    with DBManager() as db:
        provider = db.get_logosnode_provider_by_api_key(shared_key)

    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found for this API key")
    provider_type = _normalize_provider_type(provider.get("provider_type"))
    if provider_type != "logosnode":
        raise HTTPException(status_code=403, detail="Provider is not configured as logosnode")
    return provider


@router.post("/logosdb/providers/logosnode/auth", tags=["logosnode"])
async def logosnode_auth(data: LogosNodeAuthRequest, request: Request):
    """
    Authenticate a LogosWorkerNode by its API key.

    The server resolves the provider from the key. The worker never needs
    to know or send a provider_id.
    """
    _require_tls_request(request)
    provider = _logosnode_provider_for_key(data.shared_key)

    provider_id = provider["id"]
    worker_id = provider.get("name") or f"worker-{provider_id}"

    conflicting_session = await _main._logosnode_registry.get_conflicting_session(
        provider_id,
        worker_id,
        stale_after_seconds=_LOGOSNODE_STATS_STALE_AFTER_SECONDS,
    )
    if conflicting_session is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Worker '{conflicting_session.worker_id}' is already connected. " f"Stop the existing worker first."
            ),
        )
    token = await _main._logosnode_registry.issue_ticket(
        provider_id=provider_id,
        worker_id=worker_id,
        capabilities_models=data.capabilities_models,
        configured_models=data.configured_models or None,
        ttl_seconds=60,
    )
    return {
        "session_token": token,
        "ws_url": _build_logosnode_ws_url(request, token),
        "worker_id": worker_id,
        "expires_in_seconds": 60,
        "hf_token": _central_hf_token(),
    }


@router.post("/logosdb/providers/logosnode/model-profiles", tags=["logosnode"])
async def logosnode_model_profiles(data: LogosNodeModelProfilesRequest, request: Request):
    """Profiles a worker starts with, before it starts any lane.

    ``legacy_import`` is the worker's former local file, used only once.
    """
    _require_tls_request(request)
    provider = _logosnode_provider_for_key(data.shared_key)
    provider_id = int(provider["id"])

    def _load() -> Dict[str, Dict[str, Any]]:
        if data.legacy_import is not None:
            with DBManager() as db:
                imported = db.import_legacy_model_profiles(
                    provider_id,
                    data.legacy_import.model_profiles,
                    data.legacy_import.unsupported_models,
                )
            if imported:
                logger.info(
                    "Imported %d model profile(s) from the local file of provider %s",
                    imported,
                    _resolve_provider_name(provider_id),
                )
        if data.calibration_key_hashes:
            _update_reported_calibration_keys(provider_id, data.calibration_key_hashes)
        return _load_effective_profiles(provider_id)

    _profile_write_cache.forget(provider_id)
    profiles = await asyncio.to_thread(_load)
    return {"profiles": profiles}


@router.websocket("/logosdb/providers/logosnode/session")
async def logosnode_session(websocket: WebSocket, token: str):
    if not _is_tls_websocket(websocket):
        await websocket.close(code=1008, reason="TLS required")
        return

    ticket = await _main._logosnode_registry.consume_ticket(token)
    if ticket is None:
        await websocket.close(code=1008, reason="Invalid or expired token")
        return

    await websocket.accept()
    try:
        session = await _main._logosnode_registry.attach_session(ticket, websocket)
    except LogosNodeSessionConflictError as exc:
        await websocket.close(code=1008, reason=str(exc))
        return
    _cancel_benchmarks_for_changed_session(ticket.provider_id, session.session_id)

    try:
        while True:
            payload = await websocket.receive_json()
            if not isinstance(payload, dict):
                continue
            msg_type = payload.get("type")
            if msg_type == "hello":
                await _main._logosnode_registry.on_hello(
                    provider_id=ticket.provider_id,
                    worker_id=str(payload.get("worker_id", "")).strip() or ticket.worker_id,
                    capabilities_models=(
                        payload.get("capabilities_models")
                        if isinstance(payload.get("capabilities_models"), list)
                        else None
                    ),
                    configured_models=(
                        payload.get("configured_models") if isinstance(payload.get("configured_models"), list) else None
                    ),
                    max_lanes=(
                        int(payload.get("max_lanes", 0)) if isinstance(payload.get("max_lanes"), (int, float)) else 0
                    ),
                    calibrating=(
                        bool(payload.get("calibrating")) if isinstance(payload.get("calibrating"), bool) else None
                    ),
                    actions=(payload.get("actions") if isinstance(payload.get("actions"), list) else None),
                )
                _schedule_model_profile_push(
                    ticket.provider_id,
                    calibration_key_hashes=_string_map(payload.get("calibration_key_hashes")),
                )
            elif msg_type == "status":
                runtime = payload.get("runtime") if isinstance(payload.get("runtime"), dict) else {}
                await _main._logosnode_registry.update_runtime(
                    provider_id=ticket.provider_id,
                    runtime=runtime,
                    capabilities_models=(
                        payload.get("capabilities_models")
                        if isinstance(payload.get("capabilities_models"), list)
                        else None
                    ),
                    configured_models=(
                        payload.get("configured_models") if isinstance(payload.get("configured_models"), list) else None
                    ),
                    calibrating=(
                        bool(payload.get("calibrating")) if isinstance(payload.get("calibrating"), bool) else None
                    ),
                )
                await _capture_logosnode_provider_snapshot(ticket.provider_id, runtime)
            elif msg_type == "event":
                event = payload.get("event") if isinstance(payload.get("event"), dict) else {}
                await _main._logosnode_registry.append_event(
                    provider_id=ticket.provider_id,
                    event=event,
                    replay=bool(payload.get("replay", False)),
                )
                if event.get("event") == "calibration_probe_log":
                    try:
                        await asyncio.to_thread(_capture_calibration_probe_log, ticket.provider_id, event)
                    except Exception:
                        logger.debug(
                            "Failed to persist calibration probe log for provider %s",
                            _resolve_provider_name(ticket.provider_id),
                            exc_info=True,
                        )
            elif msg_type == "heartbeat":
                await _main._logosnode_registry.mark_heartbeat(ticket.provider_id)
            elif msg_type == "vllm_metrics":
                metrics_text = _validated_vllm_metrics_text(
                    payload.get("metrics_text", ""), provider_id=ticket.provider_id
                )
                if metrics_text is not None:
                    await _main._logosnode_registry.on_vllm_metrics(ticket.provider_id, metrics_text)
            elif msg_type == "command_result":
                await _main._logosnode_registry.on_command_result(ticket.provider_id, payload)
            elif msg_type == "stream_start":
                await _main._logosnode_registry.on_stream_start(ticket.provider_id, payload)
            elif msg_type == "stream_chunk":
                await _main._logosnode_registry.on_stream_chunk(ticket.provider_id, payload)
            elif msg_type == "stream_end":
                await _main._logosnode_registry.on_stream_end(ticket.provider_id, payload)
    except WebSocketDisconnect:
        pass
    finally:
        await _main._logosnode_registry.detach_session(ticket.provider_id, websocket)
        current = _main._logosnode_registry.peek_runtime_snapshot(ticket.provider_id)
        _cancel_benchmarks_for_changed_session(
            ticket.provider_id,
            str(current["session_id"]) if current else None,
        )


@router.post("/logosdb/providers/logosnode/status", tags=["logosnode"])
async def logosnode_status(data: LogosNodeStatusRequest):
    _require_root_access(data.logos_key)
    try:
        return await _main._logosnode_registry.get_runtime_snapshot(data.provider_id)
    except LogosNodeOfflineError as exc:
        return JSONResponse(status_code=503, content={"error": str(exc)})


@router.post("/logosdb/providers/logosnode/devices", tags=["logosnode"])
async def logosnode_devices(data: LogosNodeStatusRequest):
    _require_root_access(data.logos_key)
    try:
        return {"devices": await _main._logosnode_registry.get_devices(data.provider_id)}
    except LogosNodeOfflineError as exc:
        return JSONResponse(status_code=503, content={"error": str(exc)})


@router.post("/logosdb/providers/logosnode/lanes", tags=["logosnode"])
async def logosnode_lanes(data: LogosNodeStatusRequest):
    _require_root_access(data.logos_key)
    try:
        return {"lanes": await _main._logosnode_registry.get_lanes(data.provider_id)}
    except LogosNodeOfflineError as exc:
        return JSONResponse(status_code=503, content={"error": str(exc)})


@router.post("/logosdb/providers/logosnode/lanes/apply", tags=["logosnode"])
async def logosnode_apply_lanes(data: LogosNodeApplyLanesRequest):
    _require_root_access(data.logos_key)
    return await _dispatch_logosnode_command(
        provider_id=data.provider_id,
        action="apply_lanes",
        params={"lanes": data.lanes},
    )


@router.post("/logosdb/providers/logosnode/lanes/sleep", tags=["logosnode"])
async def logosnode_sleep_lane(data: LogosNodeSleepLaneRequest):
    _require_root_access(data.logos_key)
    return await _dispatch_logosnode_command(
        provider_id=data.provider_id,
        action="sleep_lane",
        params={"lane_id": data.lane_id, "level": data.level, "mode": data.mode},
    )


@router.post("/logosdb/providers/logosnode/lanes/wake", tags=["logosnode"])
async def logosnode_wake_lane(data: LogosNodeWakeLaneRequest):
    _require_root_access(data.logos_key)
    return await _dispatch_logosnode_command(
        provider_id=data.provider_id,
        action="wake_lane",
        params={"lane_id": data.lane_id},
    )


@router.post("/logosdb/providers/logosnode/lanes/delete", tags=["logosnode"])
async def logosnode_delete_lane(data: LogosNodeDeleteLaneRequest):
    _require_root_access(data.logos_key)
    return await _dispatch_logosnode_command(
        provider_id=data.provider_id,
        action="delete_lane",
        params={"lane_id": data.lane_id},
    )


@router.post("/logosdb/providers/logosnode/lanes/reconfigure", tags=["logosnode"])
async def logosnode_reconfigure_lane(data: LogosNodeReconfigureLaneRequest):
    _require_root_access(data.logos_key)
    return await _dispatch_logosnode_command(
        provider_id=data.provider_id,
        action="reconfigure_lane",
        params={"lane_id": data.lane_id, "updates": data.updates},
    )


@router.post("/logosdb/providers/logosnode/calibrate_uncalibrated", tags=["logosnode"])
async def logosnode_calibrate_uncalibrated(data: LogosNodeStatusRequest):
    """Kick off a worker-driven calibration session immediately.

    The worker picks which uncalibrated models to run and walks them one at
    a time, emitting ``calibration_*`` events as each completes. The server
    no longer chooses models or polls status — the response just confirms
    the session was started and reports which models the worker will see
    as uncalibrated right now.
    """
    _require_root_access(data.logos_key)
    snap = _main._logosnode_registry.peek_runtime_snapshot(data.provider_id)
    if snap is None:
        return JSONResponse(status_code=503, content={"error": "Worker not connected"})
    if not snap.get("first_status_received"):
        return JSONResponse(
            status_code=503,
            content={"error": "Worker has not sent its first status yet"},
        )
    models = _find_uncalibrated_models_on_provider(data.provider_id)
    if not models:
        return {
            "message": "No uncalibrated models on this worker",
            "count": 0,
            "models": [],
        }
    sleep_level = (
        _main._calibration_orchestrator._config.sleep_level if _main._calibration_orchestrator is not None else 1
    )
    pname = _resolve_provider_name(data.provider_id)
    try:
        await _main._logosnode_registry.send_command(
            data.provider_id,
            "start_calibration_session",
            params={"sleep_level": sleep_level},
            timeout_seconds=30,
        )
    except LogosNodeOfflineError as exc:
        logger.warning("Admin calibrate-uncalibrated: provider=%s offline: %s", pname, exc)
        return JSONResponse(status_code=503, content={"error": "Worker not connected"})
    except LogosNodeCommandError as exc:
        logger.warning(
            "Admin calibrate-uncalibrated: start_calibration_session refused on provider=%s: %s",
            pname,
            exc,
        )
        return JSONResponse(status_code=409, content={"error": str(exc)})
    logger.info(
        "Admin calibrate-uncalibrated: session started on provider=%s (%d candidate model(s))",
        pname,
        len(models),
    )
    return {
        "message": f"Calibration session started on {pname} ({len(models)} candidate model(s))",
        "count": len(models),
        "models": models,
    }


@router.post("/logosdb/providers/logosnode/stop_calibration", tags=["logosnode"])
async def logosnode_stop_calibration(data: LogosNodeStatusRequest):
    """Cancel a worker's in-progress calibration session, if any.

    The worker owns the teardown via cancel_event; nothing partial is
    written for the model in progress — it's just left uncalibrated for
    a later session.
    """
    _require_root_access(data.logos_key)
    snap = _main._logosnode_registry.peek_runtime_snapshot(data.provider_id)
    if snap is None:
        return JSONResponse(status_code=503, content={"error": "Worker not connected"})
    pname = _resolve_provider_name(data.provider_id)
    try:
        result = await _main._logosnode_registry.send_command(
            data.provider_id,
            "stop_calibration_session",
            timeout_seconds=30,
        )
    except LogosNodeOfflineError as exc:
        logger.warning("Admin stop-calibration: provider=%s offline: %s", pname, exc)
        return JSONResponse(status_code=503, content={"error": "Worker not connected"})
    except LogosNodeCommandError as exc:
        logger.warning(
            "Admin stop-calibration: stop_calibration_session failed on provider=%s: %s",
            pname,
            exc,
        )
        return JSONResponse(status_code=409, content={"error": str(exc)})
    was_active = bool(result.get("was_active", False))
    current_model = result.get("current_model")
    logger.info(
        "Admin stop-calibration: provider=%s was_active=%s current_model=%s",
        pname,
        was_active,
        current_model or "<none>",
    )
    return JSONResponse(
        content={
            "message": (
                f"Calibration session on {pname} cancelled (was calibrating {current_model})"
                if was_active
                else f"No calibration session was running on {pname}"
            ),
            "was_active": was_active,
            "current_model": current_model,
        }
    )


@router.post("/logosdb/providers/logosnode/model-profiles/clear-unsupported", tags=["logosnode"])
async def logosnode_clear_unsupported(data: LogosNodeClearUnsupportedRequest):
    """Let calibration retry a model a node marked permanently unsupported."""
    _require_root_access(data.logos_key)

    def _clear() -> int | None:
        with DBManager() as db:
            return db.clear_calibration_unsupported(data.provider_id, data.model_name)

    revision = await asyncio.to_thread(_clear)
    if revision is None:
        return JSONResponse(
            status_code=404,
            content={"error": f"{data.model_name} is not marked unsupported on provider {data.provider_id}"},
        )
    _profile_write_cache.forget(data.provider_id, data.model_name)
    await _push_model_profiles(data.provider_id, [data.model_name])
    return {"provider_id": data.provider_id, "model_name": data.model_name, "sync_revision": revision}


@router.post("/logosdb/providers/logosnode/model-calibrations/invalidate", tags=["logosnode"])
async def logosnode_invalidate_calibration(data: LogosNodeInvalidateCalibrationRequest):
    """Stop trusting a calibration; nodes using it re-calibrate the model."""
    _require_root_access(data.logos_key)

    def _invalidate() -> list[tuple[int, str]]:
        with DBManager() as db:
            return db.invalidate_model_calibration(data.calibration_id, data.reason)

    affected = await asyncio.to_thread(_invalidate)
    by_provider: Dict[int, list[str]] = {}
    for provider_id, model_name in affected:
        _profile_write_cache.forget(provider_id, model_name)
        by_provider.setdefault(provider_id, []).append(model_name)
    for provider_id, model_names in by_provider.items():
        await _push_model_profiles(provider_id, model_names)
    return {
        "calibration_id": data.calibration_id,
        "affected": [{"provider_id": pid, "model_name": name} for pid, name in affected],
    }


@router.post("/logosdb/providers/logosnode/model-profiles/reset", tags=["logosnode"])
async def logosnode_reset_profiles(data: LogosNodeResetProfilesRequest):
    """Empty a node's profiles so its next calibration measures from scratch.

    A connected worker adopts the empty profiles at once; echoes of its old
    state carry an outdated revision and are rejected.
    """
    _require_root_access(data.logos_key)

    def _reset() -> list[str]:
        with DBManager() as db:
            return db.reset_model_profiles(data.provider_id, data.model_names)

    reset = await asyncio.to_thread(_reset)
    for model_name in reset:
        _profile_write_cache.forget(data.provider_id, model_name)
        _recorded_calibrations.pop((data.provider_id, model_name), None)
    if reset:
        await _push_model_profiles(data.provider_id, reset)
    return {"provider_id": data.provider_id, "reset": reset}
