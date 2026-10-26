"""Application-owned nightly runs with a bounded number of maintenance workers."""

import asyncio
import copy
import json
import logging

from starlette.requests import Request

from logos.benchmarks import nightly_store as store
from logos.benchmarks.guidellm_runner import extract_serving_configuration
from logos.benchmarks.maintenance import AUTOMATIC_CALIBRATION
from logos.benchmarks.nightly import (
    LEASE_CHECK,
    MAX_PAIRS_PER_NIGHT,
    NIGHTLY_CONTEXT,
    NightlyStopped,
    can_start,
    local_now,
    parameter_plan,
)
from logos.benchmarks.reservations import benchmark_reservations
from logos.benchmarks.worker_limits import validate_worker_overrides, worker_limits
from logos.capacity.capacity_planner import MAINTENANCE_RECOVERY
from logos.dbutils.dbmanager import DBManager
from logos.dbutils.dbrequest import InternalBenchmarkRequest
from logos.maintenance_window import maintenance_node_limit

logger = logging.getLogger(__name__)


class NightlyScheduler:
    def __init__(self, registry, planner, calibration=None, maintenance=None):
        self.registry = registry
        self.planner = planner
        self.task = None
        self.calibration = calibration
        self.maintenance = maintenance

    async def start(self):
        # Reinstall persisted reservations before accepting production traffic.
        for row in store.rows():
            if row["recovery"]:
                benchmark_reservations.reserve(row["recovery"]["provider_id"], "*", -row["model_provider_id"])
        self.task = asyncio.create_task(self._loop(), name="nightly-benchmarks")

    async def stop(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)

    async def _loop(self):
        while True:
            try:
                await self._cycle()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Nightly benchmark tick failed")
            await asyncio.sleep(15)

    async def _cycle(self):
        claims = []
        if self.maintenance:
            completed = await self.maintenance.reconcile()
            claims = store.calibration_claims()
            if self.calibration:
                self.calibration._completed_this_window.update(completed)
                # Durable claims are authoritative after a restart or operator recovery.
                self.calibration._active_provider_ids = {claim["provider_id"] for claim in claims if claim["automatic"]}
        if self.calibration and not store.has_recovery() and not store.has_active_benchmarks():
            token = AUTOMATIC_CALIBRATION.set(True)
            try:
                await self.calibration._tick()
            finally:
                AUTOMATIC_CALIBRATION.reset(token)
        await self.tick()

    async def tick(self):
        token = NIGHTLY_CONTEXT.set(True)
        try:
            await self._tick()
        finally:
            NIGHTLY_CONTEXT.reset(token)

    async def _tick(self):
        schedules = store.rows()
        if not any(row["recovery"] for row in schedules) and not can_start(local_now()):
            return
        with store.cluster_lock() as connection:
            if connection is None:
                return
            if self.maintenance and (store.calibration_claims() or self.maintenance.live_calibration()):
                return
            for row in schedules:
                pair_id = row["model_provider_id"]
                if row["recovery"]:
                    try:
                        if not await self.recover(row, connection):
                            return
                    except Exception:
                        # Keep the node excluded and do not take a second node.
                        logger.exception("Nightly worker recovery requires attention")
                        return
            if self.calibration and self.calibration.benchmarks_must_wait():
                return
            # One scheduler owns the cluster lease. Each wave uses distinct
            # workers, and finishes cleanup before another wave can start.
            remaining = list(schedules)
            while remaining:
                selected = []
                providers = set()
                deferred = []
                for row in remaining:
                    pair_id = row["model_provider_id"]
                    day = local_now().date()
                    if (
                        not can_start(local_now())
                        or store.has_active_benchmarks()
                        or (self.calibration and self.calibration.benchmarks_must_wait())
                        or store.claimed_today(day) >= MAX_PAIRS_PER_NIGHT
                    ):
                        break
                    if not row["enabled"] or row["last_run_date"] == day:
                        continue
                    if len(selected) >= maintenance_node_limit():
                        deferred.append(row)
                        continue
                    try:
                        target, _, _ = self.target_lane(pair_id)
                    except RuntimeError as exc:
                        store.save(pair_id, "unavailable", [{"status": "skipped", "reason": str(exc)[:1000]}], None)
                        continue
                    provider_id = int(target["provider_id"])
                    if self.planner.is_worker_locked(provider_id):
                        # The run waits for the next night the worker is not locked.
                        logger.info("Skipping nightly benchmark %s: worker %s is locked", pair_id, provider_id)
                        continue
                    if provider_id in providers:
                        deferred.append(row)
                        continue
                    if not store.lock_held(connection):
                        return
                    if store.claim(pair_id, day):
                        selected.append(pair_id)
                        providers.add(provider_id)
                if not selected:
                    return
                # TaskGroup cancels and awaits every sibling's restoration on failure or shutdown.
                async with asyncio.TaskGroup() as group:
                    tasks = [group.create_task(self.run_schedule(pair, connection)) for pair in selected]
                if not all(task.result() for task in tasks):
                    return
                remaining = deferred

    def healthy(self, provider_id):
        snapshot = self.registry.peek_runtime_snapshot(provider_id) or {}
        health = (snapshot.get("runtime") or {}).get("node_health") or {}
        return (
            health.get("healthy", True) is not False
            and self.registry.is_provider_online(provider_id)
            and self.registry.has_received_first_status(provider_id)
            and not self.registry.is_calibrating(provider_id)
        )

    async def restore(self, pair_id, recovery):
        """Restore the exact original configuration before releasing production traffic."""
        if not recovery.get("mutated", True):
            return
        provider_id = recovery["provider_id"]
        if not self.healthy(provider_id):
            raise RuntimeError("Worker is offline or calibrating; restoration is pending")
        benchmark_reservations.reserve(provider_id, "*", -pair_id)
        runtime = await self.registry.send_command(provider_id, "get_lanes", {}, timeout_seconds=30)
        if not any(lane.get("lane_id") == recovery["lane_id"] for lane in runtime.get("lanes", [])):
            result = await self.registry.send_command(
                provider_id, "add_lane", recovery["lane_config"], timeout_seconds=900
            )
            result["restarted"] = True
        else:
            result = await self.registry.send_command(
                provider_id,
                "reconfigure_lane",
                {
                    "lane_id": recovery["lane_id"],
                    "updates": {"vllm_config": recovery["vllm_config"]},
                    "require_idle": False,
                    "force_restart": True,
                },
                timeout_seconds=900,
            )
        if (
            not result.get("restarted")
            or (result.get("lane_config") or {}).get("vllm_config") != recovery["vllm_config"]
        ):
            raise RuntimeError("Worker did not confirm its original configuration")
        token = MAINTENANCE_RECOVERY.set(True)
        try:
            ready = await self.planner.prepare_benchmark_lane(provider_id, recovery["model"], timeout_seconds=900)
        finally:
            MAINTENANCE_RECOVERY.reset(token)
        if not ready:
            raise RuntimeError("Restored production model is not ready")

    def target_lane(self, pair_id, *, disable_missing=True):
        """Resolve and validate a currently usable model/worker pair."""
        with DBManager() as db:
            target = db.get_model_provider_benchmark_target(pair_id)
        if not target:
            if disable_missing:
                store.disable_missing_target(pair_id)
            raise RuntimeError("The scheduled model/worker deployment no longer exists")
        if target["provider_type"] != "logosnode":
            raise RuntimeError("Nightly benchmarks require a Logos worker")
        pid, model = int(target["provider_id"]), str(target["model_name"])
        if not self.healthy(pid):
            raise RuntimeError("The selected worker must be online and healthy")
        if self.planner.is_worker_locked(pid):
            raise RuntimeError("The selected worker is locked")
        snapshot = self.registry.peek_runtime_snapshot(pid)
        if not (snapshot.get("runtime") or {}).get("supports_benchmark_restart"):
            raise RuntimeError("Update this worker before enabling nightly benchmarks")
        lanes = (snapshot.get("runtime") or {}).get("lanes", [])
        target_lanes = [lane for lane in lanes if lane.get("model") == model]
        if len(target_lanes) != 1 or not (target_lanes[0].get("lane_config") or {}).get("vllm"):
            raise RuntimeError("Nightly tuning requires exactly one existing vLLM lane for this model")
        lane = target_lanes[0]
        if lane.get("runtime_state") not in {"loaded", "running"} or lane.get("sleep_state") == "sleeping":
            raise RuntimeError("Nightly tuning requires the production model to be loaded and awake")
        try:
            limits = worker_limits(snapshot, model)
            baseline = parameter_plan(limits["current"])[0]
            validate_worker_overrides(baseline.serving_overrides, limits)
        except ValueError as exc:
            raise RuntimeError(str(exc)) from exc
        return target, snapshot, lane

    async def recover(self, row, connection):
        """Fence an orphaned nightly execution, confirm drain, then restore its journal."""
        import importlib

        main = importlib.import_module("logos.main")

        pair_id = row["model_provider_id"]
        with store.execution_lock(pair_id) as execution:
            if execution is None:
                return False
            jobs = store.recovery_jobs(pair_id)
            orphan_jobs = list(jobs)
            for other in store.rows():
                other_id = other["model_provider_id"]
                if other_id == pair_id or not other["recovery"]:
                    continue
                # A crashed parallel wave can leave several running jobs.
                # Never treat a sibling as orphaned while its execution lease survives.
                with store.execution_lock(other_id) as sibling:
                    if sibling is None:
                        return False
                orphan_jobs.extend(store.recovery_jobs(other_id))
            # Durable manual claims and unrelated jobs always retain their slot.
            if store.has_active_benchmarks(excluding=orphan_jobs):
                return False
            if any(not task.done() for task in main._benchmark_tasks_by_job.values()):
                return False

            def held():
                return store.lock_held(connection) and store.execution_lock_held(execution, pair_id)

            token = LEASE_CHECK.set(held)
            try:
                if not held():
                    return False
                store.fence_recovery_jobs(jobs)
                for job in jobs:
                    benchmark_reservations.release(job)
                # Cached telemetry cannot prove that requests from the old
                # execution have ended. Query the worker and fail closed.
                recovery = row["recovery"]
                if (jobs or recovery.get("mutated", True)) and not await self.recovery_worker_idle(recovery):
                    return False
                if not held():
                    return False
                store.finish_recovery_jobs(jobs)
                await self.restore(pair_id, recovery)
                store.save(pair_id, "interrupted_recovered", row["report"], None)
                benchmark_reservations.release(-pair_id)
                return True
            finally:
                LEASE_CHECK.reset(token)

    async def recovery_worker_idle(self, recovery):
        """True when the worker reports no request on the lane a recovery restores.

        Only the worker's own counters count. The orchestrator's in-flight
        counter can stay above zero after a request ended, and it cannot see
        requests from the crashed execution anyway.

        The check covers the journal's lane and any lane of the same model:
        those are the only lanes the old execution sent benchmark traffic to,
        and the only ones the restore restarts. Other lanes keep serving
        production and do not hold the recovery back. A journal without lane
        and model falls back to requiring the whole worker to be idle.
        """
        provider_id = recovery["provider_id"]
        if not self.healthy(provider_id):
            return False
        runtime = await self.registry.send_command(provider_id, "get_runtime", {}, timeout_seconds=30)
        lanes = runtime.get("lanes")
        if (runtime.get("node_health") or {}).get("healthy") is False:
            return False
        if not isinstance(lanes, list):
            return False
        lane_id, model = recovery.get("lane_id"), recovery.get("model")
        if lane_id or model:
            lanes = [
                lane
                for lane in lanes
                if (lane_id and lane.get("lane_id") == lane_id) or (model and lane.get("model") == model)
            ]
        for lane in lanes:
            if lane.get("active_requests") != 0:
                return False
            metrics = lane.get("backend_metrics") or {}
            if any(float(metrics.get(key) or 0) != 0 for key in ("requests_running", "queue_waiting")):
                return False
        return True

    async def run_schedule(self, pair_id, connection):
        with store.execution_lock(pair_id) as execution:
            if execution is None:
                return False
            token = LEASE_CHECK.set(
                lambda: store.lock_held(connection) and store.execution_lock_held(execution, pair_id)
            )
            try:
                return await self._run_schedule(pair_id, connection)
            finally:
                LEASE_CHECK.reset(token)

    async def _run_schedule(self, pair_id, connection):
        report = []
        recovery = None
        state = "completed"
        try:
            target, snapshot, lane = self.target_lane(pair_id)
            pid, model = int(target["provider_id"]), str(target["model_name"])
            lanes = (snapshot.get("runtime") or {}).get("lanes", [])
            current = extract_serving_configuration(snapshot, model)
            plan = parameter_plan(current)
            recovery = {
                "provider_id": pid,
                "model": model,
                "lane_id": lane["lane_id"],
                "vllm_config": copy.deepcopy(lane["lane_config"].get("vllm_config") or {}),
                "lane_config": copy.deepcopy(lane["lane_config"]),
                "mutated": False,
            }
            # Journal first; a process restart must not lose the original settings.
            store.save(pair_id, "preparing", report, recovery)
            self.planner._facade.reserve_worker_for_drain(pid, -pair_id)
            async with asyncio.timeout(900):
                for item in lanes:
                    while self.planner._facade.model_inflight_requests(pid, item["model"]) > 0:
                        await asyncio.sleep(1)
                    if not await self.planner._drain_lane(pid, item["lane_id"], 900):
                        raise RuntimeError("Could not drain the worker's existing traffic")
            for index, settings in enumerate(plan):
                if self.calibration and self.calibration.benchmarks_must_wait():
                    state = "calibration_pending"
                    break
                for attempt in range(2):
                    if self.calibration and self.calibration.benchmarks_must_wait():
                        state = "calibration_pending"
                        break
                    if not can_start(local_now()) or not store.status(pair_id)["enabled"]:
                        state = "window_closed" if store.status(pair_id)["enabled"] else "disabled"
                        raise NightlyStopped(state)
                    if not self.healthy(pid):
                        raise RuntimeError("Worker is no longer healthy")
                    if not LEASE_CHECK.get()():
                        raise NightlyStopped("lease_lost")
                    try:
                        validate_worker_overrides(settings.serving_overrides, worker_limits(snapshot, model))
                        recovery["mutated"] = True
                        store.save(pair_id, "running", report, recovery)
                        job_id, task = await self.submit(pair_id, settings)
                        result = await task
                        if result:
                            baseline_id = (
                                result
                                if index == 0
                                else next(
                                    (
                                        item["benchmark_id"]
                                        for item in report
                                        if item.get("configuration") == 1 and item.get("status") == "success"
                                    ),
                                    None,
                                )
                            )
                            store.record_comparison(
                                result, baseline_id, settings.serving_overrides.model_dump(exclude_none=True), current
                            )
                        outcome = {
                            "configuration": index + 1,
                            "attempt": attempt + 1,
                            "job_id": job_id,
                            "benchmark_id": result,
                            "status": "success" if result else "failed",
                            "parameters": settings.serving_overrides.model_dump(exclude_none=True),
                        }
                        report.append(outcome)
                        store.save(pair_id, "running", report, recovery)
                        break
                    except NightlyStopped as exc:
                        report.append({"configuration": index + 1, "attempt": attempt + 1, "status": exc.reason})
                        store.save(pair_id, "running", report, recovery)
                        if exc.reason != "stalled":
                            state = exc.reason
                            raise
                        # Reset the lane before one bounded retry, even with identical settings.
                        await self.restore(pair_id, recovery)
                    except (ValueError, RuntimeError) as exc:
                        report.append({"configuration": index + 1, "status": "failed", "reason": str(exc)[:1000]})
                        store.save(pair_id, "running", report, recovery)
                        break
        except NightlyStopped as exc:
            state = exc.reason
        except asyncio.CancelledError:
            state = "cancelled"
            if asyncio.current_task().cancelling():
                state = "interrupted"
                raise
        except Exception as exc:
            state = "failed"
            report.append({"status": "failed", "reason": str(exc)[:1000]})
        finally:
            if recovery:
                try:
                    if not LEASE_CHECK.get()():
                        raise RuntimeError("Maintenance lock lost; worker recovery remains pending")
                    await self.restore(pair_id, recovery)
                    recovery = None
                    benchmark_reservations.release(-pair_id)
                except Exception as exc:
                    state = "recovery_required"
                    report.append({"status": state, "reason": str(exc)[:1000]})
            store.save(pair_id, state, report, recovery)
        return recovery is None

    async def submit(self, pair_id, settings):
        # Reuse the authenticated admission path and job/result persistence.
        import importlib

        main = importlib.import_module("logos.main")
        from logos.routers.internal import internal_run_model_benchmark

        request = Request(
            {"type": "http", "headers": [(b"authorization", ("Bearer " + main._INTERNAL_SECRET).encode())]}
        )
        token = NIGHTLY_CONTEXT.set(True)
        try:
            response = await internal_run_model_benchmark(
                InternalBenchmarkRequest(model_provider_id=pair_id, **settings.model_dump()), request
            )
            payload = json.loads(response.body)
            if response.status_code != 202:
                raise RuntimeError(payload.get("error", "Benchmark admission failed"))
            job_id = payload["job_id"]
            return job_id, main._benchmark_tasks_by_job[job_id]
        finally:
            NIGHTLY_CONTEXT.reset(token)
