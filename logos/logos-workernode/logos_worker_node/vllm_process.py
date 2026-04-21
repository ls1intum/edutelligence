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
- Optional stability controls: ``disable_custom_all_reduce`` (per-lane)
  and ``nccl_p2p_available`` (global engine config, default False).
"""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime
import logging
import os
import shutil
import signal
import subprocess
import sys
import urllib.parse
from pathlib import Path
from typing import Any, AsyncIterator

import httpx

from logos_worker_node.models import (
    LaneConfig,
    OllamaConfig,
    ProcessState,
    ProcessStatus,
    VllmEngineConfig,
)

logger = logging.getLogger("logos_worker_node.vllm_process")

_READY_TIMEOUT = 300  # vLLM startup can be slow (model download + compilation)
_STOP_TIMEOUT = 15
_STARTUP_LOG_TAIL_LINES = 8
_STARTUP_LOG_TAIL_MAX_CHARS = 1200
_SCRUBBED_ENV_VARS = (
    "LOCAL_RANK",
    "RANK",
    "WORLD_SIZE",
    "LOCAL_WORLD_SIZE",
    "NODE_RANK",
    "MASTER_ADDR",
    "MASTER_PORT",
)


class VllmProcessHandle:
    """Manages a single vLLM server process on a specific port."""

    def __init__(
        self,
        lane_id: str,
        port: int,
        global_config: OllamaConfig,
        vllm_engine_config: VllmEngineConfig | None = None,
    ) -> None:
        self.lane_id = lane_id
        self.port = port
        self._global_config = global_config
        self._vllm_engine_config = vllm_engine_config or VllmEngineConfig()
        self._lane_config: LaneConfig | None = None
        self._process: asyncio.subprocess.Process | None = None
        self._http: httpx.AsyncClient | None = None
        self._log_task: asyncio.Task | None = None
        self._recent_logs: deque[str] = deque(maxlen=200)
        self._stuck_vram: bool = False
        self._known_child_pids: set[int] = set()
        self._process_group_id: int | None = None
        self.hf_home_override: str | None = None

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

        process_env = self._build_process_env(lane_config, env, cmd)
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

        # Discover TP worker child PIDs so _verify_vram_released can track them
        self._known_child_pids = await self._discover_child_pids(self._process.pid)
        if self._known_child_pids:
            logger.info(
                "[%s] Discovered %d child PIDs for TP workers: %s",
                self.lane_id, len(self._known_child_pids), self._known_child_pids,
            )

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
            resp = await self._http.post(url, timeout=120.0)
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
            resp = await self._http.post(url, timeout=120.0)
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
        vllm_prefix = self._resolve_vllm_binary(vc.vllm_binary)
        cmd = [
            *vllm_prefix, "serve", lane_config.model,
            "--host", "0.0.0.0",
            "--port", str(self.port),
            "--tensor-parallel-size", str(vc.tensor_parallel_size),
            "--dtype", vc.dtype,
        ]
        if vc.gpu_memory_utilization is not None:
            cmd.extend(["--gpu-memory-utilization", str(vc.gpu_memory_utilization)])
        # When kv_cache_memory_bytes is set, omit --gpu-memory-utilization and let
        # vLLM default to 0.9. kv_cache_memory_bytes controls the KV pool size
        # directly; adding gpu_memory_utilization=0.1 caps total VRAM to 10% which
        # prevents the model weights from loading at all.
        if vc.max_model_len > 0:
            cmd.extend(["--max-model-len", str(vc.max_model_len)])
        elif lane_config.context_length > 0:
            cmd.extend(["--max-model-len", str(lane_config.context_length)])
        if vc.kv_cache_memory_bytes:
            cmd.extend(["--kv-cache-memory-bytes", vc.kv_cache_memory_bytes])
        if vc.quantization:
            cmd.extend(["--quantization", vc.quantization])
        # enforce_eager defaults to True (skips torch.compile + CUDA graph
        # capture).  Set enforce_eager=False in vllm_config to opt in to
        # compilation on Ampere+ GPUs where it actually helps.
        if vc.enforce_eager or lane_config.flash_attention is False:
            cmd.append("--enforce-eager")
        # Attention backend: explicit config wins, otherwise auto-detect.
        # FlashInfer JIT crashes drivers on pre-Ampere (compute < 8.0).
        attn_backend = vc.attention_backend or self._auto_attention_backend()
        if attn_backend:
            cmd.extend(["--attention-config.backend", attn_backend])
        if vc.enable_prefix_caching:
            cmd.append("--enable-prefix-caching")
        if vc.disable_custom_all_reduce:
            cmd.append("--disable-custom-all-reduce")
        if vc.enable_sleep_mode:
            cmd.append("--enable-sleep-mode")
        # CUDA graph sizes: opt-in, only when not in eager mode
        if vc.cuda_graph_sizes and not vc.enforce_eager and lane_config.flash_attention is not False:
            cmd.extend(["--cuda-graph-sizes", vc.cuda_graph_sizes])
        # CPU RAM offloading for KV cache
        if vc.cpu_offload_gb > 0:
            cmd.extend(["--cpu-offload-gb", str(vc.cpu_offload_gb)])
        # Persist vLLM compilation artifacts on the shared models volume so
        # restarts can reuse them instead of recompiling from scratch.
        if not self._has_compilation_config_override(vc.extra_args):
            import json as _json
            cache_root = os.path.join(self._global_config.models_path, ".cache", "vllm")
            cmd.extend(["--compilation-config", _json.dumps({"cache_dir": cache_root})])
        if vc.chat_template_kwargs:
            import json as _json
            cmd.extend(["--default-chat-template-kwargs", _json.dumps(vc.chat_template_kwargs)])
        cmd.extend(vc.extra_args)
        return cmd

    @staticmethod
    def _has_compilation_config_override(extra_args: list[str]) -> bool:
        """True when the user already supplied a vLLM compilation config flag."""
        return any(
            arg == "--compilation-config"
            or arg.startswith("--compilation-config=")
            or arg == "-cc"
            or arg.startswith("-cc")
            for arg in extra_args
        )

    def _auto_attention_backend(self) -> str:
        """Auto-select attention backend based on GPU compute capability.

        Returns an operator override when the worker has one, otherwise leaves
        backend selection to vLLM.
        """
        forced_backend = (os.environ.get("LOGOS_VLLM_AUTO_ATTENTION_BACKEND") or "").strip().upper()
        if forced_backend:
            return forced_backend
        return ""

    _cached_cuda_arch: str | None = None

    def _detect_cuda_arch(self) -> str | None:
        """Auto-detect GPU compute capability via nvidia-smi. Cached per process."""
        if VllmProcessHandle._cached_cuda_arch is not None:
            return VllmProcessHandle._cached_cuda_arch or None
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=compute_cap", "--format=csv,noheader"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                caps = set()
                for line in result.stdout.strip().splitlines():
                    cap = line.strip()
                    if cap:
                        caps.add(cap)
                if caps:
                    arch = ";".join(sorted(caps))
                    VllmProcessHandle._cached_cuda_arch = arch
                    return arch
        except Exception:
            pass
        VllmProcessHandle._cached_cuda_arch = ""
        return None

    def _resolve_vllm_binary(self, configured_binary: str) -> list[str]:
        """Resolve the vLLM CLI executable with actionable fallback order.

        Returns a list of tokens so callers can do ``[*prefix, "serve", model, ...]``.

        Resolution order:
          1. ``configured_binary`` (absolute/relative path or bare command name)
          2. ``PATH`` lookup for configured name, then plain ``vllm``
          3. Sibling executable next to the active interpreter (handles unactivated venvs)
          4. Well-known venv roots: ``/opt/venv/bin/vllm``, ``/usr/local/bin/vllm``
          5. Module fallback: ``sys.executable -m vllm`` (works when the package is
             installed but the entry-point script is absent or not on PATH)
        """
        raw = (configured_binary or "vllm").strip() or "vllm"

        # 1) Configured path (absolute or relative path-like value)
        if os.path.sep in raw or (os.path.altsep and os.path.altsep in raw):
            candidate = os.path.abspath(os.path.expanduser(raw))
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return [candidate]

        # 2) PATH lookup (configured name first, then plain 'vllm')
        for cmd_name in dict.fromkeys((raw, "vllm")):
            found = shutil.which(cmd_name)
            if found:
                return [found]

        # 3) Sibling to the active interpreter (correct for activated venvs)
        venv_sibling = str(Path(sys.executable).resolve().with_name("vllm"))
        if os.path.isfile(venv_sibling) and os.access(venv_sibling, os.X_OK):
            return [venv_sibling]

        # 4) Well-known venv/install roots (handles non-activated /opt/venv setups)
        for root in ("/opt/venv/bin", "/usr/local/bin"):
            candidate = os.path.join(root, "vllm")
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return [candidate]

        # 5) Module fallback: works when the package is installed but the script
        #    entry-point is missing or not on PATH (e.g. bare pip install without bin)
        try:
            import importlib.util
            if importlib.util.find_spec("vllm") is not None:
                return [sys.executable, "-m", "vllm"]
        except Exception:
            pass

        checked = [raw, "PATH", venv_sibling, "/opt/venv/bin/vllm", "/usr/local/bin/vllm",
                   f"{sys.executable} -m vllm"]
        raise FileNotFoundError(
            f"[{self.lane_id}] Could not find vLLM executable. Checked: {', '.join(checked)}. "
            f"Install vLLM in this interpreter: {sys.executable} -m pip install vllm"
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
        for root in ("/usr/local/cuda", "/usr/local/cuda-13.2", "/usr/local/cuda-13.1",
                     "/usr/local/cuda-13", "/usr/local/cuda-12.8", "/usr/local/cuda-12"):
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
            for candidate in ("/usr/local/cuda", "/usr/local/cuda-13.2", "/usr/local/cuda-13.1",
                              "/usr/local/cuda-13", "/usr/local/cuda-12.8", "/usr/local/cuda-12"):
                if os.path.isdir(candidate):
                    env["CUDA_HOME"] = candidate
                    break

        # HuggingFace token — needed for gated models (e.g. gemma)
        hf_token = os.environ.get("HF_TOKEN", "")
        if hf_token:
            env["HF_TOKEN"] = hf_token

        # HuggingFace cache — use same location as Ollama models for consistency
        # (though vLLM uses HF format, not GGUF)
        if self.hf_home_override:
            env["HF_HOME"] = self.hf_home_override
        elif "HF_HOME" not in os.environ:
            env["HF_HOME"] = self._resolve_hf_home(gc.models_path)

        if lane_config.vllm_config is None:
            raise RuntimeError(f"[{self.lane_id}] Missing vllm_config for vLLM lane")
        vc = lane_config.vllm_config
        if vc.server_dev_mode:
            env["VLLM_SERVER_DEV_MODE"] = "1"

        if self._vllm_engine_config.flashinfer_loglevel > 0:
            env["FLASHINFER_LOGLEVEL"] = str(self._vllm_engine_config.flashinfer_loglevel)
        if self._vllm_engine_config.flashinfer_logdest.strip():
            env["FLASHINFER_LOGDEST"] = self._vllm_engine_config.flashinfer_logdest.strip()

        # Persistent compilation caches: point to models_path (mounted volume)
        # so JIT artifacts survive container rebuilds.
        cache_root = os.path.join(gc.models_path, ".cache")

        # vLLM cache root — controls where vLLM stores torch.compile cache,
        # CUDA graph cache, and other artifacts (~/.cache/vllm by default).
        if "VLLM_CACHE_ROOT" not in os.environ:
            env["VLLM_CACHE_ROOT"] = os.path.join(cache_root, "vllm")

        # torch.compile / inductor cache
        if "TORCHINDUCTOR_CACHE_DIR" not in os.environ:
            env["TORCHINDUCTOR_CACHE_DIR"] = os.path.join(cache_root, "torch_inductor")
        if "TORCHINDUCTOR_FX_GRAPH_CACHE" not in os.environ:
            env["TORCHINDUCTOR_FX_GRAPH_CACHE"] = "1"

        # FlashInfer JIT kernel cache (critical — first compile can take 60s+)
        if "FLASHINFER_JIT_DIR" not in os.environ:
            env["FLASHINFER_JIT_DIR"] = os.path.join(cache_root, "flashinfer")

        # Auto-detect CUDA arch for faster compilation
        if "TORCH_CUDA_ARCH_LIST" not in os.environ:
            detected_arch = self._detect_cuda_arch()
            if detected_arch:
                env["TORCH_CUDA_ARCH_LIST"] = detected_arch

        # NCCL P2P: disabled globally by default (PCIe-only assumed).
        # Set engines.vllm.nccl_p2p_available=true in config.yml for NVLink setups.
        if not self._vllm_engine_config.nccl_p2p_available:
            env["NCCL_P2P_DISABLE"] = "1"
            logger.info(
                "[%s] NCCL_P2P_DISABLE=1 (PCIe topology — no NVLink; "
                "set engines.vllm.nccl_p2p_available=true in config.yml to enable P2P)",
                self.lane_id,
            )
        else:
            logger.info("[%s] NCCL P2P enabled (NVLink topology)", self.lane_id)

        # NCCL defaults for tensor-parallel lanes (TP > 1).
        # IMPORTANT: Do NOT set NCCL transport tuning vars (P2P_LEVEL,
        # NET_GDR_LEVEL, BUFFSIZE, SHM_USE_CUDA_MEMCPY, etc.) — these are
        # debugging knobs that override NCCL's auto-detection. NCCL reads the
        # GPU/PCIe/NVLink topology and picks optimal transports automatically.
        # Hardcoding them causes unpredictable behavior across different setups.
        if vc.tensor_parallel_size > 1:
            # Async error handling — detect NCCL failures instead of hanging.
            # (NCCL_ASYNC_ERROR_HANDLING is deprecated; PyTorch reads this one.)
            env.setdefault("TORCH_NCCL_ASYNC_ERROR_HANDLING", "1")
            # Disable cuMem host allocations — unreliable in Docker/VM
            # environments without proper NUMA config. We use ipc:host + shm
            # instead, which is universally safe.
            env.setdefault("NCCL_CUMEM_ENABLE", "0")
            # Extended timeout: FlashInfer JIT can take minutes on first
            # compile, default 10min NCCL timeout is sometimes not enough.
            env.setdefault("NCCL_TIMEOUT", "1800")               # 30 min
            if self._vllm_engine_config.nccl_debug:
                env["NCCL_DEBUG"] = self._vllm_engine_config.nccl_debug
            if self._vllm_engine_config.nccl_debug_subsys:
                env["NCCL_DEBUG_SUBSYS"] = self._vllm_engine_config.nccl_debug_subsys

        return env

    def _build_process_env(
        self,
        lane_config: LaneConfig,
        env: dict[str, str],
        cmd: list[str],
    ) -> dict[str, str]:
        """Build the final subprocess environment for a vLLM lane.

        vLLM should not inherit distributed launcher variables from the worker
        process. In particular, stale LOCAL_RANK/RANK values can make a
        single-GPU lane try to address logical device 1 inside a process that
        only sees one visible GPU.
        """
        process_env = dict(os.environ)
        for key in _SCRUBBED_ENV_VARS:
            process_env.pop(key, None)

        resolved_gpu_devices = lane_config.gpu_devices or self._global_config.gpu_devices
        if resolved_gpu_devices.lower() == "all":
            # When a lane is meant to see all worker GPUs, do not leak an
            # inherited CUDA_VISIBLE_DEVICES restriction from the parent.
            process_env.pop("CUDA_VISIBLE_DEVICES", None)

        process_env.update(env)

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
        return process_env

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

    async def _discover_child_pids(self, root_pid: int) -> set[int]:
        """Discover child PIDs of the root vLLM process (TP worker subprocesses)."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "pgrep", "-P", str(root_pid),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
        except (FileNotFoundError, asyncio.TimeoutError, OSError):
            return set()

        if not stdout:
            return set()

        pids: set[int] = set()
        for line in stdout.decode("utf-8", errors="replace").splitlines():
            line = line.strip()
            if line.isdigit():
                pids.add(int(line))
        return pids

    async def _kill_descendant_processes(self, root_pid: int) -> None:
        """Kill any remaining child processes that survived process-group kill.

        With TP>1 vLLM spawns worker subprocesses. If the process-group kill
        missed any (e.g. they re-parented to init), walk /proc to find and
        kill them.  This is a best-effort safety net.
        """
        # Use known child PIDs (discovered at spawn) + fresh pgrep scan
        child_pids = set(self._known_child_pids)
        try:
            proc = await asyncio.create_subprocess_exec(
                "pgrep", "-P", str(root_pid),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
            if stdout:
                for line in stdout.decode("utf-8", errors="replace").splitlines():
                    line = line.strip()
                    if line.isdigit():
                        child_pids.add(int(line))
        except (FileNotFoundError, asyncio.TimeoutError, OSError):
            pass

        for cpid in child_pids:
            try:
                os.kill(cpid, signal.SIGKILL)
                logger.warning(
                    "[%s] Killed orphaned descendant pid=%d of root pid=%d",
                    self.lane_id, cpid, root_pid,
                )
            except (ProcessLookupError, OSError):
                pass

        self._known_child_pids.clear()

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

    def persist_recent_logs(self, reason: str) -> None:
        """Public wrapper for persisting recent vLLM logs after runtime failures."""
        self._persist_failure_logs(reason)

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
