"""
Ollama process lifecycle manager.

Manages exactly ONE Ollama server process — spawn, stop, restart,
reconfigure (kill + re-spawn with new env), and status.  Communicates
with the running Ollama instance via its HTTP API for model operations.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from typing import Any, AsyncIterator

import httpx

from node_controller.models import OllamaConfig, ProcessState, ProcessStatus

logger = logging.getLogger("node_controller.ollama_manager")

_READY_TIMEOUT = 60        # seconds to wait for Ollama to accept requests
_PRELOAD_TIMEOUT = 120     # seconds per model preload
_STOP_TIMEOUT = 10         # seconds for graceful SIGTERM before SIGKILL


class OllamaManager:
    """Manages the lifecycle of a single Ollama server process."""

    def __init__(self) -> None:
        self._process: asyncio.subprocess.Process | None = None
        self._http: httpx.AsyncClient | None = None
        self._preload_tasks: list[asyncio.Task] = []
        self._reconfigure_lock = asyncio.Lock()
        self._config: OllamaConfig | None = None
        self._log_task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # Initialisation & teardown
    # ------------------------------------------------------------------

    async def init(self) -> None:
        """Prepare the shared httpx client."""
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)
        )

    async def close(self) -> None:
        """Cancel in-flight preloads and release the HTTP client."""
        for task in self._preload_tasks:
            if not task.done():
                task.cancel()
        if self._preload_tasks:
            await asyncio.gather(*self._preload_tasks, return_exceptions=True)
            self._preload_tasks.clear()

        if self._http:
            await self._http.aclose()
            self._http = None

    # ------------------------------------------------------------------
    # Process lifecycle
    # ------------------------------------------------------------------

    async def spawn(self, config: OllamaConfig) -> ProcessStatus:
        """
        Spawn a new Ollama server process with the given config.

        If a process is already running, it is stopped first.
        """
        if self._process is not None and self._process.returncode is None:
            logger.info("Stopping existing Ollama process (pid=%d) before spawn", self._process.pid)
            await self._kill_process()

        self._config = config
        env = self._build_env(config)

        logger.info(
            "Spawning Ollama process (binary=%s, port=%d, num_parallel=%d)",
            config.ollama_binary,
            config.port,
            config.num_parallel,
        )

        # Merge current environment with Ollama-specific vars
        process_env = {**os.environ, **env}

        self._process = await asyncio.create_subprocess_exec(
            config.ollama_binary, "serve",
            env=process_env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        # Stream Ollama logs to our logger
        if self._log_task is not None and not self._log_task.done():
            self._log_task.cancel()
        self._log_task = asyncio.create_task(
            self._stream_logs(), name="ollama-logs"
        )

        logger.info("Ollama process spawned (pid=%d)", self._process.pid)

        # Wait for the HTTP API to become ready
        ready = await self._wait_for_ready(config, timeout=_READY_TIMEOUT)
        if not ready:
            logger.warning("Ollama process did not become ready within %ds", _READY_TIMEOUT)

        # Fire-and-forget preloads
        if config.preload_models:
            task = asyncio.create_task(
                self._preload_models(config.preload_models),
                name="preload",
            )
            task.add_done_callback(self._preload_done_callback)
            self._preload_tasks.append(task)

        return self.status()

    async def stop(self) -> ProcessStatus:
        """Gracefully stop the running Ollama process."""
        if self._process is None or self._process.returncode is not None:
            logger.info("No running Ollama process to stop")
            return self.status()

        await self._kill_process()
        return self.status()

    async def restart(self) -> ProcessStatus:
        """Restart the Ollama process with the current config."""
        if self._config is None:
            raise RuntimeError("Cannot restart — no config available (never spawned)")
        return await self.spawn(self._config)

    async def reconfigure(self, config: OllamaConfig) -> ProcessStatus:
        """
        Stop the current process and re-spawn with updated config.

        Protected by a lock to prevent concurrent reconfigure races.
        """
        async with self._reconfigure_lock:
            logger.info("Reconfiguring Ollama process with new settings")
            return await self.spawn(config)

    async def destroy(self) -> None:
        """Stop the process and clear state."""
        await self.stop()
        self._config = None
        logger.info("Ollama process destroyed")

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def status(self) -> ProcessStatus:
        """Get the current status of the managed Ollama process."""
        if self._process is None:
            return ProcessStatus(state=ProcessState.NOT_STARTED)

        if self._process.returncode is None:
            return ProcessStatus(
                state=ProcessState.RUNNING,
                pid=self._process.pid,
            )
        else:
            return ProcessStatus(
                state=ProcessState.STOPPED,
                pid=self._process.pid,
                return_code=self._process.returncode,
            )

    # ------------------------------------------------------------------
    # Model operations (via Ollama HTTP API)
    # ------------------------------------------------------------------

    def _ollama_url(self) -> str:
        """Construct the Ollama API base URL."""
        port = self._config.port if self._config else 11435
        return f"http://127.0.0.1:{port}"

    async def unload_model(self, model_name: str) -> bool:
        """Unload a model from VRAM by setting keep_alive to 0."""
        try:
            resp = await self._http.post(
                f"{self._ollama_url()}/api/generate",
                json={"model": model_name, "keep_alive": 0},
                timeout=30.0,
            )
            return resp.status_code == 200
        except httpx.HTTPError as e:
            logger.warning("Failed to unload model '%s': %s", model_name, e)
            return False

    async def preload_model(self, model_name: str) -> bool:
        """Preload a model into VRAM."""
        try:
            resp = await self._http.post(
                f"{self._ollama_url()}/api/generate",
                json={"model": model_name},
                timeout=_PRELOAD_TIMEOUT,
            )
            return resp.status_code == 200
        except httpx.HTTPError as e:
            logger.warning("Failed to preload model '%s': %s", model_name, e)
            return False

    async def pull_model(self, model_name: str) -> bool:
        """Pull (download) a model."""
        try:
            resp = await self._http.post(
                f"{self._ollama_url()}/api/pull",
                json={"name": model_name, "stream": False},
                timeout=600.0,
            )
            return resp.status_code == 200
        except httpx.HTTPError as e:
            logger.warning("Failed to pull model '%s': %s", model_name, e)
            return False

    async def delete_model(self, model_name: str) -> bool:
        """Delete a model from disk."""
        try:
            resp = await self._http.request(
                "DELETE",
                f"{self._ollama_url()}/api/delete",
                json={"name": model_name},
                timeout=30.0,
            )
            return resp.status_code == 200
        except httpx.HTTPError as e:
            logger.warning("Failed to delete model '%s': %s", model_name, e)
            return False

    async def create_model(self, name: str, modelfile: str) -> bool:
        """Create a model variant from a Modelfile specification."""
        try:
            resp = await self._http.post(
                f"{self._ollama_url()}/api/create",
                json={"name": name, "modelfile": modelfile, "stream": False},
                timeout=600.0,
            )
            return resp.status_code == 200
        except httpx.HTTPError as e:
            logger.warning("Failed to create model '%s': %s", name, e)
            return False

    async def copy_model(self, source: str, destination: str) -> bool:
        """Copy a model under a new name."""
        try:
            resp = await self._http.post(
                f"{self._ollama_url()}/api/copy",
                json={"source": source, "destination": destination},
                timeout=30.0,
            )
            return resp.status_code == 200
        except httpx.HTTPError as e:
            logger.warning("Failed to copy '%s' -> '%s': %s", source, destination, e)
            return False

    async def show_model(self, model_name: str) -> dict[str, Any] | None:
        """Get detailed model information."""
        try:
            resp = await self._http.post(
                f"{self._ollama_url()}/api/show",
                json={"name": model_name},
                timeout=30.0,
            )
            if resp.status_code == 200:
                return resp.json()
            return None
        except httpx.HTTPError as e:
            logger.warning("Failed to show model '%s': %s", model_name, e)
            return None

    async def pull_model_streaming(self, model_name: str) -> AsyncIterator[dict[str, Any]]:
        """Pull a model with streaming progress updates (NDJSON)."""
        async with self._http.stream(
            "POST",
            f"{self._ollama_url()}/api/pull",
            json={"name": model_name, "stream": True},
            timeout=httpx.Timeout(connect=5.0, read=3600.0, write=10.0, pool=5.0),
        ) as resp:
            async for line in resp.aiter_lines():
                if line.strip():
                    try:
                        import json
                        yield json.loads(line)
                    except (json.JSONDecodeError, ValueError):
                        pass

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_env(config: OllamaConfig) -> dict[str, str]:
        """Build the environment variables for the Ollama process."""
        env = {
            "OLLAMA_HOST": f"0.0.0.0:{config.port}",
            "OLLAMA_NUM_PARALLEL": str(config.num_parallel),
            "OLLAMA_MAX_LOADED_MODELS": str(config.max_loaded_models),
            "OLLAMA_KEEP_ALIVE": config.keep_alive,
            "OLLAMA_MAX_QUEUE": str(config.max_queue),
            "OLLAMA_MODELS": config.models_path,
        }
        if config.flash_attention:
            env["OLLAMA_FLASH_ATTENTION"] = "1"
        if config.kv_cache_type != "f16":
            env["OLLAMA_KV_CACHE_TYPE"] = config.kv_cache_type
        if config.context_length > 0:
            env["OLLAMA_CONTEXT_LENGTH"] = str(config.context_length)
        if config.sched_spread:
            env["OLLAMA_SCHED_SPREAD"] = "1"
        if config.multiuser_cache:
            env["OLLAMA_MULTIUSER_CACHE"] = "1"
        if config.gpu_overhead_bytes > 0:
            env["OLLAMA_GPU_OVERHEAD"] = str(config.gpu_overhead_bytes)
        if config.load_timeout:
            env["OLLAMA_LOAD_TIMEOUT"] = config.load_timeout
        if config.origins:
            env["OLLAMA_ORIGINS"] = ",".join(config.origins)
        if config.noprune:
            env["OLLAMA_NOPRUNE"] = "1"
        if config.llm_library:
            env["OLLAMA_LLM_LIBRARY"] = config.llm_library
        if config.gpu_devices.lower() not in ("all", "none"):
            env["CUDA_VISIBLE_DEVICES"] = config.gpu_devices
        elif config.gpu_devices.lower() == "none":
            env["CUDA_VISIBLE_DEVICES"] = ""
        env.update(config.env_overrides)
        return env

    async def _kill_process(self) -> None:
        """Send SIGTERM, wait, then SIGKILL if necessary."""
        if self._process is None or self._process.returncode is not None:
            return

        pid = self._process.pid
        logger.info("Stopping Ollama process (pid=%d)", pid)

        # Cancel log streaming
        if self._log_task is not None and not self._log_task.done():
            self._log_task.cancel()

        try:
            self._process.send_signal(signal.SIGTERM)
        except ProcessLookupError:
            return

        try:
            await asyncio.wait_for(self._process.wait(), timeout=_STOP_TIMEOUT)
            logger.info("Ollama process (pid=%d) exited gracefully", pid)
        except asyncio.TimeoutError:
            logger.warning("Ollama process (pid=%d) did not exit in %ds — sending SIGKILL", pid, _STOP_TIMEOUT)
            try:
                self._process.kill()
                await self._process.wait()
            except ProcessLookupError:
                pass

    async def _stream_logs(self) -> None:
        """Read Ollama stdout/stderr and forward to our logger."""
        if self._process is None or self._process.stdout is None:
            return
        try:
            async for line_bytes in self._process.stdout:
                line = line_bytes.decode("utf-8", errors="replace").rstrip()
                if line:
                    logger.info("[ollama] %s", line)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.debug("Log streaming ended", exc_info=True)

    async def _wait_for_ready(self, config: OllamaConfig, timeout: int = _READY_TIMEOUT) -> bool:
        """Poll /api/version until Ollama responds."""
        url = f"http://127.0.0.1:{config.port}"
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        delay = 0.1
        while loop.time() < deadline:
            # Check the process hasn't died
            if self._process is not None and self._process.returncode is not None:
                logger.error("Ollama process exited with code %d during startup", self._process.returncode)
                return False
            try:
                resp = await self._http.get(f"{url}/api/version", timeout=5.0)
                if resp.status_code == 200:
                    elapsed_ms = int((loop.time() - (deadline - timeout)) * 1000)
                    logger.info("Ollama ready at %s (%dms)", url, elapsed_ms)
                    return True
            except httpx.HTTPError:
                pass
            await asyncio.sleep(delay)
            delay = min(delay * 2, 2.0)
        return False

    async def _preload_models(self, models: list[str]) -> None:
        """Preload models into VRAM concurrently."""
        async def _load_one(model: str) -> None:
            logger.info("Preloading model '%s'...", model)
            ok = await self.preload_model(model)
            if ok:
                logger.info("Model '%s' preloaded", model)
            else:
                logger.warning("Failed to preload model '%s'", model)

        await asyncio.gather(*[_load_one(m) for m in models])

    def _preload_done_callback(self, task: asyncio.Task) -> None:
        """Log exceptions from fire-and-forget preload tasks."""
        if task in self._preload_tasks:
            self._preload_tasks.remove(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error("Preload task failed: %s", exc, exc_info=exc)
