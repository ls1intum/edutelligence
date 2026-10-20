"""Cluster-wide admission and confirmed completion of worker calibration."""

import uuid
from contextvars import ContextVar

from logos.benchmarks import nightly_store as store

AUTOMATIC_CALIBRATION = ContextVar("automatic_calibration", default=False)


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
            if (
                store.calibration_claim()
                or store.has_active_benchmarks()
                or store.has_recovery()
                or self.live_calibration()
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
            except LogosNodeCommandRejectedError:
                # A refusal settles the start command. It may mean that another
                # session is live, so only a fresh idle reply releases the claim.
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
            claim = store.calibration_claim()
            if claim and claim["provider_id"] == provider_id:
                await self._release_if_finished(claim)
            return result

    async def reconcile(self):
        # Acknowledged starts can finish between status pushes. Query the
        # worker directly; stale status and terminal events never release a claim.
        with store.cluster_lock() as connection:
            if connection is None:
                return
            claim = store.calibration_claim()
            if claim and claim["confirmed"]:
                if await self._release_if_finished(claim):
                    return claim["provider_id"]

    async def _release_if_finished(self, claim):
        result = await self.registry.send_command(
            claim["provider_id"], "get_calibration_status", {}, timeout_seconds=20
        )
        if result.get("calibrating") is False:
            store.release_calibration(claim["token"])
            return True

    async def run_benchmark(self, job_id, execute):
        try:
            return await execute()
        finally:
            # Run only after GuideLLM and its cancellation cleanup have ended.
            store.release_benchmark(job_id)
