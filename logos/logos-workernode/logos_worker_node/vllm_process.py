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
import logging
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import urllib.parse
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator, Callable, ClassVar

import httpx
from logos_worker_node.models import (
    _DEFAULT_LANE_CONTEXT_LENGTH,
    LaneConfig,
    OllamaConfig,
    ProcessState,
    ProcessStatus,
    VllmConfig,
    VllmEngineConfig,
)

logger = logging.getLogger("logos_worker_node.vllm_process")


def _env_ready_timeout() -> int:
    """Ready-wait timeout, configurable via ``LOGOS_VLLM_READY_TIMEOUT_S``.

    Default 900s accommodates very large checkpoints (≥100 GB) on cold disk
    where streaming weights alone can take 5–10 minutes. Small/medium models
    on warm disk still typically come up in under a minute; the higher
    ceiling only kicks in when something is genuinely slow.
    """
    raw = (os.environ.get("LOGOS_VLLM_READY_TIMEOUT_S") or "").strip()
    if not raw:
        return 900
    try:
        return max(60, int(raw))
    except (TypeError, ValueError):
        return 900


_READY_TIMEOUT = _env_ready_timeout()
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

# Cache for _discover_pip_cuda_lib_dirs() — computed once per process.
_pip_cuda_lib_dirs: list[str] | None = None


def _discover_pip_cuda_lib_dirs() -> list[str]:
    """Find pip-package lib directories containing CUDA shared libraries.

    PyTorch cu128 wheels depend on CUDA 12 libraries (libcudart.so.12,
    libcublasLt.so.12) shipped by nvidia-* pip packages.  These live under
    ``<site-packages>/nvidia/*/lib/`` and may not be in ``LD_LIBRARY_PATH``
    or registered with ``ldconfig``.  ``torch/lib`` provides ``libc10.so``
    and CUDA stub libraries.

    Results are cached for the lifetime of the process.
    """
    global _pip_cuda_lib_dirs  # noqa: PLW0603
    if _pip_cuda_lib_dirs is not None:
        return _pip_cuda_lib_dirs

    import sysconfig

    dirs: list[str] = []
    sp = sysconfig.get_path("purelib")
    if sp:
        nvidia_root = Path(sp) / "nvidia"
        if nvidia_root.is_dir():
            for child in sorted(nvidia_root.iterdir()):
                lib_dir = child / "lib"
                if lib_dir.is_dir():
                    dirs.append(str(lib_dir))
        torch_lib = Path(sp) / "torch" / "lib"
        if torch_lib.is_dir():
            dirs.append(str(torch_lib))

    _pip_cuda_lib_dirs = dirs
    return dirs


# Model-name → vLLM --tool-call-parser mapping.  Checked in order;
# first match wins.  Patterns are lowercased substrings of the HF model id.
# Full list of parsers: https://docs.vllm.ai/en/latest/features/tool_calling.html
_TOOL_PARSER_RULES: tuple[tuple[str, str], ...] = (
    # --- Patterns that share substrings with other families -----------------
    # Google FunctionGemma (before gemma — "functiongemma" contains "gemma")
    ("functiongemma", "functiongemma"),  # google/functiongemma-270m-it
    # Google Gemma 4
    ("gemma-4", "gemma4"),
    ("gemma4", "gemma4"),
    # Salesforce xLAM (before llama/qwen — xLAM models may contain those)
    ("xlam", "xlam"),
    # NousResearch Hermes (before llama — Hermes-Llama models exist)
    ("hermes", "hermes"),
    # Meta Llama (4 before 3)
    ("llama-4", "llama4_pythonic"),
    ("llama4", "llama4_pythonic"),
    ("llama-3", "llama3_json"),
    ("llama3", "llama3_json"),
    # Mistral / Mixtral
    ("mistral", "mistral"),
    ("mixtral", "mistral"),
    # DeepSeek (specific versions before general; R1 also uses deepseek_v3)
    ("deepseek-v3.2", "deepseek_v32"),
    ("deepseek-v3.1", "deepseek_v31"),
    ("deepseek", "deepseek_v3"),
    # IBM Granite (specific before general)
    ("granite-20b-functioncalling", "granite-20b-fc"),
    ("granite-20b-fc", "granite-20b-fc"),
    ("granite-4", "granite4"),
    ("granite4", "granite4"),
    ("granite", "granite"),
    # Zhipu GLM (4.7 before 4 — "glm-4" is a prefix of "glm-4.7")
    ("glm-4.7", "glm47"),
    ("glm47", "glm47"),
    ("glm-4", "glm45"),  # also covers GLM-4.5 and GLM-4.6
    ("glm4", "glm45"),
    # Shanghai AI Lab InternLM
    ("internlm", "internlm"),
    # AI21 Labs Jamba
    ("jamba", "jamba"),
    # Alibaba Qwen (coder→qwen3_xml per docs, then general qwen3→hermes)
    ("qwen3-coder", "qwen3_xml"),
    ("qwen3_coder", "qwen3_xml"),
    ("qwen3-", "hermes"),
    ("qwen3_", "hermes"),
    ("qwen", "hermes"),
    # MiniMax (m2 before general)
    ("minimax-m2", "minimax_m2"),
    ("minimax_m2", "minimax_m2"),
    ("minimax", "minimax"),
    # Microsoft Phi
    ("phi-4-mini", "phi4_mini_json"),
    ("phi4mini", "phi4_mini_json"),
    # Allen AI OLMo
    ("olmo-3", "olmo3"),
    ("olmo3", "olmo3"),
    # Tencent Hunyuan
    ("hunyuan-a13b", "hunyuan_a13b"),
    ("hunyuan_a13b", "hunyuan_a13b"),
    ("hunyuan", "hunyuan_a13b"),
    # Baidu ERNIE
    ("ernie-4.5", "ernie45"),
    ("ernie45", "ernie45"),
    ("ernie", "ernie45"),
    # Moonshot Kimi
    ("kimi-k2", "kimi_k2"),
    ("kimi_k2", "kimi_k2"),
    ("kimi", "kimi_k2"),
    # ByteDance Seed
    ("seed-oss", "seed_oss"),
    ("seed_oss", "seed_oss"),
    # StepFun (3.5 before 3 — "step-3" is a prefix of "step-3.5")
    ("step-3.5", "step3p5"),
    ("step3p5", "step3p5"),
    ("step-3", "step3"),
    ("step3", "step3"),
    # Sber GigaChat
    ("gigachat", "gigachat3"),
    # Meituan LongCat
    ("longcat", "longcat"),
    # Xiaomi MIMO
    ("mimo", "mimo"),
    # OpenAI OSS (gpt-oss-20b, gpt-oss-120b)
    ("gpt-oss", "openai"),
)

