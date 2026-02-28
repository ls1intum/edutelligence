"""
Continuous Ollama provider monitoring system.

Polls /api/ps endpoints of all distinct Ollama providers every 5 seconds to track:
- Loaded models
- VRAM usage
- Model expiration times

Stores snapshots in ollama_provider_snapshots table for real-time dashboards,
capacity planning, and performance analysis.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

import aiohttp

from logos.dbutils.dbmanager import DBManager

logger = logging.getLogger(__name__)


def _discover_providers() -> List[Dict[int, str]]:
    """
    Query database for all providers

    Returns:
        List of unique Ollama provider Ids
    """
    try:
        with DBManager() as db:
            return db.get_ollama_providers()
    except Exception as e:
        logger.error(f"Failed to discover Ollama providers: {e}")
        return []


def _get_auth_headers_for_ps(provider_id: int) -> Dict[str, str] | None:
    """
    Build auth headers for /api/ps based on provider config in DB.
    """
    try:
        with DBManager() as db:
            auth = db.get_provider_auth(provider_id)

        if not auth:
            return {}

        auth_name = (auth.get("auth_name") or "").strip()
        auth_format = auth.get("auth_format") or ""
        api_key = auth.get("api_key")

        if not auth_name or not auth_format:
            return {}
        if not api_key:
            logger.warning(
                "Missing API key for provider=%s - /api/ps auth skipped",
                provider_id
            )
            return {}

        return {auth_name: auth_format.format(api_key)}
    except Exception as e:
        logger.warning(f"Failed to resolve /api/ps auth for {provider_id}: {e}")
        return {}


def _insert_error_snapshot(provider_id: int, error_message: str) -> None:
    """
    Insert a snapshot with poll_success=FALSE to track errors.

    Args:
        provider_id: Provider ID (FK to providers.id)
        error_message: Description of the error
    """
    try:
        with DBManager() as db:
            db.insert_provider_snapshot(
                provider_id=provider_id,
                total_models_loaded=0,
                total_vram_used_bytes=0,
                loaded_models=[],
                poll_success=False,
                error_message=error_message
            )
    except Exception as e:
        # If we can't even insert an error snapshot, just log it
        logger.error(f"Failed to insert error snapshot for provider {provider_id}: {e}")


class OllamaProviderMonitor:
    """
    Background task manager for continuous Ollama provider monitoring.

    Discovers all distinct ollama_admin_urls at startup, then launches
    independent polling tasks for each URL. Each task queries /api/ps
    every 5 seconds and stores snapshots in the database.
    """

    def __init__(self) -> None:
        self._tasks: Set[asyncio.Task] = set()
        self._shutdown_event = asyncio.Event()
        self._http_session: Optional[aiohttp.ClientSession] = None

    async def start(self) -> None:
        """
        Discover Ollama providers and start polling tasks.

        Creates an HTTP session with connection pooling and launches
        one asyncio task per each provider. Tasks run independently so
        failures don't cascade.
        """
        # Create HTTP session with connection pooling
        timeout = aiohttp.ClientTimeout(total=5.0)
        connector = aiohttp.TCPConnector(limit_per_host=1)
        self._http_session = aiohttp.ClientSession(
            timeout=timeout,
            connector=connector
        )

        # Discover all unique Ollama provider URLs
        providers = _discover_providers()
        logger.info(f"Discovered {len(providers)} distinct Ollama provider URLs")

        if not providers:
            logger.warning("No Ollama providers found. Monitoring will not start.")
            return

        # Launch one polling task per URL
        for provider in providers:
            provider_id = provider.get("id")
            provider_url = provider.get("ollama_admin_url")
            if not provider_id or not provider_url:
                logger.warning("Skipping provider with missing id/url: %s", provider)
                continue
            task = asyncio.create_task(
                self._poll_provider_loop(provider_id, provider_url),
                name=f"ollama-monitor-{provider_id}"
            )
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

        logger.info(f"Started {len(self._tasks)} Ollama provider monitoring tasks")

    async def stop(self) -> None:
        """
        Gracefully shutdown all polling tasks and cleanup resources.

        Sets shutdown event, waits for tasks to complete, and closes
        the HTTP session.
        """
        logger.info("Stopping Ollama provider monitoring...")
        self._shutdown_event.set()

        # Wait for all tasks to finish (they'll exit on next poll cycle)
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
            logger.info(f"Stopped {len(self._tasks)} monitoring tasks")

        # Close HTTP session
        if self._http_session:
            await self._http_session.close()
            self._http_session = None

        logger.info("Ollama provider monitoring stopped")

    async def _poll_provider_loop(self, provider_id: int, provider_ollama_url: str) -> None:
        """
        Continuous polling loop for provider

        Polls every 5 seconds until shutdown event is set. Each poll cycle
        is independent - errors are logged but don't break the loop.

        Args:
            provider_id: Ollama provider id
            provider_ollama_url: Ollama admin URL to poll
        """
        logger.info(f"Started polling Ollama provider: {provider_ollama_url} ({provider_id})")

        while not self._shutdown_event.is_set():
            try:
                await self._poll_once(provider_id, provider_ollama_url)
            except Exception as e:
                # Log error but don't break the loop
                logger.error(f"Poll failed for {provider_ollama_url} ({provider_id}): {e}", exc_info=True)

            # Wait 5 seconds before next poll
            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=5.0
                )
                # If we get here, shutdown was signaled
                break
            except asyncio.TimeoutError:
                # Timeout is expected - means 5 seconds elapsed
                continue

        logger.info(f"Stopped polling Ollama provider: {provider_ollama_url} ({provider_id})")

    async def _poll_once(self, provider_id: int, provider_ollama_url: str) -> None:
        """
        Single poll cycle: fetch /api/ps, parse response, insert snapshot.

        Always inserts a snapshot even on failure (with poll_success=FALSE)
        to track uptime and errors.

        Args:
            provider_id: Ollama admin URL to poll
        """
        if not self._http_session:
            logger.error("HTTP session not initialized")
            return

        try:
            # HTTP GET /api/ps
            headers = _get_auth_headers_for_ps(provider_id)
            async with self._http_session.get(
                f"{provider_ollama_url}/api/ps",
                headers=headers if headers else None
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()

            # Parse response and extract metrics
            models = data.get("models", [])
            loaded_models = []
            total_vram = 0

            for model in models:
                model_name = model.get("name") or model.get("model")
                if not model_name:
                    continue

                size_vram = model.get("size_vram", 0)
                total_vram += size_vram

                loaded_models.append({
                    "name": model_name,
                    "size_vram": size_vram,
                    "size_vram_mb": size_vram // (1024 * 1024) if size_vram else 0,
                    "expires_at": model.get("expires_at")
                })

            # Insert successful snapshot
            with DBManager() as db:
                db.insert_provider_snapshot(
                    provider_id=provider_id,
                    total_models_loaded=len(loaded_models),
                    total_vram_used_bytes=total_vram,
                    loaded_models=loaded_models,
                    poll_success=True,
                    error_message=None
                )

            logger.debug(
                f"Polled {provider_id}: {len(loaded_models)} models, "
                f"{total_vram // (1024**3):.1f}GB VRAM"
            )

        except asyncio.TimeoutError:
            # HTTP timeout
            logger.warning(f"Timeout polling {provider_id}")
            _insert_error_snapshot(provider_id, "HTTP timeout after 5 seconds")

        except aiohttp.ClientError as e:
            # HTTP/connection errors
            logger.warning(f"HTTP error polling {provider_id}: {e}")
            _insert_error_snapshot(provider_id, f"HTTP error: {e}")

        except json.JSONDecodeError as e:
            # Malformed JSON response
            logger.warning(f"Invalid JSON from {provider_id}: {e}")
            _insert_error_snapshot(provider_id, f"JSON decode error: {e}")

        except Exception as e:
            # Other errors (DB, parsing, etc.)
            logger.error(f"Unexpected error polling {provider_id}: {e}", exc_info=True)
            _insert_error_snapshot(provider_id, f"Unexpected error: {e}")
