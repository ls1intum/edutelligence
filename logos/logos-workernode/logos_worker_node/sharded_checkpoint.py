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
  * a rejection record (a per-model marker written when the vLLM loader
    refuses a converted checkpoint — so the same unusable conversion is not
    re-run on every spawn while the engine build is unchanged),
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

import importlib.metadata
import json
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
# Per-model record of conversions the vLLM loader refused to load. Lives next
# to (not inside) the tp directories: the rejected checkpoint is deleted by
# the time the rejection is recorded, and the record must survive an operator
# deleting the tp directory manually — the very action that previously just
# triggered a re-conversion of the same unusable output.
_REJECTED_MARKER = ".logos_sharded_rejected.json"
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


def invalidate_sharded_checkpoint(directory: Path) -> bool:
    """Discard a sharded checkpoint that vLLM refused to load.

    The conversion can complete — shard files written, marker placed — and
    still produce something the loader rejects, e.g. a quantization whose
    weight layout does not survive the round trip (a tensor comes back a
    factor of the packing width too small). Nothing in the produced files says
    so; only a lane trying to serve them finds out. Removing the directory
    puts the model back on the full checkpoint; the rejection is also recorded
    (see :func:`is_sharded_checkpoint_rejected`) so that a later conversion
    against a newer vLLM, or a forced retry via deleting the record, is what
    re-arms the conversion — not every spawn re-running it and reproducing
    the same unusable shards.

    Returns True when something was removed.
    """
    with _lock_for(directory):
        if not directory.exists():
            return False
        shutil.rmtree(directory, ignore_errors=True)
        # rmtree(ignore_errors=True) hides a partial failure, and a directory
        # that still has the marker would be picked up as ready again.
        if is_sharded_checkpoint_ready(directory):
            logger.error("[sharded] could not fully remove %s — it still looks ready", directory)
            return False
        logger.warning("[sharded] discarded unusable sharded checkpoint: %s", directory)
        _record_sharded_rejection(directory)
        return True


def _sharded_rejected_marker(directory: Path) -> Path:
    """The per-model rejection record next to ``directory`` (a tp dir)."""
    return directory.parent / _REJECTED_MARKER


def _current_engine_versions() -> dict[str, str]:
    """vLLM/torch versions of the worker venv, best effort.

    The rejection verdict is pinned to the engine build that produced the
    unusable shards: a different build may round-trip a layout the old one
    could not. A package that is not importable here is simply omitted — the
    comparison then only sees the fields that could be read.
    """
    versions: dict[str, str] = {}
    for pkg in ("vllm", "torch"):
        try:
            versions[pkg] = importlib.metadata.version(pkg)
        except importlib.metadata.PackageNotFoundError:
            pass
    return versions


def _record_sharded_rejection(directory: Path) -> None:
    """Record that the vLLM loader refused the converted checkpoint at ``directory``.

    Best effort: failing to record only loses the "do not re-convert" memory,
    never the lane (which already falls back to the full checkpoint).
    """
    path = _sharded_rejected_marker(directory)
    try:
        record: dict = {}
        if path.is_file():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    record = loaded
            except (OSError, ValueError):
                logger.warning("[sharded] unreadable rejection record %s — replacing", path)
        entry: dict[str, str] = dict(_current_engine_versions())
        entry["at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        record[directory.name] = entry
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
        logger.info(
            "[sharded] recorded that the vLLM loader rejected %s (engine: %s); re-conversion "
            "is skipped while that build is unchanged — delete %s to force a retry",
            directory,
            ", ".join(f"{k}={v}" for k, v in sorted(entry.items()) if k != "at") or "unknown",
            path,
        )
    except OSError:
        logger.warning("[sharded] could not record rejection for %s", directory, exc_info=True)


def is_sharded_checkpoint_rejected(directory: Path) -> bool:
    """True when the vLLM loader refused this (model, tp) conversion and the
    engine build is unchanged since.

    A conversion can report success — shards written, marker placed — and
    still emit something the loader rejects (a quantized weight layout that
    does not survive the sharded_state round trip). The rejection is recorded
    in the per-model marker (see :func:`_record_sharded_rejection`), so the
    verdict survives both the discarded tp directory and worker restarts.
    While the recorded vLLM/torch versions still match the worker's,
    re-converting would only reproduce the same unusable shards, so the
    conversion is skipped and the lane serves the full checkpoint. A recorded
    version that differs from the current one clears the verdict — the newer
    build may round-trip the layout. A version that cannot be resolved on
    either side cannot prove the build changed, so the rejection stands (the
    lane still comes up, just on the slower full-checkpoint load).

    Deleting the marker (or the whole per-model cache directory) forces a
    conversion attempt on the next trigger.
    """
    path = _sharded_rejected_marker(directory)
    try:
        if not path.is_file():
            return False
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(record, dict):
        return False
    entry = record.get(directory.name)
    if not isinstance(entry, dict):
        return False
    current = _current_engine_versions()
    for key, recorded in entry.items():
        if key == "at":
            continue
        current_value = current.get(key)
        if current_value is not None and str(recorded) != str(current_value):
            return False
    return True


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
    if is_sharded_checkpoint_rejected(target):
        logger.info(
            "[sharded] conversion for %s (tp=%d) was already rejected by the vLLM loader under "
            "the current engine build — serving the full checkpoint instead of re-converting; "
            "delete %s to force a retry",
            model,
            tp,
            _sharded_rejected_marker(target),
        )
        return None

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
