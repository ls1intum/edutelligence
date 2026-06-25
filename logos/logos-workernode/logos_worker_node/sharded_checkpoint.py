"""Sharded-state checkpoint conversion + resolution for vLLM TP>1 lanes.

With ``tensor_parallel_size > 1`` every vLLM rank otherwise reads the *entire*
checkpoint and slices out its own shard, so cold-start load time grows roughly
linearly with TP (proportional to the model size × TP of disk reads). vLLM
supports pre-sharded checkpoints (``--load-format sharded_state``) where each
rank reads only its own shard, keeping load time roughly constant in TP.

This module owns:

  * the on-disk layout for converted checkpoints (keyed by model **and** TP —
    a sharded checkpoint is only valid for the exact TP it was produced for),
  * a readiness check (a completion marker written only after a fully-copied,
    successful conversion — so an interrupted run is never mistaken for done),
  * the conversion itself, run as a subprocess against the vLLM-equipped
    interpreter via the standalone :mod:`logos_worker_node._sharded_convert`
    entrypoint.

Conversion is triggered from two places (issue #615):

  1. right after calibration, when the calibrated TP is > 1
     (``logos_bridge._run_calibration_session``), and
  2. lazily, right before a lane with TP>1 is spawned, if no converted
     checkpoint exists yet (``vllm_process.VllmProcessHandle``).

Both call :func:`ensure_sharded_checkpoint`, which is idempotent: if a ready
checkpoint already exists it is returned immediately. On any failure it returns
``None`` and the caller falls back to loading the full checkpoint.
"""

from __future__ import annotations

import logging
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

logger = logging.getLogger("logos_worker_node.sharded_checkpoint")

_SHARDED_CACHE_SUBDIR = ".sharded_cache"
_COMPLETION_MARKER = ".logos_sharded_complete"
DEFAULT_MAX_FILE_SIZE_BYTES = 5 * 1024**3

_CONVERT_ENTRYPOINT = Path(__file__).with_name("_sharded_convert.py")

# In-process locks keyed by target dir so the calibration trigger and the
# spawn-time fallback never convert the same checkpoint concurrently. One
# worker process per node, so cross-process locking is unnecessary.
_locks_guard = threading.Lock()
_dir_locks: dict[str, threading.Lock] = {}


def _sanitize_model(model: str) -> str:
    """Filesystem-safe directory name for a HuggingFace model id."""
    return model.replace("/", "__").replace(":", "__")


def resolve_cache_root(models_path: str) -> str:
    """Resolve the persistent cache root the same way ``vllm_process`` does.

    ``LOGOS_WORKER_CACHE_ROOT`` wins; otherwise the ollama ``models_path``
    (mounted as a persistent volume in the standard docker-compose) is used.
    """
    override = os.environ.get("LOGOS_WORKER_CACHE_ROOT", "").strip()
    if override:
        return override
    return models_path or ""


def sharded_checkpoint_dir(cache_root: str, model: str, tp: int) -> Path:
    """Directory holding the sharded checkpoint for ``(model, tp)``."""
    return Path(cache_root) / _SHARDED_CACHE_SUBDIR / _sanitize_model(model) / f"tp{int(tp)}"


def is_sharded_checkpoint_ready(directory: Path) -> bool:
    """True when ``directory`` holds a completed conversion."""
    try:
        return (directory / _COMPLETION_MARKER).is_file()
    except OSError:
        return False


def _lock_for(directory: Path) -> threading.Lock:
    key = str(directory)
    with _locks_guard:
        lock = _dir_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _dir_locks[key] = lock
        return lock


