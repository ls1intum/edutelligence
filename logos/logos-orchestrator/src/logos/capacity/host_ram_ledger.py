"""Host-RAM reservation ledger.

Parallel to ``vram_ledger.VRAMLedger`` but for host memory. The capacity
planner uses this to gate cold loads against the worker's reported
``host_memory.available_mb``: a cold load that fits in VRAM can still OOM the
host if previously-sleeping lanes have not actually released their weights
(vLLM sleep_l1 keeps weights in host RAM; sleep_l2 keeps the lane process).

Reservations are per-provider. Unlike VRAM there is no per-GPU breakdown —
host RAM is a single pool per worker.

Semantics of operations:
  * ``load``         — cold add of a new lane; reserves the projected awake
                       host-RAM footprint (model profile estimate).
  * ``wake``         — wake from sleep_l2 only. wake from sleep_l1 is free on
                       the host RAM axis because the weights never left.
  * ``reclaim_stop`` — reservation tied to a ``delete_lane`` action; the
                       planner uses a negative ``host_ram_mb`` so the
                       reservation accounts for the upcoming free.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class HostRamReservation:
    """A single host-RAM reservation for an in-flight operation."""

    reservation_id: str
    provider_id: int
    lane_id: str
    operation: str  # "load" | "wake" | "reclaim_stop"
    host_ram_mb: float  # positive = consuming, negative = freeing
    created_at: float


class HostRamLedger:
    """Per-provider host-RAM reservation tracking with atomic reserve/release.

    All public methods are synchronous (no ``await``) so ``try_reserve_atomic``
    cannot be interleaved between availability check and reservation in the
    asyncio event loop.
    """

    def __init__(self) -> None:
        self._reservations: dict[str, HostRamReservation] = {}
        self._provider_committed: dict[int, float] = {}

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def reserve(
        self,
        provider_id: int,
        lane_id: str,
        operation: str,
        host_ram_mb: float,
    ) -> str:
        """Create a host-RAM reservation unconditionally. Returns reservation_id."""
        rid = uuid.uuid4().hex[:12]
        self._reservations[rid] = HostRamReservation(
            reservation_id=rid,
            provider_id=provider_id,
            lane_id=lane_id,
            operation=operation,
            host_ram_mb=host_ram_mb,
            created_at=time.time(),
        )
        self._provider_committed[provider_id] = self._provider_committed.get(provider_id, 0.0) + host_ram_mb
        logger.debug(
            "Host-RAM reserve %s: provider=%d lane=%s op=%s host_ram=%.0fMB " "(total_committed=%.0fMB)",
            rid,
            provider_id,
            lane_id,
            operation,
            host_ram_mb,
            self._provider_committed.get(provider_id, 0.0),
        )
        return rid

    def release(self, reservation_id: str) -> None:
        """Release a reservation, restoring its host RAM to available.

        Does NOT clamp to zero — paired positive+negative reservations must
        cancel out exactly. The totals are clamped only when no reservations
        remain for the provider (floating-point cleanup).
        """
        res = self._reservations.pop(reservation_id, None)
        if res is None:
            return
        committed = self._provider_committed.get(res.provider_id, 0.0)
        self._provider_committed[res.provider_id] = committed - res.host_ram_mb
        if not any(r.provider_id == res.provider_id for r in self._reservations.values()):
            self._provider_committed[res.provider_id] = max(
                0.0,
                self._provider_committed[res.provider_id],
            )
        logger.debug(
            "Host-RAM release %s: provider=%d lane=%s op=%s freed=%.0fMB " "(total_committed=%.0fMB)",
            reservation_id,
            res.provider_id,
            res.lane_id,
            res.operation,
            res.host_ram_mb,
            self._provider_committed.get(res.provider_id, 0.0),
        )

    def try_reserve_atomic(
        self,
        provider_id: int,
        lane_id: str,
        operation: str,
        host_ram_mb: float,
        raw_available_mb: float,
        safety_margin_mb: float = 0.0,
    ) -> str | None:
        """Check-and-reserve in one synchronous step.

        Returns the reservation_id if ``raw_available_mb`` minus existing
        commitments has at least ``host_ram_mb + safety_margin_mb`` room.
        Returns ``None`` if there is insufficient host RAM.

        Unlike VRAM we use an additive safety margin (MB) rather than a
        multiplicative one: host RAM is a single pool that needs a fixed
        absolute buffer (OS file cache, malloc fragmentation, mm processor
        cache) regardless of the model size.
        """
        effective = raw_available_mb - self._provider_committed.get(provider_id, 0.0)
        needed = host_ram_mb + safety_margin_mb
        if effective < needed:
            logger.debug(
                "Host-RAM reserve DENIED: provider=%d lane=%s op=%s "
                "need=%.0fMB effective_avail=%.0fMB "
                "(raw=%.0fMB committed=%.0fMB margin=%.0fMB)",
                provider_id,
                lane_id,
                operation,
                needed,
                effective,
                raw_available_mb,
                self._provider_committed.get(provider_id, 0.0),
                safety_margin_mb,
            )
            return None
        return self.reserve(provider_id, lane_id, operation, host_ram_mb)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_committed_mb(self, provider_id: int) -> float:
        """Total host RAM committed by in-flight operations on this provider."""
        return self._provider_committed.get(provider_id, 0.0)

    def get_effective_available_mb(
        self,
        provider_id: int,
        raw_available_mb: float,
    ) -> float:
        """Available host RAM after subtracting in-flight reservations."""
        return raw_available_mb - self._provider_committed.get(provider_id, 0.0)

    def has_active_reservation(
        self,
        provider_id: int,
        lane_id: str,
        operation: str | None = None,
    ) -> bool:
        for res in self._reservations.values():
            if res.provider_id == provider_id and res.lane_id == lane_id:
                if operation is None or res.operation == operation:
                    return True
        return False

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def cleanup_stale(self, max_age_seconds: float = 600.0) -> int:
        """Remove reservations older than *max_age_seconds*. Safety net."""
        now = time.time()
        stale_ids = [rid for rid, res in self._reservations.items() if (now - res.created_at) > max_age_seconds]
        for rid in stale_ids:
            res = self._reservations[rid]
            logger.warning(
                "Cleaning stale host-RAM reservation %s: provider=%d lane=%s " "op=%s host_ram=%.0fMB age=%.0fs",
                rid,
                res.provider_id,
                res.lane_id,
                res.operation,
                res.host_ram_mb,
                now - res.created_at,
            )
            self.release(rid)
        return len(stale_ids)

    def __repr__(self) -> str:
        return f"HostRamLedger(reservations={len(self._reservations)}, " f"committed={dict(self._provider_committed)})"
