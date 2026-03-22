"""
vLLM process handle — manages a single vLLM server subprocess.

vLLM uses continuous batching — no fixed ``num_parallel``.  It handles
arbitrary concurrency dynamically and exposes an OpenAI-compatible API
at ``/v1/completions``, ``/v1/chat/completions``, and ``/v1/models``.

Key differences from Ollama:
- No model pull/push/delete — model is specified at launch time and must
  exist locally (HuggingFace cache or explicit path).
- No ``num_parallel`` — continuous batching handles all concurrency.
- ``num_ctx`` equivalent is ``--max-model-len``.
- GPU pinning via ``CUDA_VISIBLE_DEVICES`` or ``--tensor-parallel-size``.
- Optional stability controls are exposed via lane config:
  ``disable_custom_all_reduce`` and ``disable_nccl_p2p``.
"""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime
import logging
import os
import shutil
import signal
import sys
import urllib.parse
from pathlib import Path
from typing import Any, AsyncIterator

import httpx

from logos_worker_node.models import LaneConfig, OllamaConfig, ProcessState, ProcessStatus

logger = logging.getLogger("logos_worker_node.vllm_process")

_READY_TIMEOUT = 300  # vLLM startup can be slow (model download + compilation)
_STOP_TIMEOUT = 15
_STARTUP_LOG_TAIL_LINES = 8
_STARTUP_LOG_TAIL_MAX_CHARS = 1200


