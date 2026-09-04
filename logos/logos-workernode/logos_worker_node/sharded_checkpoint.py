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
_REJECTION_SUFFIX = ".rejected"
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


def invalidate_sharded_checkpoint(directory: Path, vllm_version: str = "", reason: str = "") -> bool:
    """Discard a sharded checkpoint that vLLM refused to load.

    The conversion can complete — shard files written, marker placed — and
    still produce something the loader rejects, e.g. a quantization whose
    weight layout does not survive the round trip (a tensor comes back a
    factor of the packing width too small). Nothing in the produced files says
    so; only a lane trying to serve them finds out. Removing the directory
    puts the model back on the full checkpoint and lets a later conversion,
    against a newer vLLM, try again.

    The rejection is also recorded alongside the (now-gone) directory, keyed
    on ``vllm_version`` and ``reason`` when provided, so a later spawn — and a
    later worker process — sees that this (model, tp) was rejected and does not
    spend minutes rebuilding a conversion the loader is going to refuse again.
    See :func:`rejection_state`.

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
        # Record *after* a confirmed removal, so a no-op invalidation (nothing
        # cached) never plants a rejection for a checkpoint that never was.
        record_rejection(directory, vllm_version=vllm_version, reason=reason)
        return True


def rejection_path(directory: Path) -> Path:
    """Path of the rejection record for ``directory``.

    A *sibling* of the checkpoint directory (``tp<N>.rejected``), deliberately
    outside it: :func:`invalidate_sharded_checkpoint` ``rmtree``s the directory
    on removal, so the record has to live beside it to outlast the very
    conversion it describes.
    """
    return directory.with_name(directory.name + _REJECTION_SUFFIX)


def current_vllm_version() -> str:
    """The vLLM version installed in this worker, or ``""`` when unknown.

    The rejection record is keyed on this, so a (model, tp) that one vLLM
    refuses to load is remembered for exactly that version and re-tried once it
    changes (an upstream fix may have landed). ``""`` — rather than an
    exception — is returned when vLLM is not importable or has no metadata, so
    callers can treat it uniformly as "version unknown".
    """
    try:
        import importlib.metadata as md

        return md.version("vllm") or ""
    except Exception:  # noqa: BLE001
        # Missing metadata (vLLM absent) must read as "unknown", not crash spawn.
        return ""


def vllm_version_for_python(python: str) -> str:
    """The vLLM version as seen by ``python``'s interpreter, ``""`` when unknown.

    ``resolve_vllm_python`` deliberately supports a vLLM installed in a
    *different* virtualenv from this worker, and it is that vLLM — not this
    process's — that loads (or refuses) a sharded checkpoint. So the version a
    rejection is scoped to must be the one the *configured* interpreter
    reports. A foreign interpreter is asked with a small subprocess; when the
    interpreter is this process's own (or not given) the version is read
    in-process via :func:`current_vllm_version` — the same answer, without a fork.
    """
    if not python or python == sys.executable:
        return current_vllm_version()
    try:
        proc = subprocess.run(
            [python, "-c", "import importlib.metadata as m; print(m.version('vllm') or '')"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception:  # noqa: BLE001
        # A missing or broken foreign interpreter reads as "unknown" (→ skip),
        # never as a reason to keep re-converting.
        return ""
    return (proc.stdout or "").strip()


def record_rejection(directory: Path, vllm_version: str = "", reason: str = "") -> bool:
    """Persist that ``directory``'s conversion was rejected by the loader.

    Best-effort: failing to record only reverts to the pre-record behaviour
    (the next spawn re-converts and re-rejects) and must not turn an otherwise
    successful invalidation into a failure. The record is written atomically
    (temp file + rename) so a crash mid-write can never leave a torn sidecar
    that :func:`read_rejection` would misparse.
    """
    payload = {
        "vllm_version": vllm_version or "",
        "reason": reason or "",
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    path = rejection_path(directory)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, path)
        return True
    except OSError:
        logger.exception("[sharded] could not record rejection for %s", directory)
        return False


def read_rejection(directory: Path) -> dict | None:
    """The rejection record for ``directory``, or ``None`` if absent/corrupt."""
    try:
        with open(rejection_path(directory), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def rejection_state(directory: Path, current_version: str | None = None, vllm_binary: str | None = None) -> str:
    """Whether a previously-recorded rejection of ``directory`` should stand.

    Returns one of:

      * ``"none"``  — no rejection recorded; a conversion may proceed.
      * ``"skip"``  — a rejection is recorded for the current vLLM, or for a
        version that cannot be compared; do not re-convert, serve the full
        checkpoint instead.
      * ``"retry"`` — a rejection is recorded for a *different, known* vLLM;
        the sidecar is removed and a conversion may run again (an upstream fix
        may have landed since the rejection).

    ``current_version`` overrides the detected version when given (tests); pass
    ``""`` for an explicitly-unknown current version, ``None`` to detect it. When
    detecting, ``vllm_binary`` (the configured vLLM) names the interpreter to read
    the version from — the one that loads the checkpoint — else this worker's own
    version is used.

    The comparison is deliberately conservative: it retries only when *both*
    the recorded and current versions are known and differ. When either is
    unknown it skips, so the re-conversion loop can never be reintroduced just
    because the version could not be determined.
    """
    rec = read_rejection(directory)
    if rec is None:
        return "none"
    recorded = str(rec.get("vllm_version") or "").strip()
    if current_version is None:
        # When the caller names the configured binary, scope to the version of the
        # interpreter that actually loads the checkpoint, not this worker's (a
        # separate-venv deployment runs a different vLLM under the hood).
        current_version = resolve_vllm_version(vllm_binary) if vllm_binary is not None else current_vllm_version()
    current = (current_version or "").strip()
    if recorded and current and recorded != current:
        # The vLLM that recorded the rejection is no longer the one serving —
        # the rejection may no longer hold. Clear it (idempotent: a sibling
        # lane may have done the same first) so the conversion is retried.
        try:
            rejection_path(directory).unlink(missing_ok=True)
        except OSError:
            pass
        return "retry"
    return "skip"


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


def resolve_vllm_version(vllm_binary: str) -> str:
    """The vLLM version of the interpreter that serves the configured binary.

    The single source of truth for the version a sharded-checkpoint rejection
    is scoped to: whatever loads the checkpoint runs under
    ``resolve_vllm_python(vllm_binary)``, so that is whose version we record and
    compare. In the common case (the configured vLLM is this worker's own) this
    is exactly :func:`current_vllm_version`; in a separate-venv deployment it is
    that other venv's version instead.
    """
    return vllm_version_for_python(resolve_vllm_python(vllm_binary))


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
    if rejection_state(target, vllm_binary=vllm_binary) == "skip":
        # A conversion for this (model, tp) was built and the loader rejected
        # it, for the vLLM that is installed now. Rebuilding it would only
        # reproduce the same bad shards after minutes of GPU time, so go
        # straight to the full checkpoint the caller would fall back to anyway.
        logger.info(
            "[sharded] %s (tp=%d) has a checkpoint the loader rejected for this vLLM — "
            "not re-converting; caller serves the full checkpoint",
            model,
            tp,
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
