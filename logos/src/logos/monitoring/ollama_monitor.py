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
        Discover distinct Ollama provider URLs and start polling tasks.

        Creates an HTTP session with connection pooling and launches
        one asyncio task per unique URL. Tasks run independently so
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
        urls = self._discover_unique_urls()
        logger.info(f"Discovered {len(urls)} distinct Ollama provider URLs")

        if not urls:
            logger.warning("No Ollama providers found. Monitoring will not start.")
            return

        # Launch one polling task per URL
        for url in urls:
            task = asyncio.create_task(
                self._poll_provider_loop(url),
                name=f"ollama-monitor-{url}"
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

    def _discover_unique_urls(self) -> List[str]:
        """
        Query database for all distinct ollama_admin_urls.

        Returns:
            List of unique Ollama admin URLs (e.g., ["http://host.docker.internal:11435"])
        """
        try:
            with DBManager() as db:
                return db.get_distinct_ollama_urls()
        except Exception as e:
            logger.error(f"Failed to discover Ollama provider URLs: {e}")
            return []

    async def _poll_provider_loop(self, url: str) -> None:
        """
        Continuous polling loop for a single Ollama provider URL.

        Polls every 5 seconds until shutdown event is set. Each poll cycle
        is independent - errors are logged but don't break the loop.

        Args:
            url: Ollama admin URL to poll (e.g., "http://host.docker.internal:11435")
        """
        logger.info(f"Started polling Ollama provider: {url}")

        while not self._shutdown_event.is_set():
            try:
                await self._poll_once(url)
            except Exception as e:
                # Log error but don't break the loop
                logger.error(f"Poll failed for {url}: {e}", exc_info=True)

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

        logger.info(f"Stopped polling Ollama provider: {url}")

    async def _poll_once(self, url: str) -> None:
        """
        Single poll cycle: fetch /api/ps, parse response, insert snapshot.

        Always inserts a snapshot even on failure (with poll_success=FALSE)
        to track uptime and errors.

        Args:
            url: Ollama admin URL to poll
        """
        if not self._http_session:
            logger.error("HTTP session not initialized")
            return

        try:
            # HTTP GET /api/ps
            async with self._http_session.get(f"{url}/api/ps") as resp:
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
                    ollama_admin_url=url,
                    total_models_loaded=len(loaded_models),
                    total_vram_used_bytes=total_vram,
                    loaded_models=loaded_models,
                    poll_success=True,
                    error_message=None
                )

            logger.debug(
                f"Polled {url}: {len(loaded_models)} models, "
                f"{total_vram // (1024**3):.1f}GB VRAM"
            )

        except asyncio.TimeoutError:
            # HTTP timeout
            logger.warning(f"Timeout polling {url}")
            self._insert_error_snapshot(url, "HTTP timeout after 5 seconds")

        except aiohttp.ClientError as e:
            # HTTP/connection errors
            logger.warning(f"HTTP error polling {url}: {e}")
            self._insert_error_snapshot(url, f"HTTP error: {e}")

        except json.JSONDecodeError as e:
            # Malformed JSON response
            logger.warning(f"Invalid JSON from {url}: {e}")
            self._insert_error_snapshot(url, f"JSON decode error: {e}")

        except Exception as e:
            # Other errors (DB, parsing, etc.)
            logger.error(f"Unexpected error polling {url}: {e}", exc_info=True)
            self._insert_error_snapshot(url, f"Unexpected error: {e}")

    def _insert_error_snapshot(self, url: str, error_message: str) -> None:
        """
        Insert a snapshot with poll_success=FALSE to track errors.

        Args:
            url: Ollama admin URL that failed
            error_message: Description of the error
        """
        try:
            with DBManager() as db:
                db.insert_provider_snapshot(
                    ollama_admin_url=url,
                    total_models_loaded=0,
                    total_vram_used_bytes=0,
                    loaded_models=[],
                    poll_success=False,
                    error_message=error_message
                )
        except Exception as e:
            # If we can't even insert an error snapshot, just log it
            logger.error(f"Failed to insert error snapshot for {url}: {e}")