class VllmProcessHandle:
    """Manages a single vLLM server process on a specific port."""

    def __init__(self, lane_id: str, port: int, global_config: OllamaConfig) -> None:
        self.lane_id = lane_id
        self.port = port
        self._global_config = global_config
        self._lane_config: LaneConfig | None = None
        self._process: asyncio.subprocess.Process | None = None
        self._http: httpx.AsyncClient | None = None
        self._log_task: asyncio.Task | None = None
        self._recent_logs: deque[str] = deque(maxlen=200)
        self._stuck_vram: bool = False
        self._known_child_pids: set[int] = set()
        self._process_group_id: int | None = None

    async def init(self) -> None:
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=60.0, write=10.0, pool=5.0)
        )

    async def close(self) -> None:
        if self._http:
            await self._http.aclose()
            self._http = None

    # ------------------------------------------------------------------
    # Process lifecycle
    # ------------------------------------------------------------------

    async def spawn(self, lane_config: LaneConfig) -> ProcessStatus:
        """Spawn the vLLM process for this lane."""
        if self._process is not None and self._process.returncode is None:
            logger.info("[%s] Stopping existing process (pid=%d) before spawn", self.lane_id, self._process.pid)
            await self._kill_process()

        self._recent_logs.clear()
        self._lane_config = lane_config
        cmd = self._build_cmd(lane_config)
        self._require_c_compiler()
        self._require_nvcc(lane_config)
        env = self._build_env(lane_config)

        logger.info(
            "[%s] Spawning vLLM (port=%d, model=%s)",
            self.lane_id, self.port, lane_config.model,
        )

        process_env = {**os.environ, **env}
        # Keep helper tools from the same virtualenv (for example `ninja`
        # used by FlashInfer JIT) available even when the venv is not activated.
        vllm_bin_dir = str(Path(cmd[0]).resolve().parent)
        current_path = process_env.get("PATH", "")
        if vllm_bin_dir:
            process_env["PATH"] = (
                vllm_bin_dir
                if not current_path
                else f"{vllm_bin_dir}{os.pathsep}{current_path}"
            )
        self._process = await asyncio.create_subprocess_exec(
            *cmd,
            env=process_env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,  # Own process group so we can kill the entire TP tree
        )
        # Cache the process group ID so we can kill the whole tree even after
        # the root process exits (os.getpgid would fail on a dead PID).
        self._process_group_id = self._process.pid

        if self._log_task is not None and not self._log_task.done():
            self._log_task.cancel()
        self._log_task = asyncio.create_task(
            self._stream_logs(), name=f"logs-vllm-{self.lane_id}"
        )

        logger.info("[%s] vLLM process spawned (pid=%d)", self.lane_id, self._process.pid)

        ready = await self._wait_for_ready(timeout=_READY_TIMEOUT)
        if not ready:
            failure = self._format_startup_failure(_READY_TIMEOUT)
            logger.error(failure)
            self._persist_failure_logs("startup_failed")
            await self._kill_process()
            raise RuntimeError(failure)

        return self.status()

    async def stop(self) -> ProcessStatus:
        if self._process is None or self._process.returncode is not None:
            return self.status()
        pid = self._process.pid
        await self._kill_process()
        vram_clean = await self._verify_vram_released(pid)
        if not vram_clean:
            logger.error(
                "[%s] VRAM still held after stopping pid=%d — GPU memory may be leaked",
                self.lane_id, pid,
            )
            self._stuck_vram = True
            self._persist_failure_logs("stuck_vram")
        else:
            self._stuck_vram = False
        return self.status()

    @property
    def has_stuck_vram(self) -> bool:
        """True if the last stop detected residual GPU memory."""
        return getattr(self, "_stuck_vram", False)

    async def reconfigure(self, lane_config: LaneConfig) -> ProcessStatus:
        """Reconfigure = full restart for vLLM (model/config change)."""
        logger.info("[%s] Reconfiguring vLLM", self.lane_id)
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
    # Model operations (via OpenAI-compatible API)
    # ------------------------------------------------------------------

    def _base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    async def preload_model(self, model_name: str) -> bool:
        """vLLM loads the model at startup — this is a no-op health check."""
        try:
            resp = await self._http.get(f"{self._base_url()}/v1/models", timeout=10.0)
            return resp.status_code == 200
        except httpx.HTTPError:
            return False

    async def unload_model(self, model_name: str) -> bool:
        """vLLM doesn't support runtime unload — stop the process instead."""
        logger.info("[%s] Unload not supported by vLLM — use stop/destroy", self.lane_id)
        return False

    async def pull_model(self, model_name: str) -> bool:
        """vLLM downloads from HuggingFace at startup — not a separate step."""
        logger.info("[%s] vLLM pulls models at startup — no separate pull", self.lane_id)
        return False

    async def delete_model(self, model_name: str) -> bool:
        logger.info("[%s] Model deletion is a filesystem operation for vLLM", self.lane_id)
        return False

    async def create_model(self, name: str, modelfile: str) -> bool:
        logger.info("[%s] Model creation not supported by vLLM backend", self.lane_id)
        return False

    async def copy_model(self, source: str, destination: str) -> bool:
        logger.info("[%s] Model copy not supported by vLLM backend", self.lane_id)
        return False

    async def show_model(self, model_name: str) -> dict[str, Any] | None:
        """Return model info from vLLM's /v1/models endpoint."""
        try:
            resp = await self._http.get(f"{self._base_url()}/v1/models", timeout=10.0)
            if resp.status_code == 200:
                data = resp.json()
                for m in data.get("data", []):
                    if m.get("id") == model_name:
                        return m
        except httpx.HTTPError as e:
            logger.debug("[%s] Failed to query /v1/models: %s", self.lane_id, e)
        return None

    async def pull_model_streaming(self, model_name: str) -> AsyncIterator[dict[str, Any]]:
        """Not supported by vLLM — yields nothing."""
        logger.info("[%s] Streaming pull not supported by vLLM", self.lane_id)
        return
        yield  # pragma: no cover — makes this an async generator

    async def get_loaded_models(self) -> list[dict[str, Any]]:
        """Query /v1/models for the currently served model."""
        try:
            resp = await self._http.get(f"{self._base_url()}/v1/models", timeout=10.0)
            if resp.status_code == 200:
                data = resp.json()
                models = []
                for m in data.get("data", []):
                    models.append({
                        "name": m.get("id", ""),
                        "size": 0,
                        "size_vram": 0,
                        "details": {"backend": "vllm"},
                    })
                return models
        except httpx.HTTPError as e:
            logger.debug("[%s] Failed to query /v1/models: %s", self.lane_id, e)
        return []

    async def get_version(self) -> str | None:
        """Get vLLM version from the health/version endpoint."""
        try:
            resp = await self._http.get(f"{self._base_url()}/version", timeout=5.0)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("version", "unknown")
        except httpx.HTTPError:
            pass
        # Fallback: check if server is up at all
        try:
            resp = await self._http.get(f"{self._base_url()}/health", timeout=5.0)
            if resp.status_code == 200:
                return "unknown"
        except httpx.HTTPError:
            pass
        return None

    async def get_available_models(self) -> list[dict[str, Any]]:
        """Same as get_loaded_models for vLLM — only one model per process."""
        return await self.get_loaded_models()

    async def get_backend_metrics(self) -> dict[str, Any]:
        metrics = {
            "engine": "vllm",
            "queue_waiting": None,
            "requests_running": None,
            "gpu_cache_usage_percent": None,
            "prefix_cache_hit_rate": None,
            "prompt_tokens_total": None,
            "generation_tokens_total": None,
            "ttft_histogram": {},
        }
        if self._http is None:
            return metrics
        try:
            resp = await self._http.get(f"{self._base_url()}/metrics", timeout=5.0)
            if resp.status_code != 200:
                return metrics
            for raw_line in resp.text.splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                if " " not in line:
                    continue
                name, value_raw = line.split(" ", 1)
                metric_name = name.split("{", 1)[0]
                try:
                    value = float(value_raw.strip())
                except ValueError:
                    continue
                if metric_name.endswith("num_requests_waiting"):
                    metrics["queue_waiting"] = value
                elif metric_name.endswith("num_requests_running"):
                    metrics["requests_running"] = value
                elif metric_name.endswith("gpu_cache_usage_perc") or metric_name.endswith("gpu_cache_usage_percent"):
                    metrics["gpu_cache_usage_percent"] = value * 100.0
                elif metric_name.endswith("prefix_cache_hit_rate"):
                    metrics["prefix_cache_hit_rate"] = value
                elif metric_name.endswith("prompt_tokens_total"):
                    metrics["prompt_tokens_total"] = value
                elif metric_name.endswith("generation_tokens_total"):
                    metrics["generation_tokens_total"] = value
                elif "time_to_first_token_seconds_bucket" in metric_name:
                    bucket = "unknown"
                    if 'le="' in name:
                        bucket = name.split('le="', 1)[1].split('"', 1)[0]
                    metrics["ttft_histogram"][bucket] = value
        except httpx.HTTPError:
            return metrics
        return metrics

    async def sleep(self, level: int = 1, mode: str = "wait") -> dict[str, Any]:
        """Put a vLLM lane into sleep mode."""
        self._ensure_sleep_mode_ready()
        params = urllib.parse.urlencode({"level": str(level), "mode": mode})
        url = f"{self._base_url()}/sleep?{params}"
        try:
            resp = await self._http.post(url, timeout=30.0)
        except httpx.HTTPError as exc:
            raise RuntimeError(f"[{self.lane_id}] Failed to call vLLM /sleep: {exc}") from exc

        payload: dict[str, Any]
        try:
            payload = resp.json() if resp.content else {}
        except ValueError:
            payload = {"raw": resp.text}

        if resp.status_code not in (200, 202):
            raise RuntimeError(
                f"[{self.lane_id}] vLLM /sleep failed with HTTP {resp.status_code}: {payload}"
            )
        return payload

    async def wake_up(self) -> dict[str, Any]:
        """Wake up a sleeping vLLM lane."""
        self._ensure_sleep_mode_ready()
        url = f"{self._base_url()}/wake_up"
        try:
            resp = await self._http.post(url, timeout=30.0)
        except httpx.HTTPError as exc:
            raise RuntimeError(f"[{self.lane_id}] Failed to call vLLM /wake_up: {exc}") from exc

        payload: dict[str, Any]
        try:
            payload = resp.json() if resp.content else {}
        except ValueError:
            payload = {"raw": resp.text}

        if resp.status_code not in (200, 202):
            raise RuntimeError(
                f"[{self.lane_id}] vLLM /wake_up failed with HTTP {resp.status_code}: {payload}"
            )
        return payload

    async def is_sleeping(self) -> bool | None:
        """Return vLLM sleeping state when supported, else None."""
        if (
            self._lane_config is None
            or not self._lane_config.vllm
            or not self._lane_config.vllm_config
            or not self._lane_config.vllm_config.enable_sleep_mode
        ):
            return None
        if self._http is None:
            return None
        try:
            resp = await self._http.get(f"{self._base_url()}/is_sleeping", timeout=5.0)
            if resp.status_code != 200:
                return None
            payload = resp.json()
            value = payload.get("is_sleeping") if isinstance(payload, dict) else None
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)):
                return bool(value)
            return None
        except httpx.HTTPError:
            return None
        except ValueError:
            return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_sleep_mode_ready(self) -> None:
        lc = self._lane_config
        if lc is None or not lc.vllm:
            raise RuntimeError(f"[{self.lane_id}] vLLM lane is not configured")
        if lc.vllm_config is None or not lc.vllm_config.enable_sleep_mode:
            raise RuntimeError(
                f"[{self.lane_id}] Sleep mode is disabled for this lane. "
                "Enable lanes[].vllm=true with lanes[].vllm_config.enable_sleep_mode=true and reconfigure."
            )
        if self._http is None:
            raise RuntimeError(f"[{self.lane_id}] HTTP client is not initialized")

    def _build_cmd(self, lane_config: LaneConfig) -> list[str]:
        """Build the vllm serve command."""
        if not lane_config.vllm_config:
            raise RuntimeError(f"[{self.lane_id}] Missing vllm_config for vLLM lane")
        vc = lane_config.vllm_config
        vllm_binary = self._resolve_vllm_binary(vc.vllm_binary)
        cmd = [
            vllm_binary, "serve", lane_config.model,
            "--host", "0.0.0.0",
            "--port", str(self.port),
            "--tensor-parallel-size", str(vc.tensor_parallel_size),
            "--dtype", vc.dtype,
        ]
        if vc.gpu_memory_utilization is not None:
            cmd.extend(["--gpu-memory-utilization", str(vc.gpu_memory_utilization)])
        elif vc.kv_cache_memory_bytes:
            # When kv_cache_memory_bytes is set, vLLM uses it for KV cache
            # sizing and ignores gpu_memory_utilization for that purpose.
            # However, vLLM v1 still has a startup guard in request_memory()
            # that rejects launch if free VRAM < gpu_memory_utilization * total.
            # Default is 0.9 which fails on shared GPUs. Pass a minimal value
            # to satisfy the guard while letting kv_cache_memory_bytes control
            # actual cache allocation.
            cmd.extend(["--gpu-memory-utilization", "0.1"])
        if vc.max_model_len > 0:
            cmd.extend(["--max-model-len", str(vc.max_model_len)])
        elif lane_config.context_length > 0:
            cmd.extend(["--max-model-len", str(lane_config.context_length)])
        if vc.kv_cache_memory_bytes:
            cmd.extend(["--kv-cache-memory-bytes", vc.kv_cache_memory_bytes])
        if vc.quantization:
            cmd.extend(["--quantization", vc.quantization])
        # ``--enforce-eager`` is both an explicit option and our fallback when
        # flash attention is disabled for the lane.
        if vc.enforce_eager or lane_config.flash_attention is False:
            cmd.append("--enforce-eager")
        if vc.enable_prefix_caching:
            cmd.append("--enable-prefix-caching")
        if vc.disable_custom_all_reduce:
            cmd.append("--disable-custom-all-reduce")
        if vc.enable_sleep_mode:
            cmd.append("--enable-sleep-mode")
        cmd.extend(vc.extra_args)
        return cmd

    def _resolve_vllm_binary(self, configured_binary: str) -> str:
        """Resolve the vLLM CLI executable with actionable fallback order.

        Resolution order:
          1. ``configured_binary`` (absolute/relative path or command name)
          2. ``PATH`` lookup
          3. Sibling executable next to current interpreter (``<venv>/bin/vllm``)
        """
        raw = (configured_binary or "vllm").strip() or "vllm"

        # 1) Configured path (absolute or relative path-like value)
        if os.path.sep in raw or (os.path.altsep and os.path.altsep in raw):
            candidate = os.path.abspath(os.path.expanduser(raw))
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate

        # 2) PATH lookup (configured name first, then fallback 'vllm')
        for cmd_name in (raw, "vllm"):
            found = shutil.which(cmd_name)
            if found:
                return found

        # 3) Active interpreter sibling (works for unactivated virtualenvs)
        venv_sibling = str(Path(sys.executable).resolve().with_name("vllm"))
        if os.path.isfile(venv_sibling) and os.access(venv_sibling, os.X_OK):
            return venv_sibling

        raise FileNotFoundError(
            f"[{self.lane_id}] Could not find vLLM executable. Checked '{raw}', PATH, "
            f"and '{venv_sibling}'. Set lanes[].vllm_config.vllm_binary to an absolute path "
            f"or install vLLM in this interpreter: {sys.executable} -m pip install vllm"
        )

    def _require_c_compiler(self) -> None:
        """Ensure a usable C compiler exists for Triton/FlashInfer JIT paths."""
        raw_cc = (os.environ.get("CC") or "").strip()
        candidates: list[str] = []
        if raw_cc:
            # CC may contain extra flags (e.g. "gcc -m64"); check the binary token.
            candidates.append(raw_cc.split()[0])
        candidates.extend(["cc", "gcc", "clang"])

        checked: list[str] = []
        for candidate in candidates:
            if not candidate:
                continue
            if os.path.sep in candidate or (os.path.altsep and os.path.altsep in candidate):
                path_candidate = os.path.abspath(os.path.expanduser(candidate))
                checked.append(path_candidate)
                if os.path.isfile(path_candidate) and os.access(path_candidate, os.X_OK):
                    return
                continue
            checked.append(candidate)
            if shutil.which(candidate):
                return

        checked_display = ", ".join(checked) if checked else "CC, cc, gcc, clang"
        raise RuntimeError(
            f"[{self.lane_id}] No C compiler found in runtime (checked: {checked_display}). "
            "vLLM/Triton startup may JIT-compile kernels and requires a compiler. "
            "Install build-essential in the node image or set CC to an "
            "absolute compiler path."
        )

    def _require_nvcc(self, lane_config: LaneConfig) -> None:
        """Ensure CUDA toolkit compiler is available for GPU kernel compilation."""
        gpu_devices = lane_config.gpu_devices if lane_config.gpu_devices else self._global_config.gpu_devices
        if (gpu_devices or "").lower() == "none":
            return

        if shutil.which("nvcc"):
            return

        cuda_home_env = (os.environ.get("CUDA_HOME") or "").strip()
        candidates: list[str] = []
        if cuda_home_env:
            candidates.append(os.path.join(cuda_home_env, "bin", "nvcc"))
        for root in ("/usr/local/cuda", "/usr/local/cuda-12.8", "/usr/local/cuda-12"):
            candidates.append(os.path.join(root, "bin", "nvcc"))

        checked: list[str] = []
        for candidate in candidates:
            checked.append(candidate)
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return

        checked_display = ", ".join(dict.fromkeys(checked))
        raise RuntimeError(
            f"[{self.lane_id}] CUDA toolkit compiler 'nvcc' not found "
            f"(checked PATH and: {checked_display}). "
            "This GPU lane requires CUDA toolkit visibility inside the controller runtime. "
            "Mount /usr/local/cuda into the container and/or set CUDA_HOME so "
            "<CUDA_HOME>/bin/nvcc exists."
        )

    def _build_env(self, lane_config: LaneConfig) -> dict[str, str]:
        """Build environment variables for this lane's vLLM process."""
        gc = self._global_config
        env: dict[str, str] = {}

        # GPU device pinning
        gpu_devices = lane_config.gpu_devices if lane_config.gpu_devices else gc.gpu_devices
        if gpu_devices.lower() not in ("all", "none", ""):
            env["CUDA_VISIBLE_DEVICES"] = gpu_devices
        elif gpu_devices.lower() == "none":
            env["CUDA_VISIBLE_DEVICES"] = ""

        # CUDA toolkit — FlashInfer JIT needs nvcc.  Detect common paths.
        if "CUDA_HOME" not in os.environ:
            for candidate in ("/usr/local/cuda", "/usr/local/cuda-12.8", "/usr/local/cuda-12"):
                if os.path.isdir(candidate):
                    env["CUDA_HOME"] = candidate
                    break

        # HuggingFace cache — use same location as Ollama models for consistency
        # (though vLLM uses HF format, not GGUF)
        if "HF_HOME" not in os.environ:
            env["HF_HOME"] = self._resolve_hf_home(gc.models_path)

        if lane_config.vllm_config is None:
            raise RuntimeError(f"[{self.lane_id}] Missing vllm_config for vLLM lane")
        vc = lane_config.vllm_config
        if vc.server_dev_mode:
            env["VLLM_SERVER_DEV_MODE"] = "1"
        if vc.disable_nccl_p2p:
            env["NCCL_P2P_DISABLE"] = "1"

        # NCCL safety defaults for tensor-parallel lanes (TP > 1).
        # These prevent NCCL hangs from cascading into driver crashes.
        # Each can be overridden by the host environment or disable_nccl_p2p config.
        if vc.tensor_parallel_size > 1:
            env.setdefault("NCCL_P2P_DISABLE", "1")
            env.setdefault("NCCL_ASYNC_ERROR_HANDLING", "1")
            env.setdefault("NCCL_CUMEM_ENABLE", "0")

        return env

    def _resolve_hf_home(self, models_path: str) -> str:
        """Pick a writable HuggingFace cache path for vLLM downloads.

        Preferred path is ``<models_path>/.hf_cache`` to keep model artifacts
        close to the Ollama storage. If that path is not writable for the
        current user, fall back to ``~/.cache/huggingface``.
        """
        preferred = Path(models_path).expanduser() / ".hf_cache" if models_path else None
        fallback = Path.home() / ".cache" / "huggingface"
        candidates = [p for p in (preferred, fallback) if p is not None]

        for candidate in candidates:
            parent = candidate.parent
            try:
                parent.mkdir(parents=True, exist_ok=True)
                candidate.mkdir(parents=True, exist_ok=True)
            except OSError:
                continue
            if os.access(str(candidate), os.W_OK | os.X_OK):
                if preferred is not None and candidate != preferred:
                    logger.warning(
                        "[%s] Preferred HF cache '%s' not writable, falling back to '%s'",
                        self.lane_id,
                        preferred,
                        candidate,
                    )
                return str(candidate)

        logger.warning(
            "[%s] Could not verify writable HF cache path, using '%s'",
            self.lane_id,
            fallback,
        )
        return str(fallback)

    async def _kill_process(self) -> None:
        if self._process is None or self._process.returncode is not None:
            return
        pid = self._process.pid
        pgid = self._process_group_id
        logger.info("[%s] Stopping vLLM process (pid=%d, pgid=%s)", self.lane_id, pid, pgid)
        if self._log_task is not None and not self._log_task.done():
            self._log_task.cancel()

        # Phase 1: SIGTERM the entire process group (kills TP workers too)
        if pgid is not None:
            try:
                os.killpg(pgid, signal.SIGTERM)
            except (ProcessLookupError, OSError):
                try:
                    self._process.send_signal(signal.SIGTERM)
                except ProcessLookupError:
                    self._process_group_id = None
                    return
        else:
            try:
                self._process.send_signal(signal.SIGTERM)
            except ProcessLookupError:
                return

        # Phase 2: Wait for the root process to exit
        try:
            await asyncio.wait_for(self._process.wait(), timeout=_STOP_TIMEOUT)
            logger.info("[%s] vLLM process (pid=%d) exited gracefully", self.lane_id, pid)
        except asyncio.TimeoutError:
            logger.warning("[%s] vLLM (pid=%d) did not exit in %ds — SIGKILL", self.lane_id, pid, _STOP_TIMEOUT)
            # Phase 3: SIGKILL the entire process group
            if pgid is not None:
                try:
                    os.killpg(pgid, signal.SIGKILL)
                except (ProcessLookupError, OSError):
                    try:
                        self._process.kill()
                    except ProcessLookupError:
                        pass
            else:
                try:
                    self._process.kill()
                except ProcessLookupError:
                    pass
            try:
                await self._process.wait()
            except ProcessLookupError:
                pass

        self._process_group_id = None

        # Phase 4: Sweep for any orphaned descendants still holding GPU memory
        await self._kill_descendant_processes(pid)

    async def _kill_descendant_processes(self, root_pid: int) -> None:
        """Kill any remaining child processes that survived process-group kill.

        With TP>1 vLLM spawns worker subprocesses. If the process-group kill
        missed any (e.g. they re-parented to init), walk /proc to find and
        kill them.  This is a best-effort safety net.
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "pgrep", "-P", str(root_pid),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
        except (FileNotFoundError, asyncio.TimeoutError, OSError):
            return

        if not stdout:
            return

        child_pids = []
        for line in stdout.decode("utf-8", errors="replace").splitlines():
            line = line.strip()
            if line.isdigit():
                child_pids.append(int(line))

        for cpid in child_pids:
            try:
                os.kill(cpid, signal.SIGKILL)
                logger.warning(
                    "[%s] Killed orphaned descendant pid=%d of root pid=%d",
                    self.lane_id, cpid, root_pid,
                )
            except (ProcessLookupError, OSError):
                pass

    async def _verify_vram_released(
        self, pid: int, timeout: float = 10.0, poll_interval: float = 1.0,
    ) -> bool:
        """Poll nvidia-smi to confirm the killed process no longer holds VRAM.

        Returns True if VRAM is clean, False if memory is still pinned after
        *timeout* seconds.  This catches the common failure mode where the
        process exits but CUDA contexts remain in the driver.
        """
        deadline = asyncio.get_event_loop().time() + timeout
        # Collect known child PIDs to also watch for
        check_pids = {pid} | self._known_child_pids

        while asyncio.get_event_loop().time() < deadline:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "nvidia-smi",
                    "--query-compute-apps=pid,used_memory",
                    "--format=csv,noheader,nounits",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
            except (FileNotFoundError, asyncio.TimeoutError, OSError):
                return True  # Can't verify — assume clean

            if proc.returncode != 0:
                return True  # nvidia-smi failed — can't verify

            found_leaked = False
            for raw_line in stdout.decode("utf-8", errors="replace").splitlines():
                line = raw_line.strip()
                if not line or "," not in line:
                    continue
                pid_str = line.split(",", 1)[0].strip()
                if pid_str.isdigit() and int(pid_str) in check_pids:
                    found_leaked = True
                    break

            if not found_leaked:
                return True

            await asyncio.sleep(poll_interval)

        logger.warning(
            "[%s] VRAM still held by pid(s) %s after %.0fs — stuck CUDA context detected",
            self.lane_id, check_pids, timeout,
        )
        return False

    async def _stream_logs(self) -> None:
        if self._process is None or self._process.stdout is None:
            return
        try:
            async for line_bytes in self._process.stdout:
                line = line_bytes.decode("utf-8", errors="replace").rstrip()
                if line:
                    self._recent_logs.append(line)
                    logger.info("[vllm:%s] %s", self.lane_id, line)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.debug("[%s] vLLM log streaming ended", self.lane_id, exc_info=True)

    def _recent_log_tail(self) -> str:
        if not self._recent_logs:
            return ""
        tail_lines = list(self._recent_logs)[-_STARTUP_LOG_TAIL_LINES:]
        compact = " | ".join(line.strip() for line in tail_lines if line.strip())
        if len(compact) > _STARTUP_LOG_TAIL_MAX_CHARS:
            compact = compact[-_STARTUP_LOG_TAIL_MAX_CHARS:]
        return compact

    def _startup_hint(self) -> str:
        if not self._recent_logs:
            return ""
        log_blob = "\n".join(self._recent_logs).lower()
        if "failed to find c compiler" in log_blob:
            return (
                "Detected missing C compiler during vLLM startup. "
                "Install build-essential (gcc/g++/make) in the runtime image."
            )
        return ""

    def _persist_failure_logs(self, reason: str) -> None:
        """Write recent vLLM logs to disk for post-mortem debugging."""
        if not self._recent_logs:
            return
        try:
            log_dir = Path("/tmp/logos-vllm-logs")
            log_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = log_dir / f"{self.lane_id}_{timestamp}_{reason}.log"
            path.write_text("\n".join(self._recent_logs), encoding="utf-8")
            logger.info("[%s] Failure logs saved to %s", self.lane_id, path)
        except OSError:
            logger.debug("[%s] Could not persist failure logs", self.lane_id, exc_info=True)

    def _format_startup_failure(self, timeout_s: int) -> str:
        status = self.status()
        if status.state == ProcessState.STOPPED and status.return_code is not None:
            base = (
                f"[{self.lane_id}] vLLM exited during startup "
                f"(port={self.port}, return_code={status.return_code})"
            )
        else:
            base = (
                f"[{self.lane_id}] vLLM did not become ready within {timeout_s}s "
                f"(port={self.port}, state={status.state.value}, return_code={status.return_code})"
            )
        hint = self._startup_hint()
        tail = self._recent_log_tail()
        if hint and tail:
            return f"{base}. {hint} Recent logs: {tail}"
        if hint:
            return f"{base}. {hint}"
        if tail:
            return f"{base}. Recent logs: {tail}"
        return base

    async def _wait_for_ready(self, timeout: int = _READY_TIMEOUT) -> bool:
        """Wait for vLLM's health endpoint to respond."""
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        delay = 0.5  # vLLM is slower to start than Ollama
        while loop.time() < deadline:
            if self._process is not None and self._process.returncode is not None:
                logger.error(
                    "[%s] vLLM exited with code %d during startup",
                    self.lane_id, self._process.returncode,
                )
                return False
            try:
                resp = await self._http.get(f"{self._base_url()}/health", timeout=5.0)
                if resp.status_code == 200:
                    elapsed_ms = int((loop.time() - (deadline - timeout)) * 1000)
                    logger.info("[%s] vLLM ready at port %d (%dms)", self.lane_id, self.port, elapsed_ms)
                    return True
            except httpx.HTTPError:
                pass
            await asyncio.sleep(delay)
            delay = min(delay * 1.5, 5.0)
        return False
