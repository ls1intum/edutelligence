"""
Ollama process handle — manages exactly ONE Ollama server subprocess.

Extracted from OllamaManager to support multi-lane operation where each
lane gets its own OllamaProcessHandle running on a dedicated port.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from typing import Any, AsyncIterator

import httpx

from logos_worker_node.models import LaneConfig, OllamaConfig, ProcessState, ProcessStatus

logger = logging.getLogger("logos_worker_node.ollama_process")

_READY_TIMEOUT = 60
_PRELOAD_TIMEOUT = 120
_PULL_TIMEOUT = 3600  # Allow up to 1h for large model downloads (e.g. via Ceph)
_STOP_TIMEOUT = 10
_FORCE_KILL_WAIT_TIMEOUT = 5


class OllamaProcessHandle:
    """Manages a single Ollama server process on a specific port."""

    def __init__(self, lane_id: str, port: int, global_config: OllamaConfig) -> None:
        self.lane_id = lane_id
        self.port = port
        self._global_config = global_config
        self._lane_config: LaneConfig | None = None
        self._process: asyncio.subprocess.Process | None = None
        self._process_group_id: int | None = None
        self._http: httpx.AsyncClient | None = None
        self._preload_tasks: list[asyncio.Task] = []
        self._reconfigure_lock = asyncio.Lock()
        self._log_task: asyncio.Task | None = None

    async def init(self) -> None:
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)
        )

    async def close(self) -> None:
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

    async def spawn(self, lane_config: LaneConfig) -> ProcessStatus:
        """Spawn the Ollama process for this lane."""
        if self._process is not None and self._process.returncode is None:
            logger.info("[%s] Stopping existing process (pid=%d) before spawn", self.lane_id, self._process.pid)
            await self._kill_process()

        self._lane_config = lane_config
        env = self._build_env(lane_config)

        logger.info(
            "[%s] Spawning Ollama (port=%d, model=%s, num_parallel=%d)",
            self.lane_id, self.port, lane_config.model, lane_config.num_parallel,
        )

        process_env = {**os.environ, **env}
        self._process = await asyncio.create_subprocess_exec(
            self._global_config.ollama_binary, "serve",
            env=process_env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
        )
        self._process_group_id = self._process.pid

        if self._log_task is not None and not self._log_task.done():
            self._log_task.cancel()
        self._log_task = asyncio.create_task(
            self._stream_logs(), name=f"logs-{self.lane_id}"
        )

        logger.info(
            "[%s] Process spawned (pid=%d, pgid=%d)",
            self.lane_id,
            self._process.pid,
            self._process_group_id,
        )

        logger.info("[%s] Process spawned (pid=%d)", self.lane_id, self._process.pid)

        ready = await self._wait_for_ready(timeout=_READY_TIMEOUT)
        if not ready:
            logger.warning("[%s] Process did not become ready within %ds", self.lane_id, _READY_TIMEOUT)

        # Ensure model is available locally before preloading into VRAM.
        # On shared storage (e.g. Ceph volumes) the model may already exist
        # from a previous node — this check avoids redundant downloads.
        await self._ensure_model_available(lane_config.model)

        # Auto-preload the lane's model into VRAM
        task = asyncio.create_task(
            self._preload_model(lane_config.model),
            name=f"preload-{self.lane_id}",
        )
        task.add_done_callback(self._preload_done_callback)
        self._preload_tasks.append(task)

        return self.status()

    async def stop(self) -> ProcessStatus:
        if self._process is None or self._process.returncode is not None:
            return self.status()
        await self._kill_process()
        return self.status()

    async def reconfigure(self, lane_config: LaneConfig) -> ProcessStatus:
        async with self._reconfigure_lock:
            logger.info("[%s] Reconfiguring with num_parallel=%d", self.lane_id, lane_config.num_parallel)
            return await self.spawn(lane_config)

    async def destroy(self) -> None:
        await self.stop()
        self._lane_config = None

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def status(self) -> ProcessStatus:
        if self._process is None:
            return ProcessStatus(state=ProcessState.NOT_STARTED)
        if self._process.returncode is None:
            return ProcessStatus(state=ProcessState.RUNNING, pid=self._process.pid)
        return ProcessStatus(
            state=ProcessState.STOPPED,
            pid=self._process.pid,
            return_code=self._process.returncode,
        )

    @property
    def lane_config(self) -> LaneConfig | None:
        return self._lane_config

    # ------------------------------------------------------------------
    # Model operations (via Ollama HTTP API)
    # ------------------------------------------------------------------

    def _ollama_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    async def unload_model(self, model_name: str) -> bool:
        try:
            resp = await self._http.post(
                f"{self._ollama_url()}/api/generate",
                json={"model": model_name, "keep_alive": 0},
                timeout=30.0,
            )
            return resp.status_code == 200
        except httpx.HTTPError as e:
            logger.warning("[%s] Failed to unload model '%s': %s", self.lane_id, model_name, e)
            return False

    async def preload_model(self, model_name: str) -> bool:
        try:
            resp = await self._http.post(
                f"{self._ollama_url()}/api/generate",
                json={"model": model_name},
                timeout=_PRELOAD_TIMEOUT,
            )
            return resp.status_code == 200
        except httpx.HTTPError as e:
            logger.warning("[%s] Failed to preload model '%s': %s", self.lane_id, model_name, e)
            return False

    async def pull_model(self, model_name: str) -> bool:
        try:
            resp = await self._http.post(
                f"{self._ollama_url()}/api/pull",
                json={"name": model_name, "stream": False},
                timeout=600.0,
            )
            return resp.status_code == 200
        except httpx.HTTPError as e:
            logger.warning("[%s] Failed to pull model '%s': %s", self.lane_id, model_name, e)
            return False

    async def delete_model(self, model_name: str) -> bool:
        try:
            resp = await self._http.request(
                "DELETE",
                f"{self._ollama_url()}/api/delete",
                json={"name": model_name},
                timeout=30.0,
            )
            return resp.status_code == 200
        except httpx.HTTPError as e:
            logger.warning("[%s] Failed to delete model '%s': %s", self.lane_id, model_name, e)
            return False

    async def create_model(self, name: str, modelfile: str) -> bool:
        try:
            resp = await self._http.post(
                f"{self._ollama_url()}/api/create",
                json={"name": name, "modelfile": modelfile, "stream": False},
                timeout=600.0,
            )
            return resp.status_code == 200
        except httpx.HTTPError as e:
            logger.warning("[%s] Failed to create model '%s': %s", self.lane_id, name, e)
            return False

    async def copy_model(self, source: str, destination: str) -> bool:
        try:
            resp = await self._http.post(
                f"{self._ollama_url()}/api/copy",
                json={"source": source, "destination": destination},
                timeout=30.0,
            )
            return resp.status_code == 200
        except httpx.HTTPError as e:
            logger.warning("[%s] Failed to copy '%s' -> '%s': %s", self.lane_id, source, destination, e)
            return False

    async def show_model(self, model_name: str) -> dict[str, Any] | None:
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
            logger.warning("[%s] Failed to show model '%s': %s", self.lane_id, model_name, e)
            return None

    async def pull_model_streaming(self, model_name: str) -> AsyncIterator[dict[str, Any]]:
        import json as _json
        async with self._http.stream(
            "POST",
            f"{self._ollama_url()}/api/pull",
            json={"name": model_name, "stream": True},
            timeout=httpx.Timeout(connect=5.0, read=3600.0, write=10.0, pool=5.0),
        ) as resp:
            async for line in resp.aiter_lines():
                if line.strip():
                    try:
                        yield _json.loads(line)
                    except (ValueError, _json.JSONDecodeError):
                        pass

    async def get_loaded_models(self) -> list[dict[str, Any]]:
        """Query /api/ps for models currently in VRAM on this lane's port."""
        try:
            resp = await self._http.get(f"{self._ollama_url()}/api/ps", timeout=10.0)
            if resp.status_code == 200:
                return resp.json().get("models", [])
        except httpx.HTTPError as e:
            logger.debug("[%s] Failed to query /api/ps: %s", self.lane_id, e)
        return []

    async def get_version(self) -> str | None:
        """Query /api/version."""
        try:
            resp = await self._http.get(f"{self._ollama_url()}/api/version", timeout=5.0)
            if resp.status_code == 200:
                return resp.json().get("version")
        except httpx.HTTPError:
            pass
        return None

    async def get_available_models(self) -> list[dict[str, Any]]:
        """Query /api/tags for downloaded models."""
        try:
            resp = await self._http.get(f"{self._ollama_url()}/api/tags", timeout=10.0)
            if resp.status_code == 200:
                return resp.json().get("models", [])
        except httpx.HTTPError as e:
            logger.debug("[%s] Failed to query /api/tags: %s", self.lane_id, e)
        return []

    async def get_backend_metrics(self) -> dict[str, Any]:
        loaded_models = await self.get_loaded_models()
        return {
            "engine": "ollama",
            "loaded_model_count": len(loaded_models),
            "reported_vram_mb": sum(m.get("size_vram", 0) for m in loaded_models) / (1024 * 1024),
        }

    async def sleep(self, level: int = 1, mode: str = "wait") -> dict[str, Any]:
        """Ollama does not expose vLLM-style sleep endpoints."""
        _ = (level, mode)
        return {"supported": False, "detail": "sleep mode is only supported for vLLM lanes"}

    async def wake_up(self) -> dict[str, Any]:
        """Ollama does not expose vLLM-style wake endpoints."""
        return {"supported": False, "detail": "sleep mode is only supported for vLLM lanes"}

    async def is_sleeping(self) -> bool | None:
        """Ollama lanes are always treated as awake."""
        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_env(self, lane_config: LaneConfig) -> dict[str, str]:
        """Build environment variables for this lane's Ollama process."""
        gc = self._global_config
        env: dict[str, str] = {
            "OLLAMA_HOST": f"0.0.0.0:{self.port}",
            "OLLAMA_NUM_PARALLEL": str(lane_config.num_parallel),
            "OLLAMA_MAX_LOADED_MODELS": "1",  # One model per lane
            "OLLAMA_KEEP_ALIVE": lane_config.keep_alive,
            "OLLAMA_MAX_QUEUE": str(gc.max_queue),
            "OLLAMA_MODELS": gc.models_path,
        }
        if lane_config.flash_attention:
            env["OLLAMA_FLASH_ATTENTION"] = "1"
        if lane_config.kv_cache_type != "f16":
            env["OLLAMA_KV_CACHE_TYPE"] = lane_config.kv_cache_type
        if lane_config.context_length > 0:
            env["OLLAMA_CONTEXT_LENGTH"] = str(lane_config.context_length)
        if gc.sched_spread:
            env["OLLAMA_SCHED_SPREAD"] = "1"
        if gc.multiuser_cache:
            env["OLLAMA_MULTIUSER_CACHE"] = "1"
        if gc.gpu_overhead_bytes > 0:
            env["OLLAMA_GPU_OVERHEAD"] = str(gc.gpu_overhead_bytes)
        if gc.load_timeout:
            env["OLLAMA_LOAD_TIMEOUT"] = gc.load_timeout
        if gc.origins:
            env["OLLAMA_ORIGINS"] = ",".join(gc.origins)
        if gc.noprune:
            env["OLLAMA_NOPRUNE"] = "1"
        if gc.llm_library:
            env["OLLAMA_LLM_LIBRARY"] = gc.llm_library

        # GPU device pinning: lane-specific overrides global
        gpu_devices = lane_config.gpu_devices if lane_config.gpu_devices else gc.gpu_devices
        if gpu_devices.lower() not in ("all", "none", ""):
            env["CUDA_VISIBLE_DEVICES"] = gpu_devices
        elif gpu_devices.lower() == "none":
            env["CUDA_VISIBLE_DEVICES"] = ""

        env.update(gc.env_overrides)
        return env

    async def _kill_process(self) -> None:
        if self._process is None or self._process.returncode is not None:
            return
        pid = self._process.pid
        pgid = self._process_group_id or pid
        logger.info("[%s] Stopping process group (pid=%d, pgid=%d)", self.lane_id, pid, pgid)
        if self._log_task is not None and not self._log_task.done():
            self._log_task.cancel()
        try:
            os.killpg(pgid, signal.SIGTERM)
        except ProcessLookupError:
            try:
                self._process.send_signal(signal.SIGTERM)
            except ProcessLookupError:
                self._process_group_id = None
                return
        try:
            await asyncio.wait_for(self._process.wait(), timeout=_STOP_TIMEOUT)
            logger.info("[%s] Process (pid=%d) exited gracefully", self.lane_id, pid)
        except asyncio.TimeoutError:
            logger.warning(
                "[%s] Process group (pid=%d, pgid=%d) did not exit in %ds — SIGKILL",
                self.lane_id,
                pid,
                pgid,
                _STOP_TIMEOUT,
            )
            try:
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                try:
                    self._process.kill()
                except ProcessLookupError:
                    pass
            try:
                await asyncio.wait_for(self._process.wait(), timeout=_FORCE_KILL_WAIT_TIMEOUT)
                logger.info("[%s] Process group (pid=%d, pgid=%d) exited after SIGKILL", self.lane_id, pid, pgid)
            except asyncio.TimeoutError:
                logger.error(
                    "[%s] Process group (pid=%d, pgid=%d) still did not exit %ds after SIGKILL; "
                    "continuing shutdown to avoid wedging the worker",
                    self.lane_id,
                    pid,
                    pgid,
                    _FORCE_KILL_WAIT_TIMEOUT,
                )
            except ProcessLookupError:
                pass
        finally:
            self._process_group_id = None

    async def _stream_logs(self) -> None:
        if self._process is None or self._process.stdout is None:
            return
        try:
            async for line_bytes in self._process.stdout:
                line = line_bytes.decode("utf-8", errors="replace").rstrip()
                if line:
                    logger.info("[ollama:%s] %s", self.lane_id, line)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.debug("[%s] Log streaming ended", self.lane_id, exc_info=True)

    async def _wait_for_ready(self, timeout: int = _READY_TIMEOUT) -> bool:
        url = f"http://127.0.0.1:{self.port}"
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        delay = 0.1
        while loop.time() < deadline:
            if self._process is not None and self._process.returncode is not None:
                logger.error("[%s] Process exited with code %d during startup", self.lane_id, self._process.returncode)
                return False
            try:
                resp = await self._http.get(f"{url}/api/version", timeout=5.0)
                if resp.status_code == 200:
                    elapsed_ms = int((loop.time() - (deadline - timeout)) * 1000)
                    logger.info("[%s] Ollama ready at %s (%dms)", self.lane_id, url, elapsed_ms)
                    return True
            except httpx.HTTPError:
                pass
            await asyncio.sleep(delay)
            delay = min(delay * 2, 2.0)
        return False

    async def _ensure_model_available(self, model: str) -> None:
        """Check if a model is downloaded; pull it if missing.

        This is a blocking call that waits for the download to complete.
        On shared storage (e.g. Ceph), the model may already be present
        from another node, so the pull is skipped entirely.
        """
        available = await self.get_available_models()
        available_names = {m.get("name", "").split(":")[0] for m in available}
        # Also include full name:tag for exact matching
        available_names |= {m.get("name", "") for m in available}

        model_base = model.split(":")[0]
        if model in available_names or model_base in available_names:
            logger.info("[%s] Model '%s' already available on disk — skipping pull", self.lane_id, model)
            return

        logger.info(
            "[%s] Model '%s' not found locally — pulling (timeout=%ds)",
            self.lane_id, model, _PULL_TIMEOUT,
        )
        try:
            resp = await self._http.post(
                f"{self._ollama_url()}/api/pull",
                json={"name": model, "stream": False},
                timeout=_PULL_TIMEOUT,
            )
            if resp.status_code == 200:
                logger.info("[%s] Model '%s' pulled successfully", self.lane_id, model)
            else:
                logger.error(
                    "[%s] Model pull failed (status=%d): %s",
                    self.lane_id, resp.status_code, resp.text[:500],
                )
        except httpx.TimeoutException:
            logger.error(
                "[%s] Model pull for '%s' timed out after %ds",
                self.lane_id, model, _PULL_TIMEOUT,
            )
        except httpx.HTTPError as e:
            logger.error("[%s] Model pull for '%s' failed: %s", self.lane_id, model, e)

    async def _preload_model(self, model: str) -> None:
        logger.info("[%s] Preloading model '%s'...", self.lane_id, model)
        ok = await self.preload_model(model)
        if ok:
            logger.info("[%s] Model '%s' preloaded", self.lane_id, model)
        else:
            logger.warning("[%s] Failed to preload model '%s'", self.lane_id, model)

    def _preload_done_callback(self, task: asyncio.Task) -> None:
        if task in self._preload_tasks:
            self._preload_tasks.remove(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error("[%s] Preload task failed: %s", self.lane_id, exc, exc_info=exc)
