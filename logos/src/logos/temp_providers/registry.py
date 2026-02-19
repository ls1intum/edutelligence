"""
Thread-safe in-memory registry for temporary LLM providers.

NOT persisted to the database — all data lives only in process memory.
"""

import logging
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from logos.temp_providers.discovery import DiscoveredModel

logger = logging.getLogger(__name__)


def _generate_provider_id() -> str:
    """Generate a short, unique provider identifier."""
    return f"tmp-{secrets.token_hex(6)}"


def _generate_auth_token() -> str:
    """Generate a unique auth token for a temp provider."""
    return f"tpk-{secrets.token_urlsafe(32)}"


@dataclass
class TempProvider:
    """Represents a temporarily registered LLM provider."""

    id: str
    url: str
    name: str
    owner_process_id: int
    auth_key: Optional[str] = None  # credential FOR the upstream provider
    auth_token: str = ""  # token that clients must present to USE this provider via Logos
    models: List[DiscoveredModel] = field(default_factory=list)
    registered_at: float = field(default_factory=time.time)
    last_health_check: float = field(default_factory=time.time)
    is_healthy: bool = True
    unhealthy_since: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "url": self.url,
            "name": self.name,
            "owner_process_id": self.owner_process_id,
            "models": [{"id": m.id, "owned_by": m.owned_by} for m in self.models],
            "registered_at": self.registered_at,
            "last_health_check": self.last_health_check,
            "is_healthy": self.is_healthy,
            "auth_token": self.auth_token,
        }


class TempProviderRegistry:
    """
    Singleton, thread-safe, in-memory registry of temporary providers.

    All mutations are protected by an ``RLock``.
    """

    _instance: Optional["TempProviderRegistry"] = None
    _lock_cls = threading.RLock  # overridable for testing

    def __init__(self) -> None:
        # Only initialise state once (singleton guard).
        if not hasattr(self, "_providers"):
            self._providers: Dict[str, TempProvider] = {}
            self._lock = self._lock_cls()

    def __new__(cls) -> "TempProviderRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register(
        self,
        url: str,
        name: str,
        owner_process_id: int,
        models: List[DiscoveredModel],
        auth_key: Optional[str] = None,
    ) -> TempProvider:
        """Register a new temp provider and return it (with auth_token set)."""
        provider = TempProvider(
            id=_generate_provider_id(),
            url=url.rstrip("/"),
            name=name,
            owner_process_id=owner_process_id,
            auth_key=auth_key,
            auth_token=_generate_auth_token(),
            models=models,
        )
        with self._lock:
            self._providers[provider.id] = provider
        logger.info(
            "Registered temp provider %s (%s) with %d model(s)",
            provider.id,
            provider.name,
            len(models),
        )
        return provider

    def unregister(self, provider_id: str) -> bool:
        """Remove a temp provider. Returns ``True`` if it existed."""
        with self._lock:
            removed = self._providers.pop(provider_id, None)
        if removed:
            logger.info("Unregistered temp provider %s (%s)", provider_id, removed.name)
        return removed is not None

    def get(self, provider_id: str) -> Optional[TempProvider]:
        with self._lock:
            return self._providers.get(provider_id)

    def list_all(self) -> List[TempProvider]:
        with self._lock:
            return list(self._providers.values())

    def list_for_process(self, process_id: int) -> List[TempProvider]:
        with self._lock:
            return [p for p in self._providers.values() if p.owner_process_id == process_id]

    def list_healthy(self) -> List[TempProvider]:
        with self._lock:
            return [p for p in self._providers.values() if p.is_healthy]

    def update_models(self, provider_id: str, models: List[DiscoveredModel]) -> bool:
        """Replace the model list for a provider. Returns ``True`` if provider exists."""
        with self._lock:
            prov = self._providers.get(provider_id)
            if prov is None:
                return False
            prov.models = models
        return True

    def mark_healthy(self, provider_id: str) -> None:
        with self._lock:
            prov = self._providers.get(provider_id)
            if prov:
                prov.is_healthy = True
                prov.unhealthy_since = None
                prov.last_health_check = time.time()

    def mark_unhealthy(self, provider_id: str) -> None:
        with self._lock:
            prov = self._providers.get(provider_id)
            if prov:
                if prov.is_healthy:
                    prov.unhealthy_since = time.time()
                prov.is_healthy = False
                prov.last_health_check = time.time()

    def remove_stale(self, max_unhealthy_seconds: float = 300) -> List[str]:
        """Remove providers unhealthy for longer than *max_unhealthy_seconds*."""
        now = time.time()
        removed: List[str] = []
        with self._lock:
            to_remove = [
                pid
                for pid, prov in self._providers.items()
                if not prov.is_healthy
                and prov.unhealthy_since is not None
                and (now - prov.unhealthy_since) > max_unhealthy_seconds
            ]
            for pid in to_remove:
                del self._providers[pid]
                removed.append(pid)
        if removed:
            logger.info("Auto-removed stale temp providers: %s", removed)
        return removed

    def find_provider_for_model(self, model_name: str, auth_token: Optional[str] = None) -> Optional[TempProvider]:
        """
        Find a healthy temp provider that serves *model_name*.

        If *auth_token* is given, only providers whose ``auth_token`` matches are considered.
        """
        with self._lock:
            for prov in self._providers.values():
                if not prov.is_healthy:
                    continue
                if auth_token and prov.auth_token != auth_token:
                    continue
                for m in prov.models:
                    if m.id == model_name:
                        return prov
        return None

    def clear(self) -> None:
        """Remove all providers (useful for testing)."""
        with self._lock:
            self._providers.clear()

    @classmethod
    def reset_singleton(cls) -> None:
        """Destroy the singleton instance (for tests only)."""
        cls._instance = None
