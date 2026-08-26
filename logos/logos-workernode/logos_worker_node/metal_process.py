"""Metal process handle — a vLLM lane served by the vllm-metal plugin.

vllm-metal is a *platform plugin* for vLLM, not a fork: it keeps the ``vllm
serve`` CLI and the OpenAI-compatible API, and swaps the compute backend for
MLX on Apple Silicon. That makes almost all of :class:`VllmProcessHandle`
reusable — spawn/kill, readiness polling, log streaming, backend metrics, tool-
and reasoning-parser inference, and the whole lane lifecycle are inherited
unchanged.

What this subclass changes, and why
───────────────────────────────────
• The command line. CUDA-only flags must not merely be left at their defaults
  — several do not exist in the Metal build's argparse and would abort startup.
  Note also that the two stacks are on different vLLM versions (the CUDA image
  pins 0.28.x, vllm-metal currently vendors 0.19.x), so flag *syntax* diverges
  too: ``--attention-config.backend`` on the CUDA side is ``--attention-backend``
  here. Building the command separately keeps one from silently breaking the
  other; tests/test_metal_process.py asserts the result against the real
  ``vllm serve --help=all`` surface.

• The environment. Metal's tuning knobs are env vars (``VLLM_METAL_*``), not
  CLI flags — most importantly VLLM_METAL_MEMORY_FRACTION, which takes the
  place of ``--gpu-memory-utilization``. CUDA/NCCL/FlashInfer variables are
  dropped entirely.

• The preflight guards. ``_require_nvcc`` and ``_require_c_compiler`` exist for
  Triton/FlashInfer JIT, neither of which runs here; left in place they would
  refuse to start every lane on a perfectly healthy Mac.

Not supported on this backend, by design of the platform:
  - Tensor parallelism (single integrated GPU) — and therefore pre-sharded
    checkpoints, which only exist to speed up TP>1 loads.
  - Sleep/wake: vLLM's sleep mode is built on CuMemAllocator (CUDA virtual
    memory). The lane reports sleep_state="unsupported" and the orchestrator
    falls back to stop/start for memory reclamation.
  - torch.compile / CUDA graph capture, and the on-disk inductor caches.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from logos_worker_node.models import LaneConfig, MetalConfig, OllamaConfig, VllmEngineConfig
from logos_worker_node.vllm_process import (
    _DEFAULT_LANE_CONTEXT_LENGTH,
    _infer_default_chat_template_kwargs,
    _infer_reasoning_parser,
    _infer_tool_call_parser,
    _resolve_chat_template,
    VllmProcessHandle,
)

logger = logging.getLogger(__name__)

# Where vllm-metal's install.sh puts its virtualenv.
_DEFAULT_METAL_VENV = "~/.venv-vllm-metal"


class MetalVllmProcessHandle(VllmProcessHandle):
    """A vLLM lane running on Apple Silicon via the vllm-metal plugin."""

    def __init__(self, *args: Any, metal_config: MetalConfig | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._metal_config = metal_config or MetalConfig()

    # ------------------------------------------------------------------
    # Preflight guards that do not apply to this backend
    # ------------------------------------------------------------------

    def _require_c_compiler(self) -> None:
        """No-op: nothing JIT-compiles C here (no Triton, no FlashInfer)."""

    def _require_nvcc(self, lane_config: LaneConfig) -> None:
        """No-op: there is no CUDA toolkit on macOS and none is needed."""

    def _auto_attention_backend(self) -> str:
        """Let vllm-metal choose. Its backends are unrelated to CUDA's."""
        return ""

    def _detect_cuda_arch(self) -> str | None:
        """No CUDA device to detect."""
        return None

    async def _maybe_prepare_sharded_checkpoint(self, lane_config: LaneConfig) -> None:
        """No-op: sharded checkpoints only benefit TP>1, which Metal lacks."""
        self._sharded_model_dir = None

    def _purge_compile_caches_if_versions_changed(self) -> list[str]:
        """No-op: no torch.compile/inductor artifacts are produced on MLX."""
        return []

    @property
    def has_fatal_cuda_errors(self) -> bool:
        """Metal counterpart to the CUDA fatal-error scan.

        Reported through the inherited property name so the lane manager's
        restart logic keeps working unchanged. Unlike the CUDA cases, none of
        these are host-wedging conditions that need a reboot — a Metal
        allocation failure is confined to the process — so the worker's
        auto-reboot path is deliberately not fed from here.
        """
        return False

    @property
    def has_metal_allocation_failure(self) -> bool:
        """True when recent logs show the lane exceeded a Metal memory limit.

        Two distinct limits produce these: the working-set budget (how much may
        be wired down in total) and max_buffer_length (the ceiling on any single
        allocation). The second bites even when plenty of memory is free, and is
        the usual reason a large model refuses to load on a small Mac.
        """
        if not self._recent_logs:
            return False
        blob = "\n".join(self._recent_logs).lower()
        patterns = (
            "[metal::malloc]",
            "greater than the maximum allowed buffer size",
            "insufficient memory",
            "failed to allocate",
            "mtlbuffer",
        )
        return any(p in blob for p in patterns)

    def has_stuck_vram(self) -> bool:
        """Always False: no driver-resident contexts survive a killed process.

        On CUDA a killed process can leave VRAM pinned in the driver, which is
        what the stuck-VRAM path and the auto-reboot watchdog exist for. Metal
        memory is plain unified memory owned by the process and reclaimed by the
        kernel on exit, so that failure mode does not exist here.
        """
        return False

    # ------------------------------------------------------------------
    # Binary resolution
    # ------------------------------------------------------------------

    def _resolve_vllm_binary(self, configured_binary: str) -> list[str]:
        """Resolve the vllm CLI, preferring the vllm-metal venv.

        The worker runs in its own virtualenv, which deliberately does not
        contain vLLM or mlx — those live in the vllm-metal venv created by its
        install.sh. So unlike the CUDA path, the interpreter running this code
        is never the right place to look first.
        """
        configured = (configured_binary or "").strip()
        # A lane-level vllm_binary is almost always the schema default "vllm";
        # only treat it as authoritative when it actually points somewhere.
        explicit = configured if (configured and configured != "vllm") else ""
        candidates = [
            explicit,
            (self._metal_config.vllm_binary or "").strip(),
            os.path.join(_DEFAULT_METAL_VENV, "bin", "vllm"),
        ]
        for candidate in candidates:
            if not candidate:
                continue
            resolved = os.path.abspath(os.path.expanduser(candidate))
            if os.path.isfile(resolved) and os.access(resolved, os.X_OK):
                return [resolved]

        # Fall back to the inherited resolution (PATH, sibling, module form) so
        # non-standard installs still work, and so the error it raises when
        # nothing is found lists everything that was checked.
        return super()._resolve_vllm_binary(configured_binary)

    @staticmethod
    def _resolve_persistent_cache_root(gc) -> str:
        """Cache root with a macOS-appropriate default.

        The inherited resolution falls back to the ollama models_path
        (/usr/share/ollama/.ollama/models), which exists only because the Linux
        compose file mounts a volume there. On a Mac that path is absent and not
        creatable without root, so VLLM_CACHE_ROOT would point somewhere
        unwritable. LOGOS_WORKER_CACHE_ROOT (which worker.cache_path is lifted
        into, see config._propagate_cache_path_to_env) still wins when set.
        """
        override = os.environ.get("LOGOS_WORKER_CACHE_ROOT", "").strip()
        if override:
            return override
        models_path = (getattr(gc, "models_path", "") or "").strip()
        if models_path and os.path.isdir(models_path) and os.access(models_path, os.W_OK):
            return models_path
        return str(Path.home() / "Library" / "Caches" / "logos-workernode")

    # ------------------------------------------------------------------
    # Command line
    # ------------------------------------------------------------------

    def _build_cmd(self, lane_config: LaneConfig) -> list[str]:
        """Build the ``vllm serve`` command for a Metal lane.

        Deliberately omitted versus the CUDA build:
          --tensor-parallel-size     single integrated GPU
          --attention-config.backend not in this argparse (see module docstring)
          --cuda-graph-sizes         CUDA graph capture does not exist here
          --enable-sleep-mode        needs CuMemAllocator
          --gpu-memory-utilization   ignored; VLLM_METAL_MEMORY_FRACTION instead
          --kv-cache-dtype           fp8 KV is a CUDA kernel feature
          --cpu-offload-gb           meaningless on unified memory
          --compilation-config       no inductor cache to place
          --load-format sharded_state / --served-model-name  (TP>1 only)
        """
        if not lane_config.vllm_config:
            raise RuntimeError(f"[{self.lane_id}] Missing vllm_config for Metal lane")
        vc = lane_config.vllm_config

        if vc.tensor_parallel_size > 1:
            raise RuntimeError(
                f"[{self.lane_id}] tensor_parallel_size={vc.tensor_parallel_size} is not "
                "supported on the Metal backend — Apple Silicon exposes a single "
                "integrated GPU. Set tensor_parallel_size=1 for this model."
            )

        cmd = [
            *self._resolve_vllm_binary(vc.vllm_binary),
            "serve",
            lane_config.model,
            "--host",
            "0.0.0.0",
            "--port",
            str(self.port),
            "--dtype",
            vc.dtype,
        ]

        # Context window: same precedence as the CUDA path — explicit
        # max_model_len wins, then a non-default lane context_length, else let
        # vLLM size it against the actual KV budget.
        if vc.max_model_len > 0:
            cmd.extend(["--max-model-len", str(vc.max_model_len)])
        elif lane_config.context_length > 0 and lane_config.context_length != _DEFAULT_LANE_CONTEXT_LENGTH:
            cmd.extend(["--max-model-len", str(lane_config.context_length)])
        else:
            cmd.extend(["--max-model-len", "auto"])

        if vc.max_num_seqs > 0:
            cmd.extend(["--max-num-seqs", str(vc.max_num_seqs)])
        else:
            calibrated = self._calibrated_max_num_seqs(lane_config)
            if calibrated:
                cmd.extend(["--max-num-seqs", str(calibrated)])

        # MLX checkpoints carry their quantization in config.json; vLLM infers
        # it. Only pass an explicit override when the operator set one.
        if vc.quantization:
            cmd.extend(["--quantization", vc.quantization])

        if vc.enable_prefix_caching:
            cmd.append("--enable-prefix-caching")

        # enforce_eager is meaningful here too: it skips graph/kernel warmup
        # paths that some MLX models trip over.
        if vc.enforce_eager or lane_config.flash_attention is False:
            cmd.append("--enforce-eager")

        if vc.enable_auto_tool_choice:
            parser = vc.tool_call_parser or _infer_tool_call_parser(lane_config.model)
            cmd.append("--enable-auto-tool-choice")
            cmd.extend(["--tool-call-parser", parser])

        if vc.reasoning_parser != "none":
            reasoning_parser = vc.reasoning_parser or _infer_reasoning_parser(lane_config.model)
            if reasoning_parser:
                cmd.extend(["--reasoning-parser", reasoning_parser])

        cmd.extend(["--mm-processor-cache-gb", str(vc.mm_processor_cache_gb)])

        if vc.chat_template:
            template_path = _resolve_chat_template(vc.chat_template)
            logger.info("[%s] using custom chat template: %s", self.lane_id, template_path)
            cmd.extend(["--chat-template", template_path])

        merged_kwargs = {**_infer_default_chat_template_kwargs(lane_config.model), **vc.chat_template_kwargs}
        if merged_kwargs:
            cmd.extend(["--default-chat-template-kwargs", json.dumps(merged_kwargs)])

        cmd.extend(self._vllm_engine_config.global_extra_args)
        cmd.extend(vc.extra_args)
        return cmd

    # ------------------------------------------------------------------
    # Environment
    # ------------------------------------------------------------------

    def _build_env(self, lane_config: LaneConfig) -> dict[str, str]:
        """Build the environment for a Metal lane.

        Shares only the model-storage settings with the CUDA path (HF token and
        HF_HOME on the persistent cache root). Everything CUDA-, NCCL- or
        FlashInfer-related is dropped, and the VLLM_METAL_* knobs take their
        place.
        """
        if lane_config.vllm_config is None:
            raise RuntimeError(f"[{self.lane_id}] Missing vllm_config for Metal lane")
        vc = lane_config.vllm_config
        mc = self._metal_config
        env: dict[str, str] = {}

        hf_token = os.environ.get("HF_TOKEN", "")
        if hf_token:
            env["HF_TOKEN"] = hf_token

        cache_root_dir = self._resolve_persistent_cache_root(self._global_config)
        if self.hf_home_override:
            env["HF_HOME"] = self.hf_home_override
        elif "HF_HOME" not in os.environ:
            env["HF_HOME"] = self._resolve_hf_home(cache_root_dir)

        # vLLM's own cache root still applies (tokenizer/config artifacts),
        # even though nothing torch-compiles on this backend.
        if "VLLM_CACHE_ROOT" not in os.environ:
            env["VLLM_CACHE_ROOT"] = os.path.join(cache_root_dir, ".cache", "vllm")

        # server_dev_mode is honoured; sleep mode never sets it here because
        # the sleep endpoints are unavailable on this backend anyway.
        if vc.server_dev_mode:
            env["VLLM_SERVER_DEV_MODE"] = "1"

        # ── Metal tuning knobs ────────────────────────────────────────────
        if mc.memory_fraction is not None:
            env["VLLM_METAL_MEMORY_FRACTION"] = str(mc.memory_fraction)
        if mc.use_paged_attention is not None:
            env["VLLM_METAL_USE_PAGED_ATTENTION"] = "1" if mc.use_paged_attention else "0"
        if mc.block_size > 0:
            env["VLLM_METAL_BLOCK_SIZE"] = str(mc.block_size)
        if mc.multimodal_mode:
            env["VLLM_METAL_MULTIMODAL_MODE"] = mc.multimodal_mode
        if mc.prefix_cache_fraction is not None:
            env["VLLM_METAL_PREFIX_CACHE_FRACTION"] = str(mc.prefix_cache_fraction)
        # Prefix caching is requested on the command line; keep the plugin's
        # own switch consistent with it so the two cannot disagree.
        env["VLLM_METAL_PREFIX_CACHE"] = "1" if vc.enable_prefix_caching else "0"

        # Worker-wide Metal overrides first, then per-model ones, so a model
        # override still wins over a node-wide default.
        if mc.env_overrides:
            env.update(mc.env_overrides)
        if vc.env_overrides:
            env.update(vc.env_overrides)

        return env

    def _build_process_env(
        self,
        lane_config: LaneConfig,
        env: dict[str, str],
        cmd: list[str],
    ) -> dict[str, str]:
        """Final subprocess environment, without the CUDA library plumbing.

        The inherited version prepends pip-vendored CUDA library directories to
        LD_LIBRARY_PATH — harmless but meaningless here, and LD_LIBRARY_PATH is
        not even the right variable on macOS (DYLD_*). The venv bin directory is
        still prepended to PATH so the lane resolves helper executables from the
        vllm-metal environment rather than the worker's.
        """
        process_env = dict(os.environ)
        # A stale CUDA_VISIBLE_DEVICES inherited from a shared .env would be
        # meaningless here, and confusing in a crash dump.
        for key in ("CUDA_VISIBLE_DEVICES", "CUDA_HOME", "LD_LIBRARY_PATH", "NCCL_P2P_DISABLE"):
            process_env.pop(key, None)
        process_env.update(env)

        vllm_bin_dir = str(Path(cmd[0]).resolve().parent)
        current_path = process_env.get("PATH", "")
        process_env["PATH"] = vllm_bin_dir if not current_path else f"{vllm_bin_dir}{os.pathsep}{current_path}"
        return process_env

    # ------------------------------------------------------------------
    # Sleep / wake — unsupported on this backend
    # ------------------------------------------------------------------

    def _ensure_sleep_mode_ready(self) -> None:
        """No-op: there is no sleep mode to prepare."""

    async def sleep(self, level: int = 1, mode: str = "wait") -> dict[str, Any]:
        """Reject sleep: vLLM's implementation requires CUDA virtual memory.

        The orchestrator reads sleep_state="unsupported" from the lane and
        falls back to stopping and restarting the lane to reclaim memory.
        """
        logger.info("[%s] sleep is unsupported on the Metal backend", self.lane_id)
        return {"supported": False, "reason": "sleep mode requires CUDA (CuMemAllocator)"}

    async def wake_up(self) -> dict[str, Any]:
        """Reject wake: nothing can be asleep on this backend."""
        return {"supported": False, "reason": "sleep mode requires CUDA (CuMemAllocator)"}

    async def is_sleeping(self) -> bool | None:
        """Always None — "not applicable", distinct from False ("awake")."""
        return None
