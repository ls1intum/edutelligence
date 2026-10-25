"""Planned maintenance of a worker node: the cordon a node manager asks for before it replaces the node's container.

A node manager (one per GPU host) wants to swap the worker container without cutting the requests that run on it. It
asks the orchestrator for a lease on its node. While the lease is held the node is cordoned: the scheduler sends it no
new work and the capacity planner places nothing on it. The manager then asks whether the node has drained, swaps the
container, and gives the lease back once the new container is verified.

Rules kept here:

* One lease at a time across the cluster, so at most one node is out of service for a planned replacement. A second
  node asks again until the first lease is released.
* A node that runs a calibration session gets no lease: replacing its container would end the calibration.
* A lease that its manager stops renewing expires, so a manager that dies cannot cordon a node for good.
* "Drained" means no request is tracked for the node by the orchestrator (this includes requests that are scheduled
  but have not reached the worker yet) and none runs on the worker, and that this has held for a settle time. The
  settle time covers the lag between the two views.

The leases live in memory. After an orchestrator restart they are gone, so every node is routable again; the manager
asks again and never replaces a container without a fresh answer that the node has drained.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from logos.logosnode_registry import LogosNodeRuntimeRegistry

logger = logging.getLogger(__name__)

# A lease expires this long after the last call of its manager. The manager calls every few seconds while it drains
# and verifies, so the expiry only matters for a manager that is gone.
DEFAULT_LEASE_TTL_S = 1800.0
# How long a node must stay idle before it counts as drained.
DEFAULT_SETTLE_S = 10.0


def _seconds_from_env(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value >= 0 else default


def _count(value: Any) -> int:
    try:
        return max(0, int(float(value or 0)))
    except (TypeError, ValueError):
        return 0


@dataclass
class _Lease:
    provider_id: int
    deployment_id: str
    last_seen: float
    # Since when the node has been idle; None while a request is running on it.
    idle_since: float | None = None


class NodeMaintenance:
    """The leases of the nodes that are being replaced, and the rules around them."""

    def __init__(
        self,
        registry: "LogosNodeRuntimeRegistry",
        *,
        ttl_s: float | None = None,
        settle_s: float | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._registry = registry
        self._ttl_s = DEFAULT_LEASE_TTL_S if ttl_s is None else ttl_s
        self._settle_s = (
            _seconds_from_env("LOGOS_NODE_DRAIN_SETTLE_S", DEFAULT_SETTLE_S) if settle_s is None else settle_s
        )
        self._clock = clock
        self._leases: dict[int, _Lease] = {}
        self._lock = threading.RLock()
        # Number of requests the orchestrator tracks for a node, from scheduling to completion. Set once the
        # scheduling facade exists.
        self.tracked_requests: Callable[[int], int] = lambda _provider_id: 0
        # Called with the provider id after a lease was released, so requests held back for the node are considered
        # again. Set once the scheduler exists.
        self.on_released: Callable[[int], None] | None = None

    # ------------------------------------------------------------------ Reads

    def is_cordoned(self, provider_id: int) -> bool:
        """True while a live lease holds the node. Cheap: the scheduler asks this for every candidate."""
        with self._lock:
            lease = self._leases.get(int(provider_id))
            if lease is None:
                return False
            if self._clock() - lease.last_seen > self._ttl_s:
                self._drop(lease, "expired")
                return False
            return True

    def sole_replica_models(self, provider_id: int) -> list[str]:
        """Models this node serves that no other connected, uncordoned node can serve right now."""
        models = self._capabilities(provider_id)
        for other in self._registry.active_provider_ids():
            if not models:
                break
            if other == provider_id or not self._registry.is_provider_online(other) or self.is_cordoned(other):
                continue
            models -= self._capabilities(other)
        return sorted(models)

    # ------------------------------------------------------------------ Calls of the node manager

    def request(self, provider_id: int, deployment_id: str) -> dict[str, Any]:
        """Take the lease for the node, or renew it. Answers whether the node has drained."""
        provider_id = int(provider_id)
        with self._lock:
            self._expire()
            now = self._clock()
            lease = self._leases.get(provider_id)
            if lease is None:
                refusal = self._refusal(provider_id)
                if refusal is not None:
                    logger.info(
                        "Worker %s is not cordoned for deployment %s: %s",
                        self._name(provider_id),
                        deployment_id,
                        refusal["reason"],
                    )
                    return refusal
                lease = _Lease(provider_id=provider_id, deployment_id=deployment_id, last_seen=now)
                self._leases[provider_id] = lease
                logger.info(
                    "Worker %s is cordoned for deployment %s; sole replica for: %s",
                    self._name(provider_id),
                    deployment_id,
                    ", ".join(self.sole_replica_models(provider_id)) or "no model",
                )
            elif lease.deployment_id != deployment_id:
                logger.warning(
                    "Worker %s: deployment %s takes over the lease of deployment %s",
                    self._name(provider_id),
                    deployment_id,
                    lease.deployment_id,
                )
                lease.deployment_id = deployment_id
                lease.idle_since = None
            lease.last_seen = now
            return {
                "status": "granted",
                "sole_replica_models": self.sole_replica_models(provider_id),
                **self._node(provider_id),
                **self._drain_state(lease),
            }

    def status(self, provider_id: int, deployment_id: str) -> dict[str, Any]:
        """What the orchestrator sees of the node; renews the lease when the deployment holds it."""
        provider_id = int(provider_id)
        with self._lock:
            self._expire()
            lease = self._leases.get(provider_id)
            held = lease is not None and lease.deployment_id == deployment_id
            answer: dict[str, Any] = {"status": "leased" if held else "no_lease", **self._node(provider_id)}
            if held:
                lease.last_seen = self._clock()
                answer.update(self._drain_state(lease))
            return answer

    def release(self, provider_id: int, deployment_id: str) -> dict[str, Any]:
        """Give the lease back. Only the deployment that holds it can; a repeated call is harmless."""
        provider_id = int(provider_id)
        with self._lock:
            lease = self._leases.get(provider_id)
            if lease is None:
                return {"status": "no_lease"}
            if lease.deployment_id != deployment_id:
                return {"status": "held_by_other_deployment"}
            self._drop(lease, "released")
        callback = self.on_released
        if callback is not None:
            try:
                callback(provider_id)
            except (
                Exception
            ):  # noqa: BLE001 - the lease is gone either way; the queue is considered again at the next report
                logger.warning(
                    "Could not re-evaluate the queues after the release for worker %s", provider_id, exc_info=True
                )
        return {"status": "released"}

    # ------------------------------------------------------------------ Internals

    def _expire(self) -> None:
        now = self._clock()
        for lease in list(self._leases.values()):
            if now - lease.last_seen > self._ttl_s:
                self._drop(lease, "expired")

    def _drop(self, lease: _Lease, why: str) -> None:
        self._leases.pop(lease.provider_id, None)
        logger.info(
            "Worker %s is no longer cordoned (%s); deployment %s",
            self._name(lease.provider_id),
            why,
            lease.deployment_id,
        )

    def _refusal(self, provider_id: int) -> dict[str, Any] | None:
        for other in self._leases.values():
            if other.provider_id != provider_id:
                return {
                    "status": "denied",
                    "reason": "another_node_in_maintenance",
                    "holder": self._name(other.provider_id),
                }
        if self._registry.is_calibrating(provider_id):
            return {"status": "denied", "reason": "calibrating"}
        return None

    def _name(self, provider_id: int) -> str:
        snapshot = self._registry.peek_runtime_snapshot(provider_id)
        worker_id = (snapshot or {}).get("worker_id")
        return str(worker_id) if worker_id else f"provider {provider_id}"

    def _capabilities(self, provider_id: int) -> set[str]:
        snapshot = self._registry.peek_runtime_snapshot(provider_id)
        return set((snapshot or {}).get("capabilities_models") or [])

    def _node(self, provider_id: int) -> dict[str, Any]:
        snapshot = self._registry.peek_runtime_snapshot(provider_id)
        return {
            "online": self._registry.is_provider_online(provider_id),
            "session_id": (snapshot or {}).get("session_id"),
            "first_status_received": self._registry.has_received_first_status(provider_id),
        }

    def _worker_in_flight(self, provider_id: int) -> int:
        """Requests running or waiting on the lanes of the worker, as its last status reports them."""
        snapshot = self._registry.peek_runtime_snapshot(provider_id)
        lanes = ((snapshot or {}).get("runtime") or {}).get("lanes") or []
        total = 0
        for lane in lanes:
            if not isinstance(lane, dict):
                continue
            metrics = lane.get("backend_metrics") if isinstance(lane.get("backend_metrics"), dict) else {}
            running = max(_count(lane.get("active_requests")), _count(metrics.get("requests_running")))
            total += running + _count(metrics.get("queue_waiting"))
        return total

    def _drain_state(self, lease: _Lease) -> dict[str, Any]:
        provider_id = lease.provider_id
        tracked = max(0, int(self.tracked_requests(provider_id)))
        worker = self._worker_in_flight(provider_id)
        now = self._clock()
        if not self._registry.is_provider_online(provider_id):
            # Nothing is routed to a node that is gone, and what ran on it is lost already.
            return {"drained": True, "idle_for_s": 0.0, "in_flight": {"orchestrator": tracked, "worker": worker}}
        if tracked > 0 or worker > 0:
            lease.idle_since = None
        elif lease.idle_since is None:
            lease.idle_since = now
        idle_for = 0.0 if lease.idle_since is None else now - lease.idle_since
        return {
            "drained": lease.idle_since is not None and idle_for >= self._settle_s,
            "idle_for_s": round(idle_for, 1),
            "in_flight": {"orchestrator": tracked, "worker": worker},
        }
