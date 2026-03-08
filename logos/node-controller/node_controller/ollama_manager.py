"""
Ollama Docker container lifecycle manager.

Manages exactly ONE Ollama container — create, start, stop, restart,
recreate (with new config), and destroy.  Uses the Docker SDK to
interact with the Docker daemon via the mounted socket.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, AsyncIterator

import docker
import docker.errors
import httpx
from docker.models.containers import Container
from docker.types import DeviceRequest

from node_controller.models import ContainerState, ContainerStatus, OllamaConfig

logger = logging.getLogger("node_controller.ollama_manager")

_READY_TIMEOUT = 60        # seconds to wait for Ollama to be ready (create)
_START_TIMEOUT = 30        # seconds to wait after start/restart
_PRELOAD_TIMEOUT = 120     # seconds per model preload
_STOP_TIMEOUT = 15         # seconds for graceful stop


class OllamaManager:
    """Manages the lifecycle of a single Ollama Docker container."""

    def __init__(self, network_name: str, volume_name: str, models_host_path: str | None = None) -> None:
        self._client: docker.DockerClient | None = None
        self._network_name = network_name
        self._volume_name = volume_name
        self._models_host_path = models_host_path
        self._http: httpx.AsyncClient | None = None
        self._preload_tasks: list[asyncio.Task] = []  # tracked for clean shutdown
        self._reconfigure_lock = asyncio.Lock()  # prevents concurrent recreate races

    # ------------------------------------------------------------------
    # Initialisation & teardown
    # ------------------------------------------------------------------

    async def init(self) -> None:
        """Connect to Docker daemon and prepare the shared httpx client."""
        loop = asyncio.get_running_loop()
        self._client = await loop.run_in_executor(
            None, docker.from_env
        )
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)
        )
        logger.info("Docker client connected (server %s)", self._client.version().get("Version", "?"))

        # Ensure the shared network exists
        await loop.run_in_executor(None, self._ensure_network)

    async def close(self) -> None:
        """Cancel in-flight preloads and release Docker and HTTP clients."""
        # Cancel any running preload tasks
        for task in self._preload_tasks:
            if not task.done():
                task.cancel()
        if self._preload_tasks:
            await asyncio.gather(*self._preload_tasks, return_exceptions=True)
            self._preload_tasks.clear()

        if self._http:
            await self._http.aclose()
            self._http = None
        if self._client:
            self._client.close()
            self._client = None

    # ------------------------------------------------------------------
    # Container lifecycle
    # ------------------------------------------------------------------

    async def create(self, config: OllamaConfig) -> ContainerStatus:
        """
        Create and start a new Ollama container from the provided config.

        If a container with the same name already exists, it is removed first.
        """
        loop = asyncio.get_running_loop()

        # Remove any existing container with this name
        existing = await self._find_container(config.container_name)
        if existing is not None:
            logger.info("Removing existing container '%s' before create", config.container_name)
            await loop.run_in_executor(None, lambda: existing.remove(force=True))

        env = self._build_env(config)
        device_requests = self._build_device_requests(config)

        gpu_mode = "GPU" if device_requests else "CPU-only"
        effective_parallel = config.max_num_parallel if config.max_num_parallel > 0 else config.num_parallel
        logger.info(
            "Creating Ollama container '%s' (image=%s, port=%d, "
            "num_parallel=%d, max_num_parallel=%d, effective=%d, %s)",
            config.container_name,
            config.image,
            config.host_port,
            config.num_parallel,
            config.max_num_parallel,
            effective_parallel,
            gpu_mode,
        )

        models_source = self._models_host_path or self._volume_name
        volumes = {
            models_source: {
                "bind": config.models_path,
                "mode": "rw",
            }
        }

        if config.use_host_binary:
            # Thin-container mode: mount the host Ollama binary and CUDA libs.
            # The host binary prefers cuda_v12 (~7s cold start) vs the Docker
            # image's cuda_v13 (~80s on compute-capability 7.5 GPUs).
            image = config.base_image
            volumes[config.host_binary_path] = {
                "bind": config.host_binary_path,
                "mode": "ro",
            }
            volumes[config.host_lib_path] = {
                "bind": config.host_lib_path,
                "mode": "ro",
            }
            command = f"{config.host_binary_path} serve"
            logger.info(
                "Host-binary mode: mounting %s and %s from host",
                config.host_binary_path,
                config.host_lib_path,
            )
        else:
            image = config.image
            command = None  # use image's default entrypoint + CMD

        run_kwargs: dict[str, Any] = dict(
            image=image,
            name=config.container_name,
            detach=True,
            environment=env,
            ports={f"{config.container_port}/tcp": config.host_port},
            volumes=volumes,
            network=self._network_name,
            restart_policy={"Name": "unless-stopped"},
        )
        if command is not None:
            run_kwargs["command"] = command
        if device_requests:
            run_kwargs["device_requests"] = device_requests

        container: Container = await loop.run_in_executor(
            None,
            lambda: self._client.containers.run(**run_kwargs),  # type: ignore[union-attr]
        )

        logger.info("Container '%s' created (id=%s)", config.container_name, container.short_id)

        # Wait for Ollama API to be ready
        ready = await self._wait_for_ready(config, timeout=_READY_TIMEOUT)
        if not ready:
            logger.warning("Ollama container did not become ready within %ds", _READY_TIMEOUT)

        # Fire-and-forget preloads — tracked for clean shutdown
        if config.preload_models:
            task = asyncio.create_task(
                self._preload_models(config, config.preload_models),
                name=f"preload-{config.container_name}",
            )
            task.add_done_callback(self._preload_done_callback)
            self._preload_tasks.append(task)

        return await self.status(config.container_name)

    async def start(self, container_name: str) -> ContainerStatus:
        """Start a stopped container."""
        container = await self._get_container(container_name)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, container.start)
        logger.info("Container '%s' started", container_name)
        return await self.status(container_name)

    async def stop(self, container_name: str) -> ContainerStatus:
        """Gracefully stop a running container."""
        container = await self._get_container(container_name)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, lambda: container.stop(timeout=_STOP_TIMEOUT))
        logger.info("Container '%s' stopped", container_name)
        return await self.status(container_name)

    async def restart(self, container_name: str) -> ContainerStatus:
        """Restart the container without changing config."""
        container = await self._get_container(container_name)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, lambda: container.restart(timeout=_STOP_TIMEOUT))
        logger.info("Container '%s' restarted", container_name)

        # Wait for ready after restart
        from node_controller.config import get_config
        cfg = get_config()
        await self._wait_for_ready(cfg.ollama, timeout=_START_TIMEOUT)

        return await self.status(container_name)

    async def recreate(self, config: OllamaConfig) -> ContainerStatus:
        """
        Destroy the current container and create a new one with updated config.
        This is the core "restart with different parameters" operation.

        Protected by an asyncio.Lock to prevent two concurrent reconfigure
        calls from racing on container remove → create.
        """
        async with self._reconfigure_lock:
            logger.info("Recreating container '%s' with new configuration", config.container_name)
            existing = await self._find_container(config.container_name)
            if existing is not None:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, lambda: existing.remove(force=True))
            return await self.create(config)

    async def destroy(self, container_name: str) -> None:
        """Force-remove the container."""
        container = await self._find_container(container_name)
        if container is not None:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, lambda: container.remove(force=True))
            logger.info("Container '%s' destroyed", container_name)
        else:
            logger.info("Container '%s' not found — nothing to destroy", container_name)

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    async def status(self, container_name: str) -> ContainerStatus:
        """Get the current status of the managed container."""
        container = await self._find_container(container_name)
        if container is None:
            return ContainerStatus(
                state=ContainerState.NOT_FOUND,
                container_name=container_name,
            )

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, container.reload)

        state_str = container.status  # "running", "exited", "restarting", etc.
        state = self._map_state(state_str)

        started_at: datetime | None = None
        uptime: float | None = None
        attrs: dict[str, Any] = container.attrs or {}
        state_info = attrs.get("State", {})

        if started_str := state_info.get("StartedAt"):
            try:
                started_at = datetime.fromisoformat(started_str.replace("Z", "+00:00"))
                if state == ContainerState.RUNNING:
                    uptime = (datetime.now(timezone.utc) - started_at).total_seconds()
            except (ValueError, TypeError):
                pass

        return ContainerStatus(
            state=state,
            container_name=container_name,
            container_id=container.short_id,
            uptime_seconds=uptime,
            started_at=started_at,
            error_message=state_info.get("Error") or None,
        )

    # ------------------------------------------------------------------
    # Model operations (via Ollama HTTP API on the container)
    # ------------------------------------------------------------------

    async def unload_model(self, config: OllamaConfig, model_name: str) -> bool:
        """Unload a model from VRAM by setting keep_alive to 0."""
        url = self._ollama_url(config)
        try:
            resp = await self._http.post(  # type: ignore[union-attr]
                f"{url}/api/generate",
                json={"model": model_name, "keep_alive": 0},
                timeout=30.0,
            )
            return resp.status_code == 200
        except httpx.HTTPError as e:
            logger.warning("Failed to unload model '%s': %s", model_name, e)
            return False

    async def preload_model(self, config: OllamaConfig, model_name: str) -> bool:
        """Preload a model into VRAM."""
        url = self._ollama_url(config)
        try:
            resp = await self._http.post(  # type: ignore[union-attr]
                f"{url}/api/generate",
                json={"model": model_name},
                timeout=_PRELOAD_TIMEOUT,
            )
            return resp.status_code == 200
        except httpx.HTTPError as e:
            logger.warning("Failed to preload model '%s': %s", model_name, e)
            return False

    async def pull_model(self, config: OllamaConfig, model_name: str) -> bool:
        """Pull (download) a model. This can take a long time."""
        url = self._ollama_url(config)
        try:
            resp = await self._http.post(  # type: ignore[union-attr]
                f"{url}/api/pull",
                json={"name": model_name, "stream": False},
                timeout=600.0,  # models can be large
            )
            return resp.status_code == 200
        except httpx.HTTPError as e:
            logger.warning("Failed to pull model '%s': %s", model_name, e)
            return False

    async def delete_model(self, config: OllamaConfig, model_name: str) -> bool:
        """Delete a model from disk."""
        url = self._ollama_url(config)
        try:
            resp = await self._http.request(  # type: ignore[union-attr]
                "DELETE",
                f"{url}/api/delete",
                json={"name": model_name},
                timeout=30.0,
            )
            return resp.status_code == 200
        except httpx.HTTPError as e:
            logger.warning("Failed to delete model '%s': %s", model_name, e)
            return False

    async def create_model(
        self, config: OllamaConfig, name: str, modelfile: str
    ) -> bool:
        """Create a model variant from a Modelfile specification.

        This enables per-model customization (num_ctx, temperature, system
        prompt, etc.) without restarting the container.
        """
        url = self._ollama_url(config)
        try:
            resp = await self._http.post(  # type: ignore[union-attr]
                f"{url}/api/create",
                json={"name": name, "modelfile": modelfile, "stream": False},
                timeout=600.0,  # creating can involve quantization
            )
            return resp.status_code == 200
        except httpx.HTTPError as e:
            logger.warning("Failed to create model '%s': %s", name, e)
            return False

    async def copy_model(
        self, config: OllamaConfig, source: str, destination: str
    ) -> bool:
        """Copy a model under a new name (fast — just creates a manifest link)."""
        url = self._ollama_url(config)
        try:
            resp = await self._http.post(  # type: ignore[union-attr]
                f"{url}/api/copy",
                json={"source": source, "destination": destination},
                timeout=30.0,
            )
            return resp.status_code == 200
        except httpx.HTTPError as e:
            logger.warning("Failed to copy '%s' → '%s': %s", source, destination, e)
            return False

    async def show_model(
        self, config: OllamaConfig, model_name: str
    ) -> dict[str, Any] | None:
        """Get detailed model information (Modelfile, parameters, template, etc.)."""
        url = self._ollama_url(config)
        try:
            resp = await self._http.post(  # type: ignore[union-attr]
                f"{url}/api/show",
                json={"name": model_name},
                timeout=30.0,
            )
            if resp.status_code == 200:
                return resp.json()
            return None
        except httpx.HTTPError as e:
            logger.warning("Failed to show model '%s': %s", model_name, e)
            return None

    async def pull_model_streaming(
        self, config: OllamaConfig, model_name: str
    ) -> AsyncIterator[dict[str, Any]]:
        """Pull a model with streaming progress updates.

        Yields dicts like:
            {"status": "pulling abc123...", "completed": 1234, "total": 5678}
        """
        url = self._ollama_url(config)
        async with self._http.stream(  # type: ignore[union-attr]
            "POST",
            f"{url}/api/pull",
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

    def _ensure_network(self) -> None:
        """Create the Docker bridge network if it doesn't exist."""
        assert self._client is not None
        try:
            self._client.networks.get(self._network_name)
        except docker.errors.NotFound:
            self._client.networks.create(self._network_name, driver="bridge")
            logger.info("Created Docker network '%s'", self._network_name)

    async def _find_container(self, name: str) -> Container | None:
        """Find a container by name, or None if it doesn't exist."""
        assert self._client is not None
        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(
                None, lambda: self._client.containers.get(name)  # type: ignore[union-attr]
            )
        except docker.errors.NotFound:
            return None

    async def _get_container(self, name: str) -> Container:
        """Find a container by name or raise."""
        container = await self._find_container(name)
        if container is None:
            raise ValueError(f"Container '{name}' not found")
        return container

    @staticmethod
    def _build_env(config: OllamaConfig) -> dict[str, str]:
        """Build the environment variables dict for the Ollama container."""
        # Use max_num_parallel (the process ceiling) for the actual env var.
        # When max_num_parallel is 0 (auto), fall back to num_parallel.
        effective_parallel = config.max_num_parallel if config.max_num_parallel > 0 else config.num_parallel
        env = {
            "OLLAMA_NUM_PARALLEL": str(effective_parallel),
            "OLLAMA_MAX_LOADED_MODELS": str(config.max_loaded_models),
            "OLLAMA_KEEP_ALIVE": config.keep_alive,
            "OLLAMA_MAX_QUEUE": str(config.max_queue),
            "OLLAMA_CONTEXT_LENGTH": str(config.context_length),
            "OLLAMA_HOST": f"0.0.0.0:{config.container_port}",
            "OLLAMA_MODELS": config.models_path,
        }
        if config.flash_attention:
            env["OLLAMA_FLASH_ATTENTION"] = "1"
        if config.kv_cache_type != "f16":
            env["OLLAMA_KV_CACHE_TYPE"] = config.kv_cache_type
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
        # Merge user-provided overrides last (takes precedence over everything)
        env.update(config.env_overrides)
        return env

    @staticmethod
    def _build_device_requests(config: OllamaConfig) -> list[DeviceRequest]:
        """Build GPU device requests for the container.

        Returns an empty list when gpu_devices is 'none' (CPU-only mode),
        which omits the device_requests kwarg from containers.run entirely.
        """
        if config.gpu_devices.lower() == "none":
            return []
        if config.gpu_devices == "all":
            return [DeviceRequest(count=-1, capabilities=[["gpu"]])]
        # Specific device IDs
        device_ids = [d.strip() for d in config.gpu_devices.split(",")]
        return [DeviceRequest(device_ids=device_ids, capabilities=[["gpu"]])]

    @staticmethod
    def _map_state(docker_state: str) -> ContainerState:
        mapping = {
            "running": ContainerState.RUNNING,
            "exited": ContainerState.STOPPED,
            "dead": ContainerState.STOPPED,
            "paused": ContainerState.STOPPED,
            "restarting": ContainerState.RESTARTING,
            "created": ContainerState.CREATING,
        }
        return mapping.get(docker_state, ContainerState.ERROR)

    @staticmethod
    def _ollama_url(config: OllamaConfig) -> str:
        """Construct the Ollama API URL via the container name on the Docker network."""
        return f"http://{config.container_name}:{config.container_port}"

    async def _wait_for_ready(
        self, config: OllamaConfig, timeout: int = _READY_TIMEOUT
    ) -> bool:
        """Poll /api/version with exponential backoff until Ollama responds."""
        url = self._ollama_url(config)
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        delay = 0.1  # start at 100ms — Ollama often boots in <500ms
        while loop.time() < deadline:
            try:
                resp = await self._http.get(f"{url}/api/version", timeout=5.0)  # type: ignore[union-attr]
                if resp.status_code == 200:
                    elapsed_ms = int((loop.time() - (deadline - timeout)) * 1000)
                    logger.info("Ollama ready at %s (%dms)", url, elapsed_ms)
                    return True
            except httpx.HTTPError:
                pass
            await asyncio.sleep(delay)
            delay = min(delay * 2, 2.0)  # cap at 2s
        return False

    async def _preload_models(self, config: OllamaConfig, models: list[str]) -> None:
        """Preload models into VRAM concurrently.

        Ollama handles concurrent load requests via its internal queue,
        so we fire all requests in parallel and let it schedule them.
        This is faster than sequential when multiple models fit in VRAM.
        """
        async def _load_one(model: str) -> None:
            logger.info("Preloading model '%s'…", model)
            ok = await self.preload_model(config, model)
            if ok:
                logger.info("Model '%s' preloaded", model)
            else:
                logger.warning("Failed to preload model '%s'", model)

        await asyncio.gather(*[_load_one(m) for m in models])

    def _preload_done_callback(self, task: asyncio.Task) -> None:  # type: ignore[type-arg]
        """Log exceptions from fire-and-forget preload tasks and clean up."""
        if task in self._preload_tasks:
            self._preload_tasks.remove(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error("Preload task failed: %s", exc, exc_info=exc)