def resolve_vllm_python(vllm_binary: str) -> str:
    """Find a Python interpreter that has vLLM importable.

    The converter runs as ``<python> _sharded_convert.py …`` so it only needs
    vLLM on its path, not ``logos_worker_node``. vLLM may live in a different
    venv than the worker process, so the interpreter is derived from the
    resolved ``vllm`` executable rather than assuming ``sys.executable``.
    """
    raw = (vllm_binary or "vllm").strip() or "vllm"
    candidates: list[str] = []

    # Explicit path to the vllm executable → sibling python in the same venv.
    if os.path.sep in raw:
        exe = Path(os.path.expanduser(raw))
        candidates += [str(exe.with_name("python")), str(exe.with_name("python3"))]

    found = shutil.which(raw) or shutil.which("vllm")
    if found:
        p = Path(found)
        candidates += [str(p.with_name("python")), str(p.with_name("python3"))]

    for root in ("/opt/venv/bin", "/usr/local/bin"):
        candidates += [os.path.join(root, "python"), os.path.join(root, "python3")]

    for cand in candidates:
        if cand and os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand

    # Last resort: the current interpreter — correct when vLLM is installed in
    # the worker's own venv (the ``sys.executable -m vllm`` resolution path).
    return sys.executable


def _build_convert_env(
    *,
    hf_home: str | None,
    gpu_devices: str,
    tp: int,
    nccl_p2p_available: bool,
    env_overrides: dict[str, str] | None,
) -> dict[str, str]:
    """Environment for the converter — mirrors the serving lane's vLLM env."""
    env = os.environ.copy()
    if hf_home:
        env["HF_HOME"] = hf_home
    hf_token = os.environ.get("HF_TOKEN", "")
    if hf_token:
        env["HF_TOKEN"] = hf_token

    gpu = (gpu_devices or "").strip().lower()
    if gpu_devices and gpu not in ("all", "none", ""):
        env["CUDA_VISIBLE_DEVICES"] = gpu_devices
    elif gpu == "none":
        env["CUDA_VISIBLE_DEVICES"] = ""

    # NCCL topology — match spawn_vllm / VllmProcessHandle defaults so the
    # TP>1 conversion behaves like a real lane.
    if not nccl_p2p_available:
        env.setdefault("NCCL_P2P_DISABLE", "1")
    if tp > 1:
        env.setdefault("TORCH_NCCL_ASYNC_ERROR_HANDLING", "1")
        env.setdefault("NCCL_CUMEM_ENABLE", "0")
        env.setdefault("NCCL_TIMEOUT", "1800")

    for k, v in (env_overrides or {}).items():
        env[str(k)] = str(v)
    return env


def _kill_process_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass
    try:
        proc.wait(timeout=10)
    except Exception:  # noqa: BLE001
        pass


def _run_conversion_subprocess(
    cmd: list[str],
    env: dict[str, str],
    log_path: Path | None,
    timeout_s: float,
    cancel_event: threading.Event | None,
) -> bool:
    """Run the converter, polling for cancellation/timeout. True on exit 0."""
    log_file = None
    try:
        if log_path is not None:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_file = log_path.open("a", encoding="utf-8")
            sep = "=" * 72
            log_file.write(
                f"\n{sep}\n"
                f"  Sharded conversion — {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"  Command: {' '.join(cmd)}\n"
                f"{sep}\n\n"
            )
            log_file.flush()
        proc = subprocess.Popen(
            cmd,
            env=env,
            stdout=log_file or subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
            start_new_session=True,  # own process group → kill the whole TP tree
            text=True,
        )
    except Exception:
        logger.exception("[sharded] failed to launch converter")
        if log_file is not None:
            log_file.close()
        return False

    try:
        deadline = time.monotonic() + max(60.0, timeout_s)
        while True:
            try:
                rc: int | None = proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                rc = None
            if rc is not None:
                if rc == 0:
                    return True
                logger.error("[sharded] converter exited with code %d", rc)
                return False
            if cancel_event is not None and cancel_event.is_set():
                logger.info("[sharded] conversion cancelled — killing converter")
                _kill_process_group(proc)
                return False
            if time.monotonic() > deadline:
                logger.error("[sharded] conversion timed out after %.0fs — killing", timeout_s)
                _kill_process_group(proc)
                return False
    finally:
        if log_file is not None:
            log_file.close()


