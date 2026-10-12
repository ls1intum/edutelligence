"""Application-owned nightly runs, one reserved worker across the cluster."""

import asyncio
import copy
import json
import logging

from starlette.requests import Request

from logos.benchmarks import nightly_store as store
from logos.benchmarks.guidellm_runner import extract_serving_configuration
from logos.benchmarks.nightly import LEASE_CHECK, NIGHTLY_CONTEXT, NightlyStopped, can_start, local_now, parameter_plan
from logos.benchmarks.reservations import benchmark_reservations
from logos.benchmarks.worker_limits import validate_worker_overrides, worker_limits
from logos.dbutils.dbmanager import DBManager
from logos.dbutils.dbrequest import InternalBenchmarkRequest

logger = logging.getLogger(__name__)


class NightlyScheduler:
    def __init__(self, registry, planner):
        self.registry = registry
        self.planner = planner
        self.task = None

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
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Nightly benchmark tick failed")
            await asyncio.sleep(15)

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
            for row in schedules:
                pair_id = row["model_provider_id"]
                if row["recovery"]:
                    if store.has_active_benchmarks():
                        return
                    try:
                        await self.restore(pair_id, row["recovery"])
                        store.save(pair_id, "interrupted_recovered", row["report"], None)
                        benchmark_reservations.release(-pair_id)
                    except Exception:
                        # Keep the node excluded and do not take a second node.
                        logger.exception("Nightly worker recovery requires attention")
                        return
                if not can_start(local_now()) or store.has_active_benchmarks():
                    return
                if not row["enabled"] or not store.claim(pair_id, local_now().date()):
                    continue
                # Detect a lost session lock before touching a worker.
                if not store.lock_held(connection):
                    return
                if not await self.run_schedule(pair_id, connection):
                    return

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
        if not await self.planner.prepare_benchmark_lane(provider_id, recovery["model"], timeout_seconds=900):
            raise RuntimeError("Restored production model is not ready")

    async def run_schedule(self, pair_id, connection):
        report = []
        recovery = None
        state = "completed"
        try:
            with DBManager() as db:
                target = db.get_model_provider_benchmark_target(pair_id)
            if not target:
                store.disable_missing_target(pair_id)
                raise RuntimeError("The scheduled model/worker deployment no longer exists")
            if target["provider_type"] != "logosnode":
                raise RuntimeError("Nightly benchmarks require a Logos worker")
            pid, model = int(target["provider_id"]), str(target["model_name"])
            if not self.healthy(pid) or not any(
                other != pid and self.healthy(other) for other in self.registry.active_provider_ids()
            ):
                raise RuntimeError("Need the selected worker and another healthy worker for production")
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
            benchmark_reservations.reserve(pid, "*", -pair_id)
            async with asyncio.timeout(900):
                for item in lanes:
                    while self.planner._facade.model_inflight_requests(pid, item["model"]) > 0:
                        await asyncio.sleep(1)
                    if not await self.planner._drain_lane(pid, item["lane_id"], 900):
                        raise RuntimeError("Could not drain the worker's existing traffic")
            for index, settings in enumerate(plan):
                for attempt in range(2):
                    if not can_start(local_now()) or not store.status(pair_id)["enabled"]:
                        state = "window_closed" if store.status(pair_id)["enabled"] else "disabled"
                        raise NightlyStopped(state)
                    if not self.healthy(pid):
                        raise RuntimeError("Worker is no longer healthy")
                    if not store.lock_held(connection):
                        raise NightlyStopped("lease_lost")
                    try:
                        validate_worker_overrides(settings.serving_overrides, worker_limits(snapshot, model))
                        recovery["mutated"] = True
                        store.save(pair_id, "running", report, recovery)
                        lease_token = LEASE_CHECK.set(lambda: store.lock_held(connection))
                        try:
                            job_id, task = await self.submit(pair_id, settings)
                        finally:
                            LEASE_CHECK.reset(lease_token)
                        result = await task
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
                    if not store.lock_held(connection):
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
        import logos.main as main
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
