"""
Scheduling Data Facade for `logos_peer` providers.

A `logos_peer` provider is another Logos server that this Logos uses as an
upstream — its OpenAI-compatible `/v1/*` surface is treated like any cloud
provider, but with active capacity polling against `/v1/peer/status` so the
local scheduler can avoid routing to a peer that is overloaded or offline.

A circuit breaker (3 failed polls → unhealthy, 2 successes → healthy again)
prevents the local instance from forwarding to a peer that has dropped out.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from .models import ModelStatus


logger = logging.getLogger(__name__)


_DEFAULT_REFRESH_INTERVAL = 5.0
_DEFAULT_POLL_TIMEOUT = 2.0
_UNHEALTHY_FAILURE_THRESHOLD = 3
_HEALTHY_SUCCESS_THRESHOLD = 2


@dataclass
class PeerCapacity:
    """Capacity / health snapshot for a `logos_peer` upstream."""

    provider_id: int
    is_healthy: bool
    has_capacity: bool
    queue_depth: int
    free_slots: Optional[int]
    last_poll_at: Optional[datetime]
    last_error: Optional[str]

    def to_dict(self) -> dict:
        return {
            "provider_id": self.provider_id,
            "is_healthy": self.is_healthy,
            "has_capacity": self.has_capacity,
            "queue_depth": self.queue_depth,
            "free_slots": self.free_slots,
            "last_poll_at": self.last_poll_at.isoformat() if self.last_poll_at else None,
            "last_error": self.last_error,
        }


@dataclass
class _ModelSnapshot:
    available: bool
    queue_depth: int
    loaded: bool


@dataclass
class _PeerState:
    provider_id: int
    provider_name: str
    base_url: str
    api_key: str
    refresh_interval: float
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    is_healthy: bool = False  # start unhealthy until a successful poll
    last_poll_at: Optional[datetime] = None
    last_error: Optional[str] = None
    queue_depth: int = 0
    free_slots: Optional[int] = None
    models: Dict[int, str] = field(default_factory=dict)  # model_id -> model_name
    snapshots: Dict[str, _ModelSnapshot] = field(default_factory=dict)
    stop_event: threading.Event = field(default_factory=threading.Event)
    thread: Optional[threading.Thread] = None


class LogosPeerSchedulingDataFacade:
    """
    Tracks health and capacity of `logos_peer` upstream Logos servers.

    Lifecycle:

        facade = LogosPeerSchedulingDataFacade()
        facade.register_model(model_id=12, provider_name='test-peer',
                              base_url='https://test.logos.example',
                              api_key='lg-...', model_name='gpt-4o',
                              provider_id=42)
        facade.start_polling()                 # starts one daemon thread per peer
        ...
        cap = facade.get_model_capacity(12, 42)
        if cap and cap.has_capacity:
            ...
        facade.stop()                          # signals threads to exit

    The `poll_once(provider_id)` method is provided for unit tests so the polling
    behaviour can be exercised without spawning threads.
    """

    def __init__(
        self,
        *,
        http_client_factory: Optional[Any] = None,
        poll_timeout_seconds: float = _DEFAULT_POLL_TIMEOUT,
        unhealthy_failure_threshold: int = _UNHEALTHY_FAILURE_THRESHOLD,
        healthy_success_threshold: int = _HEALTHY_SUCCESS_THRESHOLD,
    ) -> None:
        self._peers: Dict[int, _PeerState] = {}
        self._lock = threading.RLock()
        self._poll_timeout = poll_timeout_seconds
        self._unhealthy_threshold = unhealthy_failure_threshold
        self._healthy_threshold = healthy_success_threshold
        self._polling_started = False
        # Allow tests to inject a fake httpx.Client.
        self._http_client_factory = http_client_factory or (
            lambda: httpx.Client(timeout=self._poll_timeout)
        )
        logger.info("LogosPeerSchedulingDataFacade initialized")

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_model(
        self,
        model_id: int,
        provider_name: str,
        base_url: str,
        api_key: str,
        model_name: str,
        provider_id: int,
        refresh_interval: float = _DEFAULT_REFRESH_INTERVAL,
    ) -> None:
        if not base_url:
            raise ValueError(
                f"base_url is required for logos_peer model {model_id} ({provider_name})"
            )
        with self._lock:
            peer = self._peers.get(int(provider_id))
            if peer is None:
                peer = _PeerState(
                    provider_id=int(provider_id),
                    provider_name=provider_name,
                    base_url=base_url.rstrip("/"),
                    api_key=api_key or "",
                    refresh_interval=float(refresh_interval),
                )
                self._peers[int(provider_id)] = peer
            else:
                peer.provider_name = provider_name
                peer.base_url = base_url.rstrip("/")
                peer.api_key = api_key or ""
                peer.refresh_interval = float(refresh_interval)
            peer.models[int(model_id)] = model_name
            logger.info(
                "Registered model %s as '%s' with logos_peer '%s' (provider_id=%s)",
                model_id, model_name, provider_name, provider_id,
            )

    def replace_registrations(self, registrations: List[dict]) -> None:
        """Reconcile the set of registered peers and models with `registrations`."""
        desired: Dict[int, Dict[str, Any]] = {}
        for entry in registrations:
            pid = int(entry["provider_id"])
            slot = desired.setdefault(
                pid,
                {
                    "provider_name": entry["provider_name"],
                    "base_url": (entry.get("base_url") or "").rstrip("/"),
                    "api_key": entry.get("api_key") or "",
                    "refresh_interval": float(
                        entry.get("refresh_interval") or _DEFAULT_REFRESH_INTERVAL
                    ),
                    "models": {},
                },
            )
            slot["models"][int(entry["model_id"])] = entry["model_name"]

        with self._lock:
            stale_ids = set(self._peers) - set(desired)
            for pid in stale_ids:
                self._stop_peer_locked(pid)
                self._peers.pop(pid, None)

            for pid, slot in desired.items():
                peer = self._peers.get(pid)
                if peer is None:
                    peer = _PeerState(
                        provider_id=pid,
                        provider_name=slot["provider_name"],
                        base_url=slot["base_url"],
                        api_key=slot["api_key"],
                        refresh_interval=slot["refresh_interval"],
                    )
                    self._peers[pid] = peer
                else:
                    peer.provider_name = slot["provider_name"]
                    peer.base_url = slot["base_url"]
                    peer.api_key = slot["api_key"]
                    peer.refresh_interval = slot["refresh_interval"]
                peer.models = dict(slot["models"])
                if self._polling_started and peer.thread is None:
                    self._start_peer_thread_locked(peer)

    # ------------------------------------------------------------------
    # Polling lifecycle
    # ------------------------------------------------------------------

    def start_polling(self) -> None:
        """Start a daemon polling thread for each registered peer."""
        with self._lock:
            self._polling_started = True
            for peer in self._peers.values():
                if peer.thread is None:
                    self._start_peer_thread_locked(peer)

    def stop(self) -> None:
        """Signal all polling threads to exit. Returns once events are set."""
        with self._lock:
            for pid in list(self._peers):
                self._stop_peer_locked(pid)
            self._polling_started = False

    def _start_peer_thread_locked(self, peer: _PeerState) -> None:
        peer.stop_event = threading.Event()
        thread = threading.Thread(
            target=self._poll_loop,
            args=(peer.provider_id,),
            name=f"logos-peer-poll-{peer.provider_id}",
            daemon=True,
        )
        peer.thread = thread
        thread.start()

    def _stop_peer_locked(self, provider_id: int) -> None:
        peer = self._peers.get(provider_id)
        if peer is None:
            return
        peer.stop_event.set()
        peer.thread = None

    def _poll_loop(self, provider_id: int) -> None:
        while True:
            with self._lock:
                peer = self._peers.get(provider_id)
                if peer is None:
                    return
                stop_event = peer.stop_event
                interval = peer.refresh_interval
            if stop_event.is_set():
                return
            try:
                self.poll_once(provider_id)
            except Exception:  # noqa: BLE001
                logger.exception("Unhandled error in logos_peer poll loop pid=%s", provider_id)
            if stop_event.wait(interval):
                return

    def poll_once(self, provider_id: int) -> None:
        """
        Perform a single status poll. Visible for tests and one-shot health checks.

        Updates `is_healthy`, `consecutive_*`, `last_*`, `queue_depth`, `free_slots`,
        and per-model snapshots. Never raises.
        """
        with self._lock:
            peer = self._peers.get(int(provider_id))
            if peer is None:
                return
            base_url = peer.base_url
            api_key = peer.api_key

        url = f"{base_url}/v1/peer/status"
        headers = {"Accept": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        body: Optional[Dict[str, Any]] = None
        error: Optional[str] = None
        try:
            client = self._http_client_factory()
            try:
                response = client.get(url, headers=headers)
            finally:
                close = getattr(client, "close", None)
                if callable(close):
                    close()
            if response.status_code >= 400:
                error = f"HTTP {response.status_code}"
            else:
                body = response.json()
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"

        now = datetime.now(timezone.utc)
        with self._lock:
            peer = self._peers.get(int(provider_id))
            if peer is None:
                return
            peer.last_poll_at = now
            if error is not None or not isinstance(body, dict):
                peer.last_error = error or "non-dict response body"
                peer.consecutive_successes = 0
                peer.consecutive_failures += 1
                if (
                    peer.is_healthy
                    and peer.consecutive_failures >= self._unhealthy_threshold
                ):
                    peer.is_healthy = False
                    logger.warning(
                        "logos_peer '%s' (id=%s) marked UNHEALTHY after %s failures: %s",
                        peer.provider_name,
                        peer.provider_id,
                        peer.consecutive_failures,
                        peer.last_error,
                    )
                return

            peer.last_error = None
            peer.consecutive_failures = 0
            peer.consecutive_successes += 1
            capacity_info = body.get("capacity") if isinstance(body, dict) else None
            if isinstance(capacity_info, dict):
                free_slots = capacity_info.get("free_slots")
                peer.free_slots = (
                    int(free_slots) if isinstance(free_slots, (int, float)) else None
                )
            else:
                peer.free_slots = None

            new_snapshots: Dict[str, _ModelSnapshot] = {}
            total_queue = 0
            for entry in body.get("models", []) or []:
                if not isinstance(entry, dict):
                    continue
                name = str(entry.get("id") or "").strip()
                if not name:
                    continue
                qd = int(entry.get("queue_depth") or 0)
                total_queue += qd
                new_snapshots[name] = _ModelSnapshot(
                    available=bool(entry.get("available", True)),
                    queue_depth=qd,
                    loaded=bool(entry.get("loaded", True)),
                )
            peer.snapshots = new_snapshots
            peer.queue_depth = total_queue

            if not peer.is_healthy and (
                peer.consecutive_successes >= self._healthy_threshold
            ):
                peer.is_healthy = True
                logger.info(
                    "logos_peer '%s' (id=%s) marked HEALTHY after %s successes",
                    peer.provider_name,
                    peer.provider_id,
                    peer.consecutive_successes,
                )

    # ------------------------------------------------------------------
    # Read APIs (used by the scheduler)
    # ------------------------------------------------------------------

    def get_model_status(self, model_id: int, provider_id: int) -> ModelStatus:
        with self._lock:
            peer = self._require_peer(provider_id)
            self._require_model(peer, model_id)
            model_name = peer.models[int(model_id)]
            snap = peer.snapshots.get(model_name)
            is_loaded = bool(peer.is_healthy and snap and snap.loaded and snap.available)
        return ModelStatus(
            model_id=int(model_id),
            provider_id=int(provider_id),
            is_loaded=is_loaded,
            vram_mb=0,
            expires_at=None,
            queue_state=None,
            active_requests=int(snap.queue_depth) if snap else 0,
            provider_type="logos_peer",
        )

    def get_model_capacity(
        self, model_id: int, provider_id: int
    ) -> Optional[PeerCapacity]:
        with self._lock:
            peer = self._peers.get(int(provider_id))
            if peer is None:
                return None
            if int(model_id) not in peer.models:
                return None
            model_name = peer.models[int(model_id)]
            snap = peer.snapshots.get(model_name)
            available = bool(peer.is_healthy and snap and snap.available)
            free_slots = peer.free_slots
            has_capacity = available and (free_slots is None or free_slots > 0)
            return PeerCapacity(
                provider_id=int(provider_id),
                is_healthy=peer.is_healthy,
                has_capacity=has_capacity,
                queue_depth=int(snap.queue_depth) if snap else peer.queue_depth,
                free_slots=free_slots,
                last_poll_at=peer.last_poll_at,
                last_error=peer.last_error,
            )

    def get_capacity_info(self, provider_id: int) -> PeerCapacity:
        with self._lock:
            peer = self._require_peer(provider_id)
            free_slots = peer.free_slots
            has_capacity = peer.is_healthy and (free_slots is None or free_slots > 0)
            return PeerCapacity(
                provider_id=int(provider_id),
                is_healthy=peer.is_healthy,
                has_capacity=has_capacity,
                queue_depth=peer.queue_depth,
                free_slots=free_slots,
                last_poll_at=peer.last_poll_at,
                last_error=peer.last_error,
            )

    def list_provider_ids(self) -> List[int]:
        with self._lock:
            return list(self._peers)

    def is_healthy(self, provider_id: int) -> bool:
        with self._lock:
            peer = self._peers.get(int(provider_id))
            return bool(peer and peer.is_healthy)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _require_peer(self, provider_id: int) -> _PeerState:
        peer = self._peers.get(int(provider_id))
        if peer is None:
            raise KeyError(f"logos_peer provider {provider_id} not registered")
        return peer

    @staticmethod
    def _require_model(peer: _PeerState, model_id: int) -> None:
        if int(model_id) not in peer.models:
            raise ValueError(
                f"Model {model_id} not registered with logos_peer provider {peer.provider_id}"
            )