def _shard_files(directory: Path) -> list[Path]:
    files: list[Path] = []
    for suffix in ("*.safetensors", "*.bin", "*.pt"):
        files.extend(directory.glob(suffix))
    return files


def ensure_sharded_checkpoint(
    *,
    model: str,
    tensor_parallel_size: int,
    cache_root: str,
    vllm_binary: str = "vllm",
    hf_home: str | None = None,
    gpu_devices: str = "",
    dtype: str = "auto",
    quantization: str = "",
    trust_remote_code: bool = False,
    nccl_p2p_available: bool = False,
    max_file_size_bytes: int = DEFAULT_MAX_FILE_SIZE_BYTES,
    env_overrides: dict[str, str] | None = None,
    log_path: Path | None = None,
    timeout_s: float = 3600.0,
    cancel_event: threading.Event | None = None,
) -> Path | None:
    """Return a ready sharded checkpoint for ``(model, tp)``, building if needed.

    Idempotent and blocking. Loads the full checkpoint on GPU once to dump
    per-rank shards, so the caller must run it with the relevant GPUs free
    (e.g. right after calibration, or before the lane it precedes is spawned).
    Returns the checkpoint directory, or ``None`` on failure/cancellation —
    in which case the caller loads the full checkpoint as before.
    """
    tp = int(tensor_parallel_size)
    if tp < 2:
        return None
    if not cache_root:
        logger.warning("[sharded] no cache_root resolved; skipping conversion for %s", model)
        return None

    target = sharded_checkpoint_dir(cache_root, model, tp)
    if is_sharded_checkpoint_ready(target):
        return target

    if not _CONVERT_ENTRYPOINT.is_file():
        logger.error("[sharded] converter entrypoint missing: %s", _CONVERT_ENTRYPOINT)
        return None

    lock = _lock_for(target)
    if not lock.acquire(blocking=False):
        logger.info("[sharded] waiting for in-progress conversion of %s (tp=%d)", model, tp)
        lock.acquire()
    try:
        # Double-check after acquiring the lock — another caller may have just
        # finished while we were waiting.
        if is_sharded_checkpoint_ready(target):
            return target

        # Clear any partial output from a previously interrupted attempt.
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        target.mkdir(parents=True, exist_ok=True)

        python = resolve_vllm_python(vllm_binary)
        cmd = [
            python,
            str(_CONVERT_ENTRYPOINT),
            "--model",
            model,
            "--tensor-parallel-size",
            str(tp),
            "--output",
            str(target),
            "--dtype",
            dtype or "auto",
            "--max-file-size",
            str(int(max_file_size_bytes)),
        ]
        if quantization:
            cmd.extend(["--quantization", quantization])
        if trust_remote_code:
            cmd.append("--trust-remote-code")

        env = _build_convert_env(
            hf_home=hf_home,
            gpu_devices=gpu_devices,
            tp=tp,
            nccl_p2p_available=nccl_p2p_available,
            env_overrides=env_overrides,
        )

        logger.info("[sharded] converting %s → %s (tp=%d) via %s", model, target, tp, python)
        ok = _run_conversion_subprocess(cmd, env, log_path, timeout_s, cancel_event)
        if not ok:
            shutil.rmtree(target, ignore_errors=True)
            return None

        shards = _shard_files(target)
        if not shards:
            logger.error("[sharded] conversion produced no shard files in %s", target)
            shutil.rmtree(target, ignore_errors=True)
            return None

        # Marker is written last — its presence is the readiness contract.
        (target / _COMPLETION_MARKER).write_text(f"model={model}\ntp={tp}\n", encoding="utf-8")
        logger.info("[sharded] conversion complete: %s (%d shard files)", target, len(shards))
        return target
    finally:
        lock.release()