# Model-name → vLLM --reasoning-parser mapping.  Checked in order; first match
# wins.  Patterns are lowercased substrings of the HF model id.
# Registered parser names sourced directly from vllm/reasoning/__init__.py
# (_REASONING_PARSERS_TO_REGISTER dict) — these are the only valid values.
_REASONING_PARSER_RULES: tuple[tuple[str, str], ...] = (
    ("gemma-4", "gemma4"),
    ("gpt-oss", "openai_gptoss"),
)

# Model-name → default --default-chat-template-kwargs mapping.  Applied as a
# base layer; explicit vllm_config.chat_template_kwargs keys win on a per-key
# basis (merge, not replace).
_DEFAULT_CHAT_TEMPLATE_KWARGS_RULES: tuple[tuple[str, dict[str, Any]], ...] = (
    # Google Gemma 4 — thinking is opt-in via chat template
    ("gemma-4", {"enable_thinking": True}),
)


def _infer_reasoning_parser(model: str) -> str | None:
    """Infer the vLLM --reasoning-parser value from the model name.

    Returns the parser name when the model is a known reasoning model, or
    ``None`` when no rule matches (no flag should be emitted).
    """
    model_lower = model.lower()
    for pattern, parser in _REASONING_PARSER_RULES:
        if pattern in model_lower:
            return parser
    return None


def _infer_default_chat_template_kwargs(model: str) -> dict[str, Any]:
    """Infer the default chat-template-kwargs dict from the model name.

    Returns the first matching dict, or ``{}`` when nothing matches.
    The caller should merge (overlay) any explicit user-supplied kwargs on top.
    """
    model_lower = model.lower()
    for pattern, kwargs in _DEFAULT_CHAT_TEMPLATE_KWARGS_RULES:
        if pattern in model_lower:
            return dict(kwargs)  # shallow copy so callers can mutate safely
    return {}


def _infer_tool_call_parser(model: str) -> str:
    """Infer the vLLM tool-call-parser from the model name.

    vLLM requires an explicit ``--tool-call-parser`` value when
    ``--enable-auto-tool-choice`` is set (no built-in auto-detect yet).
    Falls back to ``hermes`` which is broadly compatible.

    TODO: vLLM draft PR adds ``--tool-call-parser=auto`` which would make
    this function obsolete. Check if merged and remove this workaround:
    https://github.com/vllm-project/vllm/pull/34809
    """
    model_lower = model.lower()
    for pattern, parser in _TOOL_PARSER_RULES:
        if pattern in model_lower:
            return parser
    return "hermes"


