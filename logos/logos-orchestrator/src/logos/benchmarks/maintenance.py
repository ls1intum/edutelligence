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
UNCONFIRMED_CLAIM_GRACE = timedelta(minutes=5)


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
                    if await self._release_if_finished(claim):
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


def _past_grace(claim):
    created_at = claim.get("created_at")
    return created_at is not None and datetime.now(UTC) - created_at >= UNCONFIRMED_CLAIM_GRACE
