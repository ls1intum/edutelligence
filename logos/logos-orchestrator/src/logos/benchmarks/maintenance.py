"""Cluster-wide admission and confirmed completion of worker calibration."""

import logging
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta

from logos.benchmarks import nightly_store as store
from logos.maintenance_window import maintenance_node_limit

logger = logging.getLogger(__name__)

AUTOMATIC_CALIBRATION = ContextVar("automatic_calibration", default=False)

# A start whose reply was lost keeps an unconfirmed claim. The worker activates
# its session before it answers, so once this has passed since the claim, an
# idle status proves the start never took effect or has already finished.
# Longer than the longest lane command (900 s): a worker that still reads
# commands one at a time can run a start that long after it was sent.
UNCONFIRMED_CLAIM_GRACE = timedelta(minutes=20)

# The worker's only refusal of a start that leaves a session running. Every
# other refusal is answered before the worker creates a session.
SESSION_ALREADY_RUNNING = "calibration session already in progress"

# How a worker answers a command its build does not implement.
UNSUPPORTED_COMMAND = "Unsupported bridge command"


class MaintenanceCoordinator:
    def __init__(self, registry):
        self.registry = registry

    def live_calibration(self):
        return any(self.registry.is_calibrating(pid) for pid in self.registry.active_provider_ids())

    async def start_calibration(self, provider_id, send):
        from logos.logosnode_registry import LogosNodeCommandError, LogosNodeCommandRejectedError, MaintenanceBusyError

        with store.cluster_lock() as connection:
            if connection is None:
                raise MaintenanceBusyError("Calibration or benchmarks already own the maintenance slot")
            occupied = {claim["provider_id"] for claim in store.calibration_claims()}
            occupied.update(pid for pid in self.registry.active_provider_ids() if self.registry.is_calibrating(pid))
            if (
                provider_id in occupied
                or len(occupied) >= maintenance_node_limit()
                or store.has_active_benchmarks()
                or store.has_recovery()
            ):
                raise MaintenanceBusyError("Calibration, benchmarks or recovery already own the maintenance slot")
            token = str(uuid.uuid4())
            store.claim_calibration(provider_id, token, AUTOMATIC_CALIBRATION.get())
            dispatched = False

            def on_dispatched(_):
                nonlocal dispatched
                if not store.lock_held(connection):
                    raise LogosNodeCommandError("Maintenance lock was lost before calibration dispatch")
                dispatched = True

            try:
                result = await send(on_dispatched)
            except LogosNodeCommandRejectedError as exc:
                if SESSION_ALREADY_RUNNING not in str(exc):
                    # No session was started, and none is running.
                    store.release_calibration(token)
                    raise
                # Another session is live, so only a fresh idle reply releases the claim.
                store.confirm_calibration(token)
                try:
                    await self._release_if_finished({"provider_id": provider_id, "token": token})
                except Exception:
                    pass  # Reconciliation will retry; uncertainty keeps the slot.
                raise
            except BaseException:
                # A lost reply does not prove that the worker stopped. Keep the
                # durable claim until an operator's stop is confirmed.
                if not dispatched:
                    store.release_calibration(token)
                raise
            store.confirm_calibration(token)
            return result

    async def stop_calibration(self, provider_id, send):
        from logos.logosnode_registry import MaintenanceBusyError

        with store.cluster_lock() as connection:
            if connection is None:
                raise MaintenanceBusyError("Maintenance command is still in progress")
            result = await send()
            for claim in store.calibration_claims():
                if claim["provider_id"] == provider_id:
                    await self._release_if_finished(claim)
            return result

    async def reconcile(self):
        # Acknowledged starts can finish between status pushes. Query the
        # worker directly; stale status and terminal events never release a claim.
        from logos.logosnode_registry import LogosNodeCommandError, LogosNodeOfflineError

        completed = []
        with store.cluster_lock() as connection:
            if connection is None:
                return completed
            for claim in store.calibration_claims():
                if not claim["confirmed"] and not _past_grace(claim):
                    continue
                try:
                    # A start never confirmed may not have run: free the slot,
                    # but leave the worker due for calibration this window.
                    if await self._release_if_finished(claim) and claim["confirmed"]:
                        completed.append(claim["provider_id"])
                except (LogosNodeOfflineError, LogosNodeCommandError, TimeoutError) as exc:
                    logger.warning(
                        "Calibration status unavailable for provider %s (%s); claim %s remains reserved. "
                        "Reconnect and stop calibration, or follow the offline calibration recovery procedure.",
                        claim["provider_id"],
                        exc,
                        claim["token"],
                    )
        return completed

    async def release_claim(self, provider_id, token):
        """Release one calibration claim on an operator's request.

        Tries a normal stop first. The claim is released without the worker's
        confirmation only when the worker is offline, or when it answers the
        stop or the status query with an error and its status reports show no
        session. An online worker that does not answer keeps its claim, and so
        does a worker that still reports a session.
        """
        from logos.logosnode_registry import LogosNodeCommandError, LogosNodeOfflineError, MaintenanceBusyError

        with store.cluster_lock() as connection:
            if connection is None:
                raise MaintenanceBusyError("Maintenance command is still in progress")
            claim = next(
                (c for c in store.calibration_claims() if c["token"] == token and c["provider_id"] == provider_id),
                None,
            )
            if claim is None:
                raise LookupError("The calibration claim no longer exists")
            failure = "worker offline"
            online = self.registry.is_provider_online(provider_id)
            if online and not claim["confirmed"] and not _past_grace(claim):
                # The start may still be queued on the worker and run after a stop.
                raise MaintenanceBusyError("The calibration start may still be running. Try again later.")
            if online:
                try:
                    # Sent directly: send_command would route the stop back here.
                    await self.registry._send_command(provider_id, "stop_calibration_session", {}, 30)
                    if await self._release_if_finished(claim):
                        return {"released": True, "forced": False}
                    raise MaintenanceBusyError("The worker still reports a calibration session")
                except MaintenanceBusyError:
                    raise
                except (LogosNodeOfflineError, TimeoutError) as exc:
                    # No answer is no proof of a stop: the worker may only be busy.
                    if self.registry.is_provider_online(provider_id):
                        raise MaintenanceBusyError(
                            "The worker did not answer. Try again, or release the claim once it is offline."
                        ) from exc
                    failure = str(exc) or type(exc).__name__
                except LogosNodeCommandError as exc:
                    # The worker answered, so its status reports are current.
                    failure = str(exc) or type(exc).__name__
                if self.registry.is_calibrating(provider_id):
                    raise MaintenanceBusyError("The worker still reports a calibration session")
            store.release_calibration(token)
            logger.warning(
                "Calibration claim %s for provider %s released by an operator without worker confirmation "
                "(%s; automatic=%s, confirmed=%s, age=%ss)",
                token,
                provider_id,
                failure,
                claim.get("automatic"),
                claim.get("confirmed"),
                int(float(claim.get("age_s") or 0)),
            )
            return {"released": True, "forced": True}

    async def release_recovery(self, pair_id, force=False):
        """Release a nightly recovery journal on an operator's request.

        Without ``force`` the worker must show the journal's lane with its
        original ``vllm_config``, so releasing only drops bookkeeping. With
        ``force`` the journal is dropped without that proof; the lane keeps
        whatever settings it runs now. Either way the recovery's own orphaned
        benchmark jobs are failed and the worker's reservation is lifted.
        """
        import importlib

        from logos.benchmarks.reservations import benchmark_reservations
        from logos.logosnode_registry import LogosNodeCommandError, LogosNodeOfflineError, MaintenanceBusyError

        main = importlib.import_module("logos.main")
        with store.cluster_lock() as connection:
            if connection is None:
                raise MaintenanceBusyError("Maintenance command is still in progress")
            row = next((r for r in store.rows() if r["model_provider_id"] == pair_id and r["recovery"]), None)
            if row is None:
                raise LookupError("No nightly recovery is pending for this deployment")
            recovery = row["recovery"]
            with store.execution_lock(pair_id) as execution:
                if execution is None:
                    raise MaintenanceBusyError("A recovery is running right now")
                jobs = store.recovery_jobs(pair_id)
                if any(not task.done() for job, task in main._benchmark_tasks_by_job.items() if job in jobs):
                    raise MaintenanceBusyError("A benchmark of this recovery is still running")
                provider_id = recovery.get("provider_id")
                if not force and recovery.get("mutated", True):
                    try:
                        runtime = await self.registry.send_command(provider_id, "get_lanes", {}, timeout_seconds=30)
                    except (LogosNodeOfflineError, LogosNodeCommandError, TimeoutError) as exc:
                        raise MaintenanceBusyError(
                            f"The worker cannot confirm the original settings ({str(exc) or type(exc).__name__})"
                        ) from exc
                    lane = next(
                        (lane for lane in runtime.get("lanes") or [] if lane.get("lane_id") == recovery.get("lane_id")),
                        None,
                    )
                    if lane is None:
                        raise MaintenanceBusyError("The recovered lane is not loaded on the worker")
                    if (lane.get("lane_config") or {}).get("vllm_config") != recovery.get("vllm_config"):
                        raise MaintenanceBusyError("The lane does not run its original settings yet")
                if not store.lock_held(connection) or not store.execution_lock_held(execution, pair_id):
                    raise MaintenanceBusyError("Maintenance command is still in progress")
                if jobs:
                    store.fence_recovery_jobs(jobs)
                    store.finish_recovery_jobs(jobs)
                    for job in jobs:
                        benchmark_reservations.release(job)
                store.save(pair_id, "interrupted_recovered", row["report"], None)
                benchmark_reservations.release(-pair_id)
        logger.warning(
            "Nightly recovery %s for provider %s, lane %s released by an operator (forced=%s, jobs=%s)",
            pair_id,
            provider_id,
            recovery.get("lane_id"),
            bool(force),
            jobs,
        )
        return {"released": True, "forced": bool(force)}

    def slot_status(self):
        """Everything that holds the maintenance slot right now."""
        holders = store.maintenance_holders()
        calibrations = []
        for claim in holders["calibrations"]:
            pid = claim["provider_id"]
            calibrations.append(
                {
                    "provider_id": pid,
                    "provider_name": claim.get("provider_name"),
                    "claim_token": claim["token"],
                    "automatic": bool(claim["automatic"]),
                    "confirmed": bool(claim["confirmed"]),
                    "since": claim["created_at"],
                    "age_s": _seconds(claim.get("age_s")),
                    **self._worker_state(pid),
                }
            )
        claimed = {claim["provider_id"] for claim in calibrations}
        for pid in self.registry.active_provider_ids():
            # A session without a claim, e.g. started before the coordinator, also holds the slot.
            if pid not in claimed and self.registry.is_calibrating(pid):
                calibrations.append(
                    {
                        "provider_id": pid,
                        "provider_name": None,
                        "claim_token": None,
                        "automatic": None,
                        "confirmed": None,
                        "since": None,
                        "age_s": None,
                        **self._worker_state(pid),
                    }
                )
        benchmarks = [{**row, "age_s": _seconds(row.get("age_s"))} for row in holders["benchmarks"]]
        recoveries = [{**row, "age_s": _seconds(row.get("age_s"))} for row in holders["recoveries"]]
        return {
            "limit": maintenance_node_limit(),
            "free": not (calibrations or benchmarks or recoveries),
            "calibrations": calibrations,
            "benchmarks": benchmarks,
            "recoveries": recoveries,
        }

    def _worker_state(self, provider_id):
        return {
            "online": self.registry.is_provider_online(provider_id),
            "calibrating": self.registry.is_calibrating(provider_id),
            "status_supported": self.registry.supports_action(provider_id, "get_calibration_status"),
        }

    async def _release_if_finished(self, claim):
        from logos.logosnode_registry import LogosNodeCommandError

        try:
            result = await self.registry.send_command(
                claim["provider_id"], "get_calibration_status", {}, timeout_seconds=20
            )
        except LogosNodeCommandError as exc:
            if UNSUPPORTED_COMMAND not in str(exc):
                raise
            # The connected worker has no status command, so its status
            # reports are the only account of its session left.
            result = {"calibrating": bool(self.registry.is_calibrating(claim["provider_id"]))}
        if result.get("calibrating") is False:
            store.release_calibration(claim["token"])
            return True

    async def run_benchmark(self, job_id, execute):
        try:
            return await execute()
        finally:
            # Run only after GuideLLM and its cancellation cleanup have ended.
            store.release_benchmark(job_id)


def _seconds(value):
    return None if value is None else int(float(value))


def _past_grace(claim):
    age_s = claim.get("age_s")
    if age_s is not None:
        return float(age_s) >= UNCONFIRMED_CLAIM_GRACE.total_seconds()
    created_at = claim.get("created_at")
    return created_at is not None and datetime.now(UTC) - created_at >= UNCONFIRMED_CLAIM_GRACE
