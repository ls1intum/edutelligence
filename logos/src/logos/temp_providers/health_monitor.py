"""
Background health monitor for temporary providers.

Periodically pings each registered temp provider and marks it
healthy / unhealthy.  Providers that stay unhealthy for longer than
``auto_remove_after_s`` seconds are automatically removed.
"""

import asyncio
import logging
from typing import Optional

import httpx

from logos.temp_providers.registry import TempProviderRegistry

logger = logging.getLogger(__name__)

# Timeout for health-check HTTP requests.
_HEALTH_TIMEOUT = httpx.Timeout(connect=5.0, read=5.0, write=5.0, pool=5.0)


async def _check_provider_health(url: str, auth_key: Optional[str] = None) -> bool:
    """
    Return ``True`` if the provider is reachable.

    Tries ``GET /v1/models`` first (OpenAI-compat), then ``GET /api/tags`` (Ollama).
    """
    headers: dict[str, str] = {}
    if auth_key:
        headers["Authorization"] = f"Bearer {auth_key}"

    async with httpx.AsyncClient(timeout=_HEALTH_TIMEOUT) as client:
        for path in ("/v1/models", "/api/tags"):
            try:
                resp = await client.get(url.rstrip("/") + path, headers=headers)
                if resp.status_code < 500:
                    if resp.status_code >= 400:
                        logger.warning(
                            "Health check for %s%s returned %d — server reachable but possible auth misconfiguration",
                            url, path, resp.status_code,
                        )
                    return True
            except Exception:
                continue
    return False


class HealthMonitor:
    """
    Async background task that periodically health-checks temp providers.

    Usage::

        monitor = HealthMonitor(interval_s=30, auto_remove_after_s=300)
        await monitor.start()
        ...
        await monitor.stop()
    """

    def __init__(
        self,
        interval_s: float = 30,
        auto_remove_after_s: float = 300,
        registry: Optional[TempProviderRegistry] = None,
    ) -> None:
        self.interval_s = interval_s
        self.auto_remove_after_s = auto_remove_after_s
        self._registry = registry or TempProviderRegistry()
        self._task: Optional[asyncio.Task] = None

    def start(self) -> None:
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._run(), name="temp-provider-health-monitor")
        logger.info("Temp-provider health monitor started (interval=%ss)", self.interval_s)

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:  # noqa: PERF203
            logger.debug("Health monitor task cancelled")
        self._task = None
        logger.info("Temp-provider health monitor stopped")

    async def _run(self) -> None:
        while True:
            try:
                await self._check_all()
                self._registry.remove_stale(self.auto_remove_after_s)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Unexpected error in health monitor loop")
            await asyncio.sleep(self.interval_s)

    async def _check_all(self) -> None:
        providers = self._registry.list_all()
        for prov in providers:
            try:
                healthy = await _check_provider_health(prov.url, prov.auth_key)
            except Exception:
                healthy = False

            was_healthy = prov.is_healthy
            if healthy:
                self._registry.mark_healthy(prov.id)
                if not was_healthy:
                    logger.info("Temp provider %s (%s) is healthy again", prov.id, prov.name)
            else:
                self._registry.mark_unhealthy(prov.id)
                if was_healthy:
                    logger.warning("Temp provider %s (%s) is now unhealthy", prov.id, prov.name)

    async def run_once(self) -> None:
        """Run a single health-check cycle (useful for testing)."""
        await self._check_all()
        self._registry.remove_stale(self.auto_remove_after_s)
