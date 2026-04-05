"""VRAM reservation ledger for atomic check-and-reserve semantics.

Every GPU memory-consuming operation (load, wake) must reserve VRAM through
the ledger before executing.  The ledger's `try_reserve_atomic` performs the
availability check and reservation in a single synchronous call with no
``await``, making it immune to check-then-act races in asyncio.

Reservations track which GPU devices they target, so per-GPU feasibility
checks account for in-flight operations on the same physical GPUs.

Reservations are released when the operation completes (success or failure).
A stale-reservation cleanup runs periodically as a safety net.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


def _parse_gpu_devices(gpu_devices: str | None) -> frozenset[int]:
    """Parse a comma-separated GPU device string into a set of device indices."""
    if not gpu_devices:
        return frozenset()
    result: set[int] = set()
    for part in gpu_devices.split(","):
        part = part.strip()
        if part.isdigit():
            result.add(int(part))
    return frozenset(result)


@dataclass
class VRAMReservation:
    """A single VRAM reservation for an in-flight operation."""

    reservation_id: str
    provider_id: int
    lane_id: str
    operation: str  # "load" | "wake" | "reclaim_sleep" | "reclaim_stop"
    vram_mb: float  # positive = consuming, negative = freeing
    created_at: float
    gpu_devices: frozenset[int] = field(default_factory=frozenset)


class VRAMLedger:
    """Per-provider and per-GPU VRAM reservation tracking with atomic reserve/release.

    All public methods are synchronous (no ``await``).  In a cooperative
    asyncio event loop this guarantees that ``try_reserve_atomic`` cannot
    be interleaved between the availability check and the mutation.

    Reservations optionally specify which GPU devices they target.  This
    enables per-GPU feasibility checks: a load targeting GPU 0 only sees
    reservations on GPU 0, not reservations on GPU 1.
    """

    def __init__(self) -> None:
        self._reservations: dict[str, VRAMReservation] = {}
        # Fast per-provider totals so we don't re-sum on every call
        self._provider_committed: dict[int, float] = {}
        # Fast per-(provider, gpu_device) totals for per-GPU checks
        self._gpu_committed: dict[tuple[int, int], float] = {}

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def reserve(
        self,
        provider_id: int,
        lane_id: str,
        operation: str,
        vram_mb: float,
        gpu_devices: str | None = None,
    ) -> str:
        """Create a VRAM reservation unconditionally.  Returns reservation_id.

        *gpu_devices* is an optional comma-separated string like ``"0"`` or
        ``"0,1"``.  When provided, per-GPU committed totals are updated so
        that ``get_gpu_committed_mb`` returns accurate values.
        """
        rid = uuid.uuid4().hex[:12]
        parsed_gpus = _parse_gpu_devices(gpu_devices)
        self._reservations[rid] = VRAMReservation(
            reservation_id=rid,
            provider_id=provider_id,
            lane_id=lane_id,
            operation=operation,
            vram_mb=vram_mb,
            created_at=time.time(),
            gpu_devices=parsed_gpus,
        )
        self._provider_committed[provider_id] = (
            self._provider_committed.get(provider_id, 0.0) + vram_mb
        )
        # Distribute VRAM evenly across targeted GPUs
        if parsed_gpus:
            per_gpu = vram_mb / len(parsed_gpus)
            for dev in parsed_gpus:
                key = (provider_id, dev)
                self._gpu_committed[key] = self._gpu_committed.get(key, 0.0) + per_gpu
        logger.debug(
            "VRAM reserve %s: provider=%d lane=%s op=%s vram=%.0fMB gpus=%s "
            "(total_committed=%.0fMB)",
            rid, provider_id, lane_id, operation, vram_mb,
            gpu_devices or "all",
            self._provider_committed.get(provider_id, 0.0),
        )
        return rid

    def release(self, reservation_id: str) -> None:
        """Release a reservation, restoring its VRAM to available."""
        res = self._reservations.pop(reservation_id, None)
        if res is None:
            return
        committed = self._provider_committed.get(res.provider_id, 0.0)
        self._provider_committed[res.provider_id] = max(0.0, committed - res.vram_mb)
        # Release per-GPU committed
        if res.gpu_devices:
            per_gpu = res.vram_mb / len(res.gpu_devices)
            for dev in res.gpu_devices:
                key = (res.provider_id, dev)
                old = self._gpu_committed.get(key, 0.0)
                self._gpu_committed[key] = max(0.0, old - per_gpu)
        logger.debug(
            "VRAM release %s: provider=%d lane=%s op=%s freed=%.0fMB "
            "(total_committed=%.0fMB)",
            reservation_id, res.provider_id, res.lane_id, res.operation,
            res.vram_mb,
            self._provider_committed.get(res.provider_id, 0.0),
        )

    def try_reserve_atomic(
        self,
        provider_id: int,
        lane_id: str,
        operation: str,
        vram_mb: float,
        raw_available_mb: float,
        safety_margin: float = 1.1,
        gpu_devices: str | None = None,
        per_gpu_free: dict[int, float] | None = None,
    ) -> str | None:
        """Check-and-reserve in one synchronous step.

        Returns the reservation_id if ``raw_available_mb`` minus existing
        commitments has enough room for ``vram_mb * safety_margin``.
        Returns ``None`` if there is insufficient VRAM.

        When *gpu_devices* and *per_gpu_free* are provided, also checks
        per-GPU feasibility: each targeted GPU must have enough free VRAM
        after subtracting existing per-GPU commitments.

        Because this method contains no ``await``, it cannot be preempted
        by another coroutine in the same asyncio loop.
        """
        # Provider-level check
        effective = raw_available_mb - self._provider_committed.get(provider_id, 0.0)
        needed = vram_mb * safety_margin
        if effective < needed:
            logger.debug(
                "VRAM reserve DENIED (provider): provider=%d lane=%s op=%s "
                "need=%.0fMB effective_avail=%.0fMB "
                "(raw=%.0fMB committed=%.0fMB)",
                provider_id, lane_id, operation, needed, effective,
                raw_available_mb, self._provider_committed.get(provider_id, 0.0),
            )
            return None

        # Per-GPU check when device placement is known
        parsed_gpus = _parse_gpu_devices(gpu_devices)
        if parsed_gpus and per_gpu_free is not None:
            per_gpu_needed = (vram_mb / len(parsed_gpus)) * safety_margin
            for dev in parsed_gpus:
                gpu_avail = per_gpu_free.get(dev, 0.0)
                gpu_committed = self._gpu_committed.get((provider_id, dev), 0.0)
                gpu_effective = gpu_avail - gpu_committed
                if gpu_effective < per_gpu_needed:
                    logger.debug(
                        "VRAM reserve DENIED (GPU %d): provider=%d lane=%s op=%s "
                        "need=%.0fMB/GPU effective=%.0fMB "
                        "(raw=%.0fMB committed=%.0fMB)",
                        dev, provider_id, lane_id, operation,
                        per_gpu_needed, gpu_effective,
                        gpu_avail, gpu_committed,
                    )
                    return None

        return self.reserve(provider_id, lane_id, operation, vram_mb, gpu_devices)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_committed_mb(self, provider_id: int) -> float:
        """Total VRAM committed by in-flight operations on this provider."""
        return self._provider_committed.get(provider_id, 0.0)

    def get_gpu_committed_mb(self, provider_id: int, device_id: int) -> float:
        """VRAM committed by in-flight operations on a specific GPU."""
        return self._gpu_committed.get((provider_id, device_id), 0.0)

    def get_effective_available_mb(
        self, provider_id: int, raw_available_mb: float,
    ) -> float:
        """Available VRAM after subtracting in-flight reservations."""
        return raw_available_mb - self._provider_committed.get(provider_id, 0.0)

    def get_gpu_effective_available_mb(
        self, provider_id: int, device_id: int, raw_gpu_free_mb: float,
    ) -> float:
        """Available VRAM on a specific GPU after subtracting reservations."""
        return raw_gpu_free_mb - self._gpu_committed.get(
            (provider_id, device_id), 0.0,
        )

    def has_active_reservation(
        self, provider_id: int, lane_id: str, operation: str | None = None,
    ) -> bool:
        """Check if any active reservation exists for this lane."""
        for res in self._reservations.values():
            if res.provider_id == provider_id and res.lane_id == lane_id:
                if operation is None or res.operation == operation:
                    return True
        return False

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def cleanup_stale(self, max_age_seconds: float = 600.0) -> int:
        """Remove reservations older than *max_age_seconds*.

        Returns the count of removed reservations.  This is a safety net —
        normal operation should always release reservations explicitly.
        """
        now = time.time()
        stale_ids = [
            rid for rid, res in self._reservations.items()
            if (now - res.created_at) > max_age_seconds
        ]
        for rid in stale_ids:
            res = self._reservations[rid]
            logger.warning(
                "Cleaning stale VRAM reservation %s: provider=%d lane=%s op=%s "
                "vram=%.0fMB gpus=%s age=%.0fs",
                rid, res.provider_id, res.lane_id, res.operation, res.vram_mb,
                ",".join(str(d) for d in sorted(res.gpu_devices)) or "all",
                now - res.created_at,
            )
            self.release(rid)
        return len(stale_ids)

    def __repr__(self) -> str:
        return (
            f"VRAMLedger(reservations={len(self._reservations)}, "
            f"committed={dict(self._provider_committed)}, "
            f"gpu_committed={dict(self._gpu_committed)})"
        )