class VllmProcessHandle:
    """Manages a single vLLM server process on a specific port."""

    def __init__(
        self,
        lane_id: str,
        port: int,
        global_config: OllamaConfig,
        vllm_engine_config: VllmEngineConfig | None = None,
        model_profiles: Any | None = None,
        per_gpu_total_mb: Callable[[], float] | None = None,
    ) -> None:
        self.lane_id = lane_id
        self.port = port
        self._global_config = global_config
        self._vllm_engine_config = vllm_engine_config or VllmEngineConfig()
        self._model_profiles = model_profiles
        self._per_gpu_total_mb = per_gpu_total_mb or (lambda: 0.0)
        self._lane_config: LaneConfig | None = None
        self._process: asyncio.subprocess.Process | None = None
        self._http: httpx.AsyncClient | None = None
        self._log_task: asyncio.Task | None = None
        self._recent_logs: deque[str] = deque(maxlen=200)
        self._stuck_vram: bool = False
        self._known_child_pids: set[int] = set()
        self._process_group_id: int | None = None
        self._max_concurrency: int | None = None
        self.hf_home_override: str | None = None
        # Consecutive liveness-probe failures observed by is_sleeping().
        # The lane manager reads this to escalate to a restart when the API
        # server is alive (/v1/models, /health) but the EngineCore RPC is
        # wedged so /is_sleeping never returns.
        self._consecutive_liveness_failures: int = 0

    async def init(self) -> None:
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(connect=5.0, read=60.0, write=10.0, pool=5.0))

    async def close(self) -> None:
        if self._http:
            await self._http.aclose()
            self._http = None

    # ------------------------------------------------------------------
    # Process lifecycle
    # ------------------------------------------------------------------

    async def spawn(self, lane_config: LaneConfig) -> ProcessStatus:
        """Spawn the vLLM process for this lane.

        Cache safety: before spawning, the on-disk torch.compile and inductor
        caches are purged if the recorded (vLLM, torch) versions don't match
        the venv's current versions — a version bump is the most common cause
        of cache poisoning. If the spawn still fails with a stack trace
        pointing inside the compile cache directory (e.g. an AOT-compiled
        graph that was specialized on a stale shape profile), the caches are
        purged again and the spawn is retried once.
        """
        if self._process is not None and self._process.returncode is None:
            logger.info(
                "[%s] Stopping existing process (pid=%d) before spawn",
                self.lane_id,
                self._process.pid,
            )
            await self._kill_process()

        self._purge_compile_caches_if_versions_changed()

        purged_once = False
        while True:
            try:
                status = await self._spawn_once(lane_config)
                self._write_compile_cache_stamp()
                return status
            except RuntimeError:
                if purged_once or not self.has_poisoned_compile_cache:
                    raise
                purged = self._purge_compile_caches()
                purged_once = True
                if not purged:
                    raise
                logger.warning(
                    "[%s] vLLM startup failed inside the on-disk compile cache; " "purged %s and retrying once",
                    self.lane_id,
                    purged,
                )

    async def _spawn_once(self, lane_config: LaneConfig) -> ProcessStatus:
        """A single vLLM spawn attempt; raises on startup failure."""
        self._recent_logs.clear()
        self._lane_config = lane_config
        cmd = self._build_cmd(lane_config)
        self._require_c_compiler()
        self._require_nvcc(lane_config)
        env = self._build_env(lane_config)

        logger.info(
            "[%s] Spawning vLLM (port=%d, model=%s)",
            self.lane_id,
            self.port,
            lane_config.model,
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
        self._log_task = asyncio.create_task(self._stream_logs(), name=f"logs-vllm-{self.lane_id}")

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
                self.lane_id,
                len(self._known_child_pids),
                self._known_child_pids,
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
                self.lane_id,
                pid,
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

    @property
    def has_fatal_cuda_errors(self) -> bool:
        """True if recent logs contain fatal CUDA error patterns.

        These patterns indicate the GPU is in an unrecoverable state that
        cannot be resolved without a host OS reboot.
        """
        if not self._recent_logs:
            return False
        log_blob = "\n".join(self._recent_logs).lower()
        fatal_patterns = (
            "cuda-capable device(s) is/are busy or unavailable",
            "all cuda-capable devices are busy or unavailable",
            "nccl warn cuda failure",
            "cuda error: out of memory",
        )
        return any(p in log_blob for p in fatal_patterns)

    # Stack-trace path fragments that mean execution is inside a file loaded
    # from the persistent torch.compile / inductor cache. A failure raised
    # from these paths means the cached artifact is no longer valid for the
    # current vLLM/torch build (or the current shape profile of an
    # AOT-compiled model) and the engine cannot start until the cache is
    # removed.
    _POISONED_COMPILE_CACHE_PATH_FRAGMENTS: ClassVar[tuple[str, ...]] = (
        "/.cache/vllm/torch_compile_cache/",
        "/.cache/torch_inductor/",
        "/torch_aot_compile/",
        "/inductor_cache/",
    )

    # Subdirectories under <cache_root>/.cache that are safe to wipe when a
    # compile-cache poisoning is detected. FlashInfer JIT artifacts and the
    # HuggingFace weights cache are intentionally excluded — they are not
    # implicated in compile-cache poisoning and are expensive to rebuild.
    _PURGEABLE_COMPILE_CACHE_SUBDIRS: ClassVar[tuple[str, ...]] = (
        "vllm",
        "torch_inductor",
    )

    _COMPILE_CACHE_STAMP_FILENAME: ClassVar[str] = ".logos_compile_cache_stamp.json"

    @property
    def has_poisoned_compile_cache(self) -> bool:
        """True if recent logs implicate the on-disk torch.compile cache.

        Triggered when a stack-trace line references a file under
        ``VLLM_CACHE_ROOT`` or ``TORCHINDUCTOR_CACHE_DIR``. The originating
        exception can be anything (``RuntimeError`` on a shape assert,
        ``ImportError`` on a stale symbol, ``UnpicklingError`` on a stale
        FX graph) — if execution is reaching into a cached compile artifact
        and crashing there, the artifact is bad.
        """
        if not self._recent_logs:
            return False
        log_blob = "\n".join(self._recent_logs)
        return any(frag in log_blob for frag in self._POISONED_COMPILE_CACHE_PATH_FRAGMENTS)

    def _compile_cache_root(self) -> str | None:
        """Return ``<persistent_root>/.cache`` or ``None`` if unresolvable."""
        try:
            cache_root_dir = self._resolve_persistent_cache_root(self._global_config)
        except Exception:
            logger.exception("[%s] Could not resolve cache root", self.lane_id)
            return None
        if not cache_root_dir:
            return None
        return os.path.join(cache_root_dir, ".cache")

    def _purge_compile_caches(self) -> list[str]:
        """Remove the torch.compile and inductor caches for this worker.

        Returns the paths actually removed. HuggingFace weights and the
        FlashInfer JIT cache are left in place — they are not implicated
        in compile-cache poisoning and are expensive to rebuild. Paths
        resolve to the persistent cache root which, in the standard
        docker-compose deployment, is bind-mounted onto host storage
        (e.g. ``/mnt/ceph``), so the wipe affects the host volume too.
        """
        cache_root = self._compile_cache_root()
        if cache_root is None:
            return []
        removed: list[str] = []
        for sub in self._PURGEABLE_COMPILE_CACHE_SUBDIRS:
            path = os.path.join(cache_root, sub)
            if not os.path.isdir(path):
                continue
            try:
                shutil.rmtree(path)
                removed.append(path)
                logger.warning("[%s] Purged compile cache: %s", self.lane_id, path)
            except OSError:
                logger.exception("[%s] Failed to purge compile cache: %s", self.lane_id, path)
        return removed

    @staticmethod
    def _current_compile_versions() -> dict[str, str]:
        """Return ``{"vllm": "...", "torch": "..."}`` from the worker venv.

        Missing packages are silently omitted so the resulting dict only
        contains versions we successfully read; the stamp comparison then
        compares only on overlapping keys.
        """
        import importlib.metadata as md

        versions: dict[str, str] = {}
        for pkg in ("vllm", "torch"):
            try:
                versions[pkg] = md.version(pkg)
            except md.PackageNotFoundError:
                continue
        return versions

    def _compile_cache_stamp_path(self) -> str | None:
        cache_root = self._compile_cache_root()
        if cache_root is None:
            return None
        return os.path.join(cache_root, self._COMPILE_CACHE_STAMP_FILENAME)

    def _read_compile_cache_stamp(self) -> dict[str, str] | None:
        path = self._compile_cache_stamp_path()
        if not path or not os.path.isfile(path):
            return None
        import json as _json

        try:
            with open(path, encoding="utf-8") as fh:
                data = _json.load(fh)
        except (OSError, ValueError):
            logger.debug(
                "[%s] Could not read compile cache stamp at %s",
                self.lane_id,
                path,
                exc_info=True,
            )
            return None
        if not isinstance(data, dict):
            return None
        return {str(k): str(v) for k, v in data.items()}

    def _write_compile_cache_stamp(self) -> None:
        """Record the current (vllm, torch) versions next to the compile cache."""
        path = self._compile_cache_stamp_path()
        if not path:
            return
        versions = self._current_compile_versions()
        if not versions:
            return
        import json as _json

        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                _json.dump(versions, fh, sort_keys=True)
        except OSError:
            logger.debug(
                "[%s] Could not write compile cache stamp at %s",
                self.lane_id,
                path,
                exc_info=True,
            )

    def _purge_compile_caches_if_versions_changed(self) -> list[str]:
        """Purge compile caches when the recorded versions no longer match.

        Returns the paths actually removed. A version bump of vLLM or torch
        is the most common cause of compile-cache poisoning: the cached
        FX graph / inductor ``.so`` artifacts were produced by the previous
        build and trip the engine when it tries to replay them. Comparing
        a small stamp file against the venv's current versions on every
        spawn lets us preempt that failure without waiting for the reactive
        detector to fire after a crash.
        """
        cache_root = self._compile_cache_root()
        if cache_root is None:
            return []
        # No cache on disk yet → nothing to do, and writing a stamp ahead of
        # time would be misleading. The stamp gets written after the next
        # successful spawn produces real artifacts.
        if not any(os.path.isdir(os.path.join(cache_root, sub)) for sub in self._PURGEABLE_COMPILE_CACHE_SUBDIRS):
            return []
        current = self._current_compile_versions()
        if not current:
            return []
        stamp = self._read_compile_cache_stamp()
        if stamp is not None:
            mismatched = {k: (stamp.get(k), current[k]) for k in current if stamp.get(k) != current[k]}
            if not mismatched:
                return []
            logger.warning(
                "[%s] Compile cache stamp mismatch (%s); purging to avoid poisoning",
                self.lane_id,
                ", ".join(f"{k}: {old}→{new}" for k, (old, new) in mismatched.items()),
            )
        else:
            # Cache exists but no stamp — produced by a worker version
            # that predates the stamping logic. Treat as unknown and purge
            # so we start from a known-good baseline.
            logger.warning(
                "[%s] Compile cache present but no version stamp; purging to avoid poisoning",
                self.lane_id,
            )
        return self._purge_compile_caches()

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
                    models.append(
                        {
                            "name": m.get("id", ""),
                            "size": 0,
                            "size_vram": 0,
                            "details": {"backend": "vllm"},
                        }
                    )
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
            "e2e_latency_histogram": {},
        }
        if self._http is None:
            return metrics
        try:
            resp = await self._http.get(f"{self._base_url()}/metrics", timeout=5.0)
            if resp.status_code != 200:
                return metrics
            _prefix_queries: float = 0.0
            _prefix_hits: float = 0.0
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
                elif (
                    metric_name.endswith("gpu_cache_usage_perc")
                    or metric_name.endswith("gpu_cache_usage_percent")
                    or metric_name.endswith("kv_cache_usage_perc")
                    or metric_name.endswith("kv_cache_usage_percent")
                ):
                    metrics["gpu_cache_usage_percent"] = value * 100.0
                elif metric_name.endswith("prefix_cache_hit_rate"):
                    # Legacy gauge (vLLM < 0.20); kept for backward compatibility.
                    metrics["prefix_cache_hit_rate"] = value
                elif (
                    metric_name.endswith("gpu_prefix_cache_queries")
                    or metric_name.endswith("gpu_prefix_cache_queries_total")
                    or metric_name.endswith(":prefix_cache_queries_total")
                    or metric_name.endswith(":prefix_cache_queries")
                ):
                    _prefix_queries += value
                elif (
                    metric_name.endswith("gpu_prefix_cache_hits")
                    or metric_name.endswith("gpu_prefix_cache_hits_total")
                    or metric_name.endswith(":prefix_cache_hits_total")
                    or metric_name.endswith(":prefix_cache_hits")
                ):
                    _prefix_hits += value
                elif metric_name.endswith("prompt_tokens_total"):
                    metrics["prompt_tokens_total"] = value
                elif metric_name.endswith("generation_tokens_total"):
                    metrics["generation_tokens_total"] = value
                elif "time_to_first_token_seconds_bucket" in metric_name:
                    bucket = "unknown"
                    if 'le="' in name:
                        bucket = name.split('le="', 1)[1].split('"', 1)[0]
                    metrics["ttft_histogram"][bucket] = value
                elif "e2e_request_latency_seconds_bucket" in metric_name:
                    bucket = "unknown"
                    if 'le="' in name:
                        bucket = name.split('le="', 1)[1].split('"', 1)[0]
                    metrics["e2e_latency_histogram"][bucket] = value
            # vLLM 0.20+: compute prefix hit rate from counters when the legacy
            # gauge was not present.
            if metrics["prefix_cache_hit_rate"] is None and _prefix_queries > 0:
                metrics["prefix_cache_hit_rate"] = _prefix_hits / _prefix_queries
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
            raise RuntimeError(f"[{self.lane_id}] vLLM /sleep failed with HTTP {resp.status_code}: {payload}")
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
            raise RuntimeError(f"[{self.lane_id}] vLLM /wake_up failed with HTTP {resp.status_code}: {payload}")

        # Workaround for upstream vLLM bug: /sleep clears only the
        # EngineCore-side (P1) mm receiver cache via EngineCore.reset_mm_cache,
        # leaving the API-server-side (P0) sender cache populated. The next
        # request that re-uses an image hash from before the sleep sends
        # mm_item=None to P1, which asserts on the cache miss
        # (vllm/multimodal/cache.py:644) and wedges the engine. The
        # AsyncLLM.reset_mm_cache path clears both caches and is exposed
        # via /reset_mm_cache (dev-mode endpoint; we already enable
        # VLLM_SERVER_DEV_MODE for sleep support). Best-effort: log and
        # continue if the call fails.
        vc = self._lane_config.vllm_config if self._lane_config else None
        if vc is not None and vc.mm_processor_cache_gb > 0 and self._http is not None:
            reset_url = f"{self._base_url()}/reset_mm_cache"
            try:
                reset_resp = await self._http.post(reset_url, timeout=10.0)
                if reset_resp.status_code not in (200, 202):
                    logger.warning(
                        "[%s] post-wake /reset_mm_cache returned HTTP %s — "
                        "P0/P1 mm caches may be desynced and the next image "
                        "request can wedge the engine",
                        self.lane_id,
                        reset_resp.status_code,
                    )
            except httpx.HTTPError as exc:
                logger.warning(
                    "[%s] post-wake /reset_mm_cache failed: %s — " "P0/P1 mm caches may be desynced",
                    self.lane_id,
                    exc,
                )
        return payload

    async def is_sleeping(self) -> bool | None:
        """Return vLLM sleeping state when supported, else None.

        Side-effect: track consecutive transport-level failures (timeout /
        connection-reset) so the lane manager can detect a wedged EngineCore
        even when the API server itself remains alive (e.g. /v1/models and
        /health still return 200).  A wedged EngineCore makes /is_sleeping
        hang because it must round-trip to the engine over ZMQ.
        """
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
        except httpx.HTTPError:
            self._consecutive_liveness_failures += 1
            return None
        if resp.status_code != 200:
            # Non-200 here is "unknown" (e.g. dev mode off); not a wedge
            # signal, so we leave the failure counter alone instead of
            # resetting it — only an actual successful round-trip below
            # proves the engine RPC is live.
            return None
        try:
            payload = resp.json()
        except ValueError:
            return None
        self._consecutive_liveness_failures = 0
        value = payload.get("is_sleeping") if isinstance(payload, dict) else None
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        return None

    @property
    def consecutive_liveness_failures(self) -> int:
        """Number of consecutive transport-level failures from is_sleeping().

        Lane manager uses this to escalate to a restart when /is_sleeping
        keeps timing out: that means the EngineCore RPC channel is wedged
        even if the API server's other endpoints are still alive.
        """
        return self._consecutive_liveness_failures

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

    _GMU_AUTO_FLOOR: ClassVar[float] = 0.5
    _GMU_AUTO_CEILING: ClassVar[float] = 0.95

    def _resolve_gmu(
        self,
        vc: VllmConfig,
        lane_config: LaneConfig,
    ) -> float | None:
        """Return the gpu_memory_utilization to pass to vLLM, or None to omit.

        Selection order:
          1. Explicit per-model override (vc.gpu_memory_utilization is not
             None) — operator's value wins, no derivation.
          2. Auto-derive from calibrated profile when available:
             gmu = clamp(loaded_vram_mb / tp / per_gpu_total_mb,
                         _GMU_AUTO_FLOOR, _GMU_AUTO_CEILING)
             Matches what the lane actually uses; the planner's separate
             PER_GPU_COLD_START_MB headroom is the sole safety buffer.
          3. None — no profile, no override; omit the flag and let vLLM
             apply its own default (0.9 in current versions).
        """
        if vc.gpu_memory_utilization is not None:
            return float(vc.gpu_memory_utilization)
        if self._model_profiles is None:
            return None
        profile = self._model_profiles.get_profile(lane_config.model)
        if profile is None:
            return None
        loaded = getattr(profile, "loaded_vram_mb", None)
        tp = getattr(profile, "tensor_parallel_size", None) or vc.tensor_parallel_size
        if not loaded or not tp or tp <= 0:
            return None
        per_gpu_total = self._per_gpu_total_mb()
        if per_gpu_total <= 0:
            return None
        derived = float(loaded) / float(tp) / float(per_gpu_total)
        clamped = min(self._GMU_AUTO_CEILING, max(self._GMU_AUTO_FLOOR, derived))
        logger.info(
            "[%s] Auto-derived gpu_memory_utilization=%.3f for %s "
            "(loaded=%.0fMB / tp=%d / per_gpu_total=%.0fMB; raw=%.3f, "
            "clamped to [%.2f, %.2f])",
            self.lane_id,
            clamped,
            lane_config.model,
            loaded,
            tp,
            per_gpu_total,
            derived,
            self._GMU_AUTO_FLOOR,
            self._GMU_AUTO_CEILING,
        )
        return clamped

    def _calibrated_max_model_len(self, lane_config: LaneConfig) -> int | None:
        """Return the auto-shrunk --max-model-len recorded by calibration.

        Calibration parses vLLM's "estimated maximum model length is N"
        suggestion and re-probes with --max-model-len=N when the operator's
        pinned KV budget can't fit one request at the model's default
        max_seq_len. The value is persisted on the profile so the lane
        spawner reuses the same flag — without this, vLLM would refuse to
        start at the default max_seq_len even though the budget was proven
        viable at the shrunk value.
        """
        if self._model_profiles is None:
            return None
        profile = self._model_profiles.get_profile(lane_config.model)
        if profile is None:
            return None
        value = getattr(profile, "calibration_max_model_len", None)
        if not value or int(value) <= 0:
            return None
        return int(value)

    def _build_cmd(self, lane_config: LaneConfig) -> list[str]:
        """Build the vllm serve command."""
        if not lane_config.vllm_config:
            raise RuntimeError(f"[{self.lane_id}] Missing vllm_config for vLLM lane")
        vc = lane_config.vllm_config
        vllm_prefix = self._resolve_vllm_binary(vc.vllm_binary)
        cmd = [
            *vllm_prefix,
            "serve",
            lane_config.model,
            "--host",
            "0.0.0.0",
            "--port",
            str(self.port),
            "--tensor-parallel-size",
            str(vc.tensor_parallel_size),
            "--dtype",
            vc.dtype,
        ]
        # Resolve gpu_memory_utilization: explicit per-model override wins;
        # otherwise auto-derive from the calibrated profile so vLLM's startup
        # floor check (free_per_gpu >= gmu * total_per_gpu, raised by
        # vllm/v1/worker/utils.py:request_memory) matches the lane's actual
        # measured footprint. The +500 MB cold-start headroom lives only in the
        # planner's PER_GPU_COLD_START_MB; baking it into gmu would
        # double-count and unnecessarily reject co-resident sleeping lanes.
        resolved_gmu = self._resolve_gmu(vc, lane_config)
        if resolved_gmu is not None:
            cmd.extend(["--gpu-memory-utilization", str(resolved_gmu)])
        if vc.max_model_len > 0:
            cmd.extend(["--max-model-len", str(vc.max_model_len)])
        # For vLLM lanes, context_length defaults to 4096 from shared lane
        # schema. Treat that sentinel default as "unset" so vLLM can use the
        # model's native maximum context unless an explicit override is given.
        elif lane_config.context_length > 0 and lane_config.context_length != _DEFAULT_LANE_CONTEXT_LENGTH:
            cmd.extend(["--max-model-len", str(lane_config.context_length)])
        else:
            # Reuse calibration's auto-shrunk --max-model-len so production
            # matches the configuration that actually passed the binary search.
            # Without this, vLLM falls back to the model's default max_seq_len
            # (e.g. Gemma-3-12B's 131072), which the operator-pinned KV budget
            # may not be able to hold for a single request — vLLM then refuses
            # to start even though calibration proved a shrunk value works.
            calibrated_max_len = self._calibrated_max_model_len(lane_config)
            if calibrated_max_len:
                cmd.extend(["--max-model-len", str(calibrated_max_len)])
        if vc.kv_cache_memory_bytes:
            cmd.extend(["--kv-cache-memory-bytes", vc.kv_cache_memory_bytes])
        if vc.kv_cache_dtype:
            cmd.extend(["--kv-cache-dtype", vc.kv_cache_dtype])
        if vc.quantization:
            cmd.extend(["--quantization", vc.quantization])
        # enforce_eager defaults to False (CUDA graph capture enabled).
        # Set enforce_eager=True in vllm_config to skip torch.compile + graph
        # capture — required on Turing (SM 7.5) and other pre-Ampere boards
        # where graph capture is unstable, and as a workaround for Marlin MoE
        # kernels under TP>1.
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
        # Tool calling: enabled by default so OpenAI-compatible clients
        # (OpenCode, etc.) can send tools/tool_choice without getting HTTP 400.
        # vLLM requires --tool-call-parser when --enable-auto-tool-choice is set.
        # When tool_call_parser is empty we infer the parser from the model name.
        if vc.enable_auto_tool_choice:
            parser = vc.tool_call_parser or _infer_tool_call_parser(lane_config.model)
            cmd.append("--enable-auto-tool-choice")
            cmd.extend(["--tool-call-parser", parser])
        # Reasoning parser: empty = infer from model name; explicit = use as-is;
        # explicit "none" = skip the flag entirely.
        if vc.reasoning_parser != "none":
            reasoning_parser = vc.reasoning_parser or _infer_reasoning_parser(lane_config.model)
            if reasoning_parser:
                cmd.extend(["--reasoning-parser", reasoning_parser])
        # CUDA graph sizes: opt-in, only when not in eager mode
        if vc.cuda_graph_sizes and not vc.enforce_eager and lane_config.flash_attention is not False:
            cmd.extend(["--cuda-graph-sizes", vc.cuda_graph_sizes])
        # CPU RAM offloading for KV cache
        if vc.cpu_offload_gb > 0:
            cmd.extend(["--cpu-offload-gb", str(vc.cpu_offload_gb)])
        # Multimodal processor cache. Pass explicitly so the value the worker
        # uses to gate the post-wake /reset_mm_cache workaround matches what
        # vLLM is actually running with — without this they could diverge if
        # vLLM ever changes its built-in default.
        cmd.extend(["--mm-processor-cache-gb", str(vc.mm_processor_cache_gb)])
        # Persist vLLM compilation artifacts on the resolved cache root so
        # restarts can reuse them instead of recompiling from scratch.
        if not self._has_compilation_config_override(vc.extra_args):
            import json as _json

            cache_root = os.path.join(
                self._resolve_persistent_cache_root(self._global_config),
                ".cache",
                "vllm",
            )
            cmd.extend(["--compilation-config", _json.dumps({"cache_dir": cache_root})])
        # Default chat-template-kwargs: start from inferred defaults for the
        # model family, then overlay explicit user-supplied keys (user wins
        # key-by-key; the entire dict is never replaced wholesale).
        inferred_kwargs = _infer_default_chat_template_kwargs(lane_config.model)
        merged_kwargs = {**inferred_kwargs, **vc.chat_template_kwargs}
        if merged_kwargs:
            import json as _json

            cmd.extend(["--default-chat-template-kwargs", _json.dumps(merged_kwargs)])
        # Worker-wide vLLM flags (e.g. --safetensors-load-strategy=prefetch on
        # NFS-flavoured storage that vLLM's auto-detection misses) — applied
        # BEFORE per-lane extra_args so a lane can still override a global
        # default when needed (argparse takes the last occurrence).
        cmd.extend(self._vllm_engine_config.global_extra_args)
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
                capture_output=True,
                text=True,
                timeout=10,
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

        checked = [
            raw,
            "PATH",
            venv_sibling,
            "/opt/venv/bin/vllm",
            "/usr/local/bin/vllm",
            f"{sys.executable} -m vllm",
        ]
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
        for root in (
            "/usr/local/cuda",
            "/usr/local/cuda-13.2",
            "/usr/local/cuda-13.1",
            "/usr/local/cuda-13",
            "/usr/local/cuda-12.8",
            "/usr/local/cuda-12",
        ):
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
            for candidate in (
                "/usr/local/cuda",
                "/usr/local/cuda-13.2",
                "/usr/local/cuda-13.1",
                "/usr/local/cuda-13",
                "/usr/local/cuda-12.8",
                "/usr/local/cuda-12",
            ):
                if os.path.isdir(candidate):
                    env["CUDA_HOME"] = candidate
                    break

        # HuggingFace token — needed for gated models (e.g. gemma)
        hf_token = os.environ.get("HF_TOKEN", "")
        if hf_token:
            env["HF_TOKEN"] = hf_token

        # All four worker caches (HF_HOME, VLLM_CACHE_ROOT, TORCHINDUCTOR_CACHE_DIR,
        # FLASHINFER_WORKSPACE_BASE) hang off this single root.  Default is the
        # ollama models_path because the standard docker-compose mounts that as
        # a persistent named volume; deployments without ollama (or with a
        # different storage layout) can override globally via
        # LOGOS_WORKER_CACHE_ROOT, or per-cache via the individual env vars.
        cache_root_dir = self._resolve_persistent_cache_root(gc)

        # HuggingFace cache — write into the persistent root.
        if self.hf_home_override:
            env["HF_HOME"] = self.hf_home_override
        elif "HF_HOME" not in os.environ:
            env["HF_HOME"] = self._resolve_hf_home(cache_root_dir)

        if lane_config.vllm_config is None:
            raise RuntimeError(f"[{self.lane_id}] Missing vllm_config for vLLM lane")
        vc = lane_config.vllm_config
        # Sleep endpoints (/sleep, /wake_up, /is_sleeping) require
        # VLLM_SERVER_DEV_MODE.  Auto-enable it when sleep mode is active
        # so operators don't need to set both flags.
        if vc.server_dev_mode or vc.enable_sleep_mode:
            env["VLLM_SERVER_DEV_MODE"] = "1"

        if self._vllm_engine_config.flashinfer_loglevel > 0:
            env["FLASHINFER_LOGLEVEL"] = str(self._vllm_engine_config.flashinfer_loglevel)
        if self._vllm_engine_config.flashinfer_logdest.strip():
            env["FLASHINFER_LOGDEST"] = self._vllm_engine_config.flashinfer_logdest.strip()

        # Persistent compilation caches: point to the resolved cache root so
        # JIT artifacts survive container rebuilds.
        cache_root = os.path.join(cache_root_dir, ".cache")

        # vLLM cache root — controls where vLLM stores torch.compile cache,
        # CUDA graph cache, and other artifacts (~/.cache/vllm by default).
        if "VLLM_CACHE_ROOT" not in os.environ:
            env["VLLM_CACHE_ROOT"] = os.path.join(cache_root, "vllm")

        # torch.compile / inductor cache
        if "TORCHINDUCTOR_CACHE_DIR" not in os.environ:
            env["TORCHINDUCTOR_CACHE_DIR"] = os.path.join(cache_root, "torch_inductor")
        if "TORCHINDUCTOR_FX_GRAPH_CACHE" not in os.environ:
            env["TORCHINDUCTOR_FX_GRAPH_CACHE"] = "1"

        # FlashInfer JIT kernel cache (critical — first compile can take 60s+).
        # flashinfer 0.6.x reads FLASHINFER_WORKSPACE_BASE (see
        # flashinfer/jit/env.py) and writes its cache to
        # <base>/.cache/flashinfer/<version>/<arch>/cached_ops/.  Pointing the
        # base at the persistent volume keeps compiled .so files across
        # container rebuilds so the worker boot warmup + first lane spawn pay
        # JIT cost only once per (head_dim, dtype).  FLASHINFER_JIT_DIR is a
        # Python attribute on flashinfer.jit.env, NOT an env var read at
        # runtime — setting it has no effect.
        if "FLASHINFER_WORKSPACE_BASE" not in os.environ:
            env["FLASHINFER_WORKSPACE_BASE"] = cache_root_dir

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
            env.setdefault("NCCL_TIMEOUT", "1800")  # 30 min
            if self._vllm_engine_config.nccl_debug:
                env["NCCL_DEBUG"] = self._vllm_engine_config.nccl_debug
            if self._vllm_engine_config.nccl_debug_subsys:
                env["NCCL_DEBUG_SUBSYS"] = self._vllm_engine_config.nccl_debug_subsys

        # Per-model environment overrides (e.g. VLLM_USE_V1=0 for models
        # whose head dimensions exceed V1 attention kernel limits on SM 7.5).
        if vc.env_overrides:
            env.update(vc.env_overrides)

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

        # Ensure pip-vendored CUDA libraries (libcudart.so.12, libcublasLt.so.12
        # from nvidia-* packages, libc10.so from torch) are discoverable.
        # The Dockerfile registers these via ldconfig, but this is a defensive
        # fallback for environments where ldconfig wasn't configured.
        pip_cuda_dirs = _discover_pip_cuda_lib_dirs()
        if pip_cuda_dirs:
            existing_ld = process_env.get("LD_LIBRARY_PATH", "")
            pip_cuda_path = os.pathsep.join(pip_cuda_dirs)
            process_env["LD_LIBRARY_PATH"] = (
                f"{pip_cuda_path}{os.pathsep}{existing_ld}" if existing_ld else pip_cuda_path
            )

        # Keep helper tools from the same virtualenv (for example `ninja`
        # used by FlashInfer JIT) available even when the venv is not activated.
        vllm_bin_dir = str(Path(cmd[0]).resolve().parent)
        current_path = process_env.get("PATH", "")
        if vllm_bin_dir:
            process_env["PATH"] = vllm_bin_dir if not current_path else f"{vllm_bin_dir}{os.pathsep}{current_path}"
        return process_env

    @staticmethod
    def _resolve_persistent_cache_root(gc) -> str:
        """Single root directory for all worker-side persistent caches.

        Resolution order:
          1. ``LOGOS_WORKER_CACHE_ROOT`` env var if non-empty.
          2. ``gc.models_path`` (the ollama models_path) — used because the
             standard docker-compose mounts that as a persistent named volume,
             so it's the one path the worker can rely on surviving container
             rebuilds in the default deployment.

        ``HF_HOME``, ``VLLM_CACHE_ROOT``, ``TORCHINDUCTOR_CACHE_DIR`` and
        ``FLASHINFER_WORKSPACE_BASE`` all derive from this root; deployments
        without ollama (or with a different storage layout) only need to set
        ``LOGOS_WORKER_CACHE_ROOT`` to point at any persistent path they have
        — no need to override each cache env var individually.
        """
        override = os.environ.get("LOGOS_WORKER_CACHE_ROOT", "").strip()
        if override:
            return override
        return getattr(gc, "models_path", "") or ""

    def _resolve_hf_home(self, cache_root_dir: str) -> str:
        """Pick a writable HuggingFace cache path for vLLM downloads.

        Preferred path is ``<cache_root_dir>/.hf_cache`` (where
        ``cache_root_dir`` is the resolved persistent cache root). If that
        path is not writable for the current user, fall back to
        ``~/.cache/huggingface``.
        """
        preferred = Path(cache_root_dir).expanduser() / ".hf_cache" if cache_root_dir else None
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
            logger.warning(
                "[%s] vLLM (pid=%d) did not exit in %ds — SIGKILL",
                self.lane_id,
                pid,
                _STOP_TIMEOUT,
            )
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
                "pgrep",
                "-P",
                str(root_pid),
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
                "pgrep",
                "-P",
                str(root_pid),
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
                    self.lane_id,
                    cpid,
                    root_pid,
                )
            except (ProcessLookupError, OSError):
                pass

        self._known_child_pids.clear()

    async def _verify_vram_released(
        self,
        pid: int,
        timeout: float = 10.0,
        poll_interval: float = 1.0,
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
            self.lane_id,
            check_pids,
            timeout,
        )
        return False

    # Matches vLLM startup line like:
    #   "Maximum concurrency for 4,096 tokens per request: 10.66x"
    _RE_MAX_CONCURRENCY = re.compile(r"Maximum concurrency for [\d,]+ tokens per request:\s+([\d.]+)x")

    # vLLM warnings that are expected side-effects of our configuration
    # (e.g. VLLM_SERVER_DEV_MODE required for sleep endpoints) and add
    # no operational value — suppress them from the log stream.
    _SUPPRESSED_LOG_FRAGMENTS: ClassVar[tuple[str, ...]] = ("SECURITY WARNING: Development endpoints are enabled",)

    @property
    def max_concurrency(self) -> int | None:
        """Max concurrent full-context requests reported by vLLM at startup."""
        return self._max_concurrency

    async def _stream_logs(self) -> None:
        if self._process is None or self._process.stdout is None:
            return
        try:
            async for line_bytes in self._process.stdout:
                line = line_bytes.decode("utf-8", errors="replace").rstrip()
                if line:
                    self._recent_logs.append(line)
                    if any(frag in line for frag in self._SUPPRESSED_LOG_FRAGMENTS):
                        continue
                    logger.info("[vllm:%s] %s", self.lane_id, line)
                    if self._max_concurrency is None:
                        m = self._RE_MAX_CONCURRENCY.search(line)
                        if m:
                            self._max_concurrency = max(1, math.floor(float(m.group(1))))
                            logger.info(
                                "[%s] vLLM reported max concurrency: %d",
                                self.lane_id,
                                self._max_concurrency,
                            )
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
        if self.has_poisoned_compile_cache:
            return (
                "Stack trace points inside the on-disk torch.compile / inductor cache. "
                "The worker auto-purges and retries once; a repeat failure means the new "
                "spawn produced fresh artifacts that still crash."
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
                f"[{self.lane_id}] vLLM exited during startup " f"(port={self.port}, return_code={status.return_code})"
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
                    self.lane_id,
                    self._process.returncode,
                )
                return False
            try:
                resp = await self._http.get(f"{self._base_url()}/health", timeout=5.0)
                if resp.status_code == 200:
                    elapsed_ms = int((loop.time() - (deadline - timeout)) * 1000)
                    logger.info(
                        "[%s] vLLM ready at port %d (%dms)",
                        self.lane_id,
                        self.port,
                        elapsed_ms,
                    )
                    return True
            except httpx.HTTPError:
                pass
            await asyncio.sleep(delay)
            delay = min(delay * 1.5, 5.0)
        return False
