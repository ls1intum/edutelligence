"""
Ollama instance status poller.

Periodically queries the managed Ollama container's HTTP API to collect
loaded models, available models, and version.  Results are cached and
served via the Logos-facing API.

Uses a single shared httpx.AsyncClient for all requests.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from node_controller.models import (
    AvailableModel,
    LoadedModel,
    OllamaConfig,
    OllamaStatus,
)

logger = logging.getLogger("node_controller.ollama_status")


class OllamaStatusPoller:
    """Background poller for the managed Ollama instance."""

    def __init__(self, poll_interval: int = 5) -> None:
        self._poll_interval = poll_interval
        self._status = OllamaStatus()
        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None
        self._http: httpx.AsyncClient | None = None
        self._config: OllamaConfig | None = None

    async def start(self, config: OllamaConfig) -> None:
        """Begin background polling against the given Ollama config."""
        self._config = config
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=15.0, write=10.0, pool=5.0)
        )
        self._task = asyncio.create_task(self._poll_loop(), name="ollama-poll")
        logger.info("Ollama status poller started (interval=%ds)", self._poll_interval)

    async def stop(self) -> None:
        """Stop polling and close the HTTP client."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._http:
            await self._http.aclose()
            self._http = None
        logger.info("Ollama status poller stopped")

    def update_config(self, config: OllamaConfig) -> None:
        """Update the target Ollama config (e.g. after reconfigure)."""
        self._config = config

    async def get_status(self) -> OllamaStatus:
        """Return the latest cached Ollama status."""
        async with self._lock:
            return self._status.model_copy()

    async def refresh(self) -> OllamaStatus:
        """Force an immediate refresh and return fresh status."""
        await self._poll()
        return await self.get_status()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _base_url(self) -> str:
        assert self._config is not None
        return f"http://{self._config.container_name}:{self._config.container_port}"

    async def _poll_loop(self) -> None:
        while True:
            await asyncio.sleep(self._poll_interval)
            try:
                await self._poll()
            except Exception:
                logger.exception("Error polling Ollama status")

    async def _poll(self) -> None:
        if self._http is None or self._config is None:
            return

        url = self._base_url()

        # Fire all three requests concurrently instead of sequentially.
        # This cuts poll latency from ~3 round-trips to ~1.
        async def _fetch_version() -> tuple[bool, str | None]:
            try:
                resp = await self._http.get(f"{url}/api/version", timeout=5.0)  # type: ignore[union-attr]
                if resp.status_code == 200:
                    return True, resp.json().get("version")
            except httpx.HTTPError:
                pass
            return False, None

        async def _fetch_loaded() -> list[LoadedModel]:
            try:
                resp = await self._http.get(f"{url}/api/ps", timeout=10.0)  # type: ignore[union-attr]
                if resp.status_code == 200:
                    return self._parse_loaded_models(resp.json())
            except httpx.HTTPError as e:
                logger.debug("Failed to query /api/ps: %s", e)
            return []

        async def _fetch_available() -> list[AvailableModel]:
            try:
                resp = await self._http.get(f"{url}/api/tags", timeout=10.0)  # type: ignore[union-attr]
                if resp.status_code == 200:
                    return self._parse_available_models(resp.json())
            except httpx.HTTPError as e:
                logger.debug("Failed to query /api/tags: %s", e)
            return []

        (reachable, version), loaded, available = await asyncio.gather(
            _fetch_version(), _fetch_loaded(), _fetch_available()
        )

        if not reachable:
            async with self._lock:
                self._status = OllamaStatus(reachable=False)
            return

        async with self._lock:
            self._status = OllamaStatus(
                reachable=reachable,
                loaded_models=loaded,
                available_models=available,
                version=version,
            )

    @staticmethod
    def _parse_loaded_models(data: dict[str, Any]) -> list[LoadedModel]:
        """Parse the /api/ps response into LoadedModel objects."""
        models: list[LoadedModel] = []
        for item in data.get("models", []):
            expires_at = None
            if ea := item.get("expires_at"):
                try:
                    expires_at = datetime.fromisoformat(ea.replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    pass

            models.append(
                LoadedModel(
                    name=item.get("name", ""),
                    size=item.get("size", 0),
                    size_vram=item.get("size_vram", 0),
                    expires_at=expires_at,
                    digest=item.get("digest"),
                    details=item.get("details", {}),
                )
            )
        return models

    @staticmethod
    def _parse_available_models(data: dict[str, Any]) -> list[AvailableModel]:
        """Parse the /api/tags response into AvailableModel objects."""
        models: list[AvailableModel] = []
        for item in data.get("models", []):
            modified_at = None
            if ma := item.get("modified_at"):
                try:
                    modified_at = datetime.fromisoformat(ma.replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    pass

            models.append(
                AvailableModel(
                    name=item.get("name", ""),
                    size=item.get("size", 0),
                    digest=item.get("digest"),
                    modified_at=modified_at,
                    details=item.get("details", {}),
                )
            )
        return models
