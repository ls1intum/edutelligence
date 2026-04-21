"""Shared calibration engine for VRAM profiling.

Extracts the reusable calibration functions so they can be imported both by
the standalone CLI tool (``tools/calibrate_vram_profiles.py``) and by the
worker's startup flow (``main.py``).

The calibration process binary-searches upward for the maximum KV cache each
model can use (starting at ``_KV_CACHE_MIN_STEP_MB`` floor, searching up to
``_KV_CACHE_VRAM_CAP_RATIO`` of per-GPU VRAM with
±``_KV_CACHE_MIN_STEP_MB`` precision).  It measures real VRAM in awake and
sleeping states and persists the results to ``model_profiles.yml``.

VRAM decomposition (exact, no guessing)::

    base_residency_mb    = loaded_vram_mb  (weights + KV cache — full footprint)
    sleeping_residual_mb = measured directly after sleep
    kv_budget_mb         = kv_cache_sent_mb (stored for auditing only)

The scheduler uses ``base_residency_mb`` directly for calibrated profiles — it
does NOT add a separate KV estimate on top.  For uncalibrated profiles the
scheduler falls back to ``base_residency + estimated_kv``.
"""
from __future__ import annotations

import json
import logging
import math
import os
import signal
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import yaml

    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_VLLM = "vllm"
_READY_TIMEOUT_S = 600.0
_SLEEP_TIMEOUT_S = 120.0
_VLLM_STOP_TIMEOUT_S = 30.0
_VRAM_SETTLE_S = 4.0
_VRAM_SAMPLE_COUNT = 3
_VRAM_SAMPLE_INTERVAL_S = 1.0
_PROFILES_FILE = "model_profiles.yml"
_CALIBRATION_PORT = 11499
_KV_CACHE_MIN_STEP_MB = 1024.0  # binary search precision and safety margin
_KV_CACHE_VRAM_CAP_RATIO = 0.8  # fraction of total GPU VRAM used as KV search ceiling
_FAILED_COMMANDS_FILE = "calibration_failed_commands.txt"

# ---------------------------------------------------------------------------
# KV-cache size parsing
# ---------------------------------------------------------------------------


def _parse_kv_to_mb(value: str) -> float:
    """Parse a human-friendly size string to megabytes.

    ``'4G'`` → 4096.0, ``'512M'`` → 512.0, ``'1024'`` (bytes) → ~0.001.
    """
    v = (value or "").strip().upper()
    if v.endswith("G"):
        return float(v[:-1]) * 1024.0
    if v.endswith("M"):
        return float(v[:-1])
    if v.endswith("K"):
        return float(v[:-1]) / 1024.0
    return float(v) / (1024.0 * 1024.0)  # raw bytes


def _format_kv_mb(mb: float) -> str:
    """Format a megabyte value as a human-friendly KV cache size string.

    ``2048.0`` → ``'2G'``, ``1536.0`` → ``'1536M'``.
    """
    if mb >= 1024.0 and mb % 1024.0 == 0:
        return f"{int(mb / 1024)}G"
    return f"{int(mb)}M"


def _round_up_gb(mb: float) -> float:
    """Round *mb* up to the nearest whole gigabyte (1024 MB boundary)."""
    return math.ceil(mb / 1024.0) * 1024.0


# ---------------------------------------------------------------------------
# Failed-command blacklist
# ---------------------------------------------------------------------------


def _cmd_fingerprint(cmd: list[str]) -> str:
    """Build a canonical one-line string from a vLLM command list.

    Strips ``--host`` and ``--port`` (calibration infra, not model-specific)
    so that retries on a different port aren't falsely considered "new".
    """
    filtered: list[str] = []
    skip_next = False
    for i, tok in enumerate(cmd):
        if skip_next:
            skip_next = False
            continue
        if tok in ("--host", "--port"):
            skip_next = True
            continue
        filtered.append(tok)
    return " ".join(filtered)


def _load_failed_commands(failed_path: Path) -> set[str]:
    if not failed_path.exists():
        return set()
    return {
        line.strip()
        for line in failed_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }


def _record_failed_command(failed_path: Path, fingerprint: str) -> None:
    failed_path.parent.mkdir(parents=True, exist_ok=True)
    with failed_path.open("a", encoding="utf-8") as f:
        f.write(fingerprint + "\n")
    logger.info("  Blacklisted command → %s", failed_path)


# ---------------------------------------------------------------------------
# GPU VRAM helpers
# ---------------------------------------------------------------------------


def query_gpu_vram(
    gpu_indices: list[int] | None = None,
) -> dict[int, dict[str, float]]:
    """Return per-GPU VRAM snapshot.  *gpu_indices=None* means all GPUs."""
    raw = subprocess.check_output(
        [
            "nvidia-smi",
            "--query-gpu=index,memory.total,memory.used,memory.free",
            "--format=csv,noheader,nounits",
        ],
        text=True,
        timeout=30,
    )
    result: dict[int, dict[str, float]] = {}
    for line in raw.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 4:
            continue
        idx = int(parts[0])
        if gpu_indices is not None and idx not in gpu_indices:
            continue
        result[idx] = {
            "total_mb": float(parts[1]),
            "used_mb": float(parts[2]),
            "free_mb": float(parts[3]),
        }
    return result


def _total_used_mb(snapshot: dict[int, dict[str, float]]) -> float:
    return sum(v["used_mb"] for v in snapshot.values())


def sample_vram_mb(gpu_indices: list[int] | None) -> float:
    """Median VRAM used across target GPUs from *N* samples."""
    samples: list[float] = []
    for i in range(_VRAM_SAMPLE_COUNT):
        samples.append(_total_used_mb(query_gpu_vram(gpu_indices)))
        if i < _VRAM_SAMPLE_COUNT - 1:
            time.sleep(_VRAM_SAMPLE_INTERVAL_S)
    samples.sort()
    return samples[len(samples) // 2]


def parse_gpu_indices(gpu_devices: str) -> list[int] | None:
    """``'0,1'`` → ``[0, 1]``; ``''`` or ``'all'`` → ``None`` (all GPUs)."""
    gd = (gpu_devices or "").strip().lower()
    if not gd or gd == "all":
        return None
    return [int(x.strip()) for x in gd.split(",") if x.strip().isdigit()]


# ---------------------------------------------------------------------------
# HTTP helpers (stdlib only — no httpx dependency at calibration time)
# ---------------------------------------------------------------------------


def _http(
    method: str,
    url: str,
    body: dict | None = None,
    timeout_s: float = 30.0,
) -> tuple[int, Any]:
    payload = None
    headers: dict[str, str] = {"User-Agent": "logos-calibrate/1.0"}
    if body is not None:
        payload = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        url, data=payload, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read()
            parsed: Any = json.loads(raw) if raw else {}
            return resp.status, parsed
    except urllib.error.HTTPError as e:
        return e.code, {}
    except Exception:
        return 0, {}


def _get(url: str, timeout_s: float = 10.0) -> tuple[int, Any]:
    return _http("GET", url, timeout_s=timeout_s)


def _post(
    url: str, body: dict | None = None, timeout_s: float = 30.0
) -> tuple[int, Any]:
    return _http("POST", url, body=body, timeout_s=timeout_s)


# ---------------------------------------------------------------------------
# vLLM process lifecycle
# ---------------------------------------------------------------------------


def _build_vllm_cmd(
    plan: dict[str, Any],
    vllm_binary: str,
    host: str,
    port: int,
    kv_cache_memory_bytes: str,
) -> list[str]:
    """Build the vLLM command list without spawning a process."""
    model = plan["model"]
    tp = int(plan.get("tensor_parallel_size", 1))
    dtype = str(plan.get("dtype", "auto"))
    quant = str(plan.get("quantization") or "")
    max_model_len = plan.get("max_model_len")
    enforce_eager = bool(plan.get("enforce_eager", True))
    disable_custom_all_reduce = bool(plan.get("disable_custom_all_reduce", False))
    extra_args: list[str] = list(plan.get("extra_args") or [])
    kv_bytes = str(plan.get("kv_cache_memory_bytes") or kv_cache_memory_bytes)
    explicit_gmu = plan.get("gpu_memory_utilization")

    cmd = [
        vllm_binary,
        "serve",
        model,
        "--host",
        host,
        "--port",
        str(port),
        "--tensor-parallel-size",
        str(tp),
        "--dtype",
        dtype,
        "--kv-cache-memory-bytes",
        kv_bytes,
        "--enable-sleep-mode",
    ]
    if explicit_gmu is not None:
        cmd.extend(["--gpu-memory-utilization", str(explicit_gmu)])
    if max_model_len:
        cmd.extend(["--max-model-len", str(int(max_model_len))])
    if quant:
        cmd.extend(["--quantization", quant])
    if enforce_eager:
        cmd.append("--enforce-eager")
    if disable_custom_all_reduce:
        cmd.append("--disable-custom-all-reduce")
    cmd.extend(extra_args)
    return cmd


def spawn_vllm(
    plan: dict[str, Any],
    vllm_binary: str,
    host: str,
    port: int,
    log_path: Path,
    kv_cache_memory_bytes: str,
    *,
    nccl_p2p_available: bool = False,
    hf_home: str | None = None,
) -> tuple[subprocess.Popen[str], list[str]]:
    """Spawn vLLM and return ``(process, cmd_list)``."""
    tp = int(plan.get("tensor_parallel_size", 1))

    cmd = _build_vllm_cmd(plan, vllm_binary, host, port, kv_cache_memory_bytes)

    env = os.environ.copy()
    env["VLLM_SERVER_DEV_MODE"] = "1"
    # Keep venv tools (ninja etc.) visible even outside activated venv
    vllm_dir = str(Path(vllm_binary).resolve().parent)
    env["PATH"] = f"{vllm_dir}{os.pathsep}{env.get('PATH', '')}"

    # Override HF_HOME to load from tmpfs RAM cache if provided.
    if hf_home:
        env["HF_HOME"] = hf_home
        logger.info("  HF_HOME=%s (tmpfs RAM cache)", hf_home)

    # NCCL P2P: disabled by default (PCIe-only assumed).
    # Set nccl_p2p_available=True for NVLink setups.
    if not nccl_p2p_available:
        env.setdefault("NCCL_P2P_DISABLE", "1")
        logger.info(
            "  NCCL_P2P_DISABLE=1 (PCIe topology — no NVLink; "
            "set engines.vllm.nccl_p2p_available=true in config.yml to enable P2P)"
        )
    else:
        logger.info("  NCCL P2P enabled (NVLink topology)")

    # For tensor-parallel calibration runs (tp > 1), mirror the NCCL env vars
    # used by regular vLLM lanes so calibration matches production behaviour.
    if tp > 1:
        env.setdefault("TORCH_NCCL_ASYNC_ERROR_HANDLING", "1")
        env.setdefault("NCCL_CUMEM_ENABLE", "0")   # unreliable in Docker without NUMA config
        env.setdefault("NCCL_TIMEOUT", "1800")

    gpu_devices = str(plan.get("gpu_devices") or "")
    if gpu_devices and gpu_devices.lower() not in ("all", ""):
        env["CUDA_VISIBLE_DEVICES"] = gpu_devices

    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = log_path.open("w", encoding="utf-8")
    try:
        proc = subprocess.Popen(
            cmd, env=env, stdout=log_file, stderr=subprocess.STDOUT, text=True,
            start_new_session=True,
        )
    finally:
        log_file.close()

    logger.info("  Spawned PID=%d  log=%s", proc.pid, log_path)
    logger.info("  Command: %s", " ".join(cmd))
    return proc, cmd


def _kill_stale_vllm_workers() -> None:
    """Kill any orphaned ``VLLM::Worker`` or ``vllm`` processes.

    Scans ``/proc`` directly (no psutil dependency) for processes whose
    ``/proc/<pid>/comm`` contains ``vllm`` (case-insensitive) — this
    catches both the ``VLLM::Worker`` subprocesses and lingering ``vllm
    serve`` parents.
    """
    proc_root = Path("/proc")
    if not proc_root.exists():
        return  # not Linux
    killed = 0
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            cmdline = (entry / "cmdline").read_bytes().decode(
                "utf-8", errors="replace"
            )
        except Exception:
            continue
        # Match both "vllm serve ..." parents and "VLLM::Worker" children
        if "vllm" not in cmdline.lower():
            continue
        pid = int(entry.name)
        if pid == os.getpid():
            continue
        try:
            os.kill(pid, signal.SIGKILL)
            killed += 1
        except OSError:
            pass
    if killed:
        logger.info("  Killed %d stale vLLM process(es)", killed)
        time.sleep(_VRAM_SETTLE_S)  # let GPU memory release


def _read_log_tail(log_path: Path, max_lines: int = 40) -> str:
    """Read the last *max_lines* of a vLLM log file, or '' on failure."""
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        tail = lines[-max_lines:] if len(lines) > max_lines else lines
        return "\n".join(tail)
    except Exception:
        return ""

def stop_vllm(proc: subprocess.Popen[str]) -> None:
    """Stop a vLLM process and all its child workers.

    Uses process-group kill (enabled by ``start_new_session=True`` in
    ``spawn_vllm``) so orphaned ``VLLM::Worker`` subprocesses are
    cleaned up even when the parent has already crashed.
    """
    pgid: int | None = None
    try:
        pgid = os.getpgid(proc.pid)
    except OSError:
        pass  # process already gone

    if proc.poll() is None:
        # Parent still running — try graceful shutdown first
        if pgid is not None:
            try:
                os.killpg(pgid, signal.SIGTERM)
            except OSError:
                pass
        else:
            proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=_VLLM_STOP_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            pass  # fall through to SIGKILL below

    # Force-kill the entire process group to catch orphaned workers
    if pgid is not None:
        try:
            os.killpg(pgid, signal.SIGKILL)
        except OSError:
            pass  # already gone

    # Reap the main process
    try:
        proc.wait(timeout=10)
    except Exception:
        pass


def wait_ready(
    base_url: str,
    timeout_s: float,
    proc: subprocess.Popen[str],
    gpu_indices: list[int] | None = None,
) -> None:
    deadline = time.perf_counter() + timeout_s
    t_start = time.perf_counter()
    last_log = t_start - 25.0  # log at ~5 s, then every 30 s
    while time.perf_counter() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(
                f"vLLM exited before becoming ready (code={proc.poll()})"
            )
        status, _ = _get(f"{base_url}/health", timeout_s=5.0)
        if status == 200:
            return
        now = time.perf_counter()
        if now - last_log >= 30.0:
            elapsed = now - t_start
            vram_str = ""
            try:
                used = _total_used_mb(query_gpu_vram(gpu_indices))
                vram_str = f"  VRAM={used:.0f} MB"
            except Exception:
                pass
            logger.info(
                "        %.0fs — weights loaded, waiting for CUDA graph warmup%s",
                elapsed,
                vram_str,
            )
            last_log = now
        time.sleep(2.0)
    raise TimeoutError(f"vLLM not ready after {timeout_s:.0f}s")


def wait_sleep_state(
    base_url: str, target: bool, timeout_s: float
) -> None:
    deadline = time.perf_counter() + timeout_s
    while time.perf_counter() < deadline:
        status, payload = _get(f"{base_url}/is_sleeping", timeout_s=5.0)
        if status == 200 and isinstance(payload, dict):
            if bool(payload.get("is_sleeping")) is target:
                return
        time.sleep(0.5)
    raise TimeoutError(
        f"/is_sleeping did not reach {target} within {timeout_s:.0f}s"
    )


# ---------------------------------------------------------------------------
# Calibration logic
# ---------------------------------------------------------------------------


@dataclass
class CalibrationResult:
    model: str
    tensor_parallel_size: int
    gpu_devices: str
    kv_cache_sent_mb: float  # what we explicitly gave vLLM during calibration
    success: bool
    loaded_vram_mb: float = 0.0  # measured: total GPU delta while awake
    sleeping_residual_mb: float = 0.0  # measured: total GPU delta while sleeping
    base_residency_mb: float = 0.0  # = loaded_vram_mb (weights + KV, full footprint)
    calibrated_at: float = 0.0
    error: str = ""


def calibrate_model(
    plan: dict[str, Any],
    *,
    vllm_binary: str,
    port: int,
    log_dir: Path,
    sleep_level: int,
    ready_timeout_s: float,
    nccl_p2p_available: bool = False,
    hf_home: str | None = None,
) -> CalibrationResult:
    # Always force eager mode for calibration: CUDA graph capture is not
    # needed for VRAM measurement and can add 10-30 minutes of startup time.
    # The per-model production enforce_eager setting is irrelevant here.
    if not plan.get("enforce_eager"):
        logger.info(
            "  enforce_eager=True (forced for calibration — CUDA graph capture skipped)"
        )
        plan = {**plan, "enforce_eager": True}

    model = plan["model"]
    gpu_devices = str(plan.get("gpu_devices") or "")
    tp = int(plan.get("tensor_parallel_size", 1))
    gpu_indices = parse_gpu_indices(gpu_devices)
    host = "127.0.0.1"
    base_url = f"http://{host}:{port}"
    log_path = log_dir / f"{model.replace('/', '__')}.log"

    partial = CalibrationResult(
        model=model,
        tensor_parallel_size=tp,
        gpu_devices=gpu_devices,
        kv_cache_sent_mb=0.0,
        success=False,
    )

    logger.info("-" * 60)
    logger.info("Calibrating: %s", model)
    logger.info(
        "  tp=%d  gpu_devices=%s  sleep_level=%d",
        tp,
        gpu_devices or "all",
        sleep_level,
    )
    logger.info("-" * 60)

    # Phase 0 — Kill any orphaned vLLM workers from previous runs.
    # Without this, leaked GPU memory inflates the baseline and can cause
    # subsequent calibrations to OOM or hang.
    _kill_stale_vllm_workers()

    # Phase 1 — Baseline: measure before any model process exists.
    # Retry up to 3 times with a short delay — nvidia-smi can be temporarily
    # sluggish right after a previous heavy calibration run (GPU driver busy).
    logger.info("  [1/5] Baseline VRAM...")
    baseline_mb: float | None = None
    for _attempt in range(3):
        try:
            baseline_mb = sample_vram_mb(gpu_indices)
            break
        except Exception as exc:
            last_exc = exc
            if _attempt < 2:
                logger.warning("  nvidia-smi baseline attempt %d failed: %s — retrying in 15s", _attempt + 1, exc)
                time.sleep(15)
    if baseline_mb is None:
        partial.error = f"nvidia-smi baseline failed: {last_exc}"
        logger.warning("  ERROR: %s", partial.error)
        return partial
    logger.info("        baseline = %.0f MB", baseline_mb)

    # Compute VRAM cap for KV cache search.
    # Use per-GPU VRAM × tp so the cap reflects the GPUs actually used,
    # not all GPUs visible on the host.
    max_kv_mb = float("inf")
    try:
        gpu_snap = query_gpu_vram(gpu_indices)
        per_gpu_mb = min(v["total_mb"] for v in gpu_snap.values())
        effective_gpu_mb = per_gpu_mb * tp
        max_kv_mb = per_gpu_mb * _KV_CACHE_VRAM_CAP_RATIO
        logger.info(
            "  GPU VRAM = %.0f MB/GPU × tp=%d = %.0f MB effective, "
            "KV cache search cap (%.0f%%) = %.0f MB",
            per_gpu_mb, tp, effective_gpu_mb,
            _KV_CACHE_VRAM_CAP_RATIO * 100, max_kv_mb,
        )
    except Exception as exc:
        logger.warning(
            "  Could not query GPU VRAM for KV cache cap: %s — no cap applied", exc,
        )

    # Phase 2 — Find the maximum KV cache the model can use.
    #
    # 1. Probe the floor (_KV_CACHE_MIN_STEP_MB) to verify the model can
    #    start at all — if even the minimum KV cache OOMs, the model
    #    weights themselves exceed available GPU VRAM.
    # 2. Binary-search upward to find the maximum KV cache that still
    #    fits (±_KV_CACHE_MIN_STEP_MB precision).
    #
    # A per-model override (plan["kv_cache_memory_bytes"]) skips the
    # search and uses the fixed value.
    explicit_kv = plan.get("kv_cache_memory_bytes")
    if explicit_kv:
        # Per-model override — use as-is, no search
        kv_cache_sent_mb = _parse_kv_to_mb(str(explicit_kv))
        kv_search = False
        logger.info(
            "  [2/6] Using explicit kv_cache=%s (%.0f MB) — no search",
            explicit_kv, kv_cache_sent_mb,
        )
    else:
        kv_search = True
        kv_cache_sent_mb = max_kv_mb if max_kv_mb < float("inf") else 4096.0
        # Round down to whole GB
        kv_cache_sent_mb = math.floor(kv_cache_sent_mb / 1024.0) * 1024.0
        logger.info(
            "  [2/6] Searching max KV cache (floor=%.0f MB, "
            "ceiling=%.0f MB, step=%.0f MB)...",
            _KV_CACHE_MIN_STEP_MB, kv_cache_sent_mb, _KV_CACHE_MIN_STEP_MB,
        )

    failed_path = log_dir / _FAILED_COMMANDS_FILE
    failed_commands = _load_failed_commands(failed_path)

    def _try_start(kv_mb: float) -> subprocess.Popen[str] | None:
        """Try to start vLLM with the given KV cache.  Returns the
        running process on success, ``None`` on failure (process is
        cleaned up).  Blacklisted commands are skipped immediately."""
        kv_str = _format_kv_mb(kv_mb)
        planned = {**plan, "kv_cache_memory_bytes": kv_str}
        # Check the blacklist *before* spawning to avoid wasting time.
        fingerprint = _cmd_fingerprint(
            _build_vllm_cmd(planned, vllm_binary, host, port, kv_str)
        )
        if fingerprint in failed_commands:
            logger.warning(
                "        SKIP kv_cache=%s — command previously failed "
                "(remove line from %s to retry)",
                kv_str, failed_path,
            )
            return None
        proc, _ = spawn_vllm(
            planned,
            vllm_binary, host, port, log_path,
            kv_cache_memory_bytes=kv_str,
            nccl_p2p_available=nccl_p2p_available,
            hf_home=hf_home,
        )
        logger.info(
            "        Trying kv_cache=%s (%.0f MB, timeout=%.0fs)...",
            kv_str, kv_mb, ready_timeout_s,
        )
        t0 = time.perf_counter()
        try:
            wait_ready(base_url, ready_timeout_s, proc, gpu_indices)
            logger.info(
                "        OK kv_cache=%s ready in %.1fs",
                kv_str, time.perf_counter() - t0,
            )
            return proc
        except (RuntimeError, TimeoutError) as exc:
            log_tail = _read_log_tail(log_path)
            logger.warning(
                "        FAIL kv_cache=%s: %s", kv_str, exc,
            )
            if log_tail:
                logger.warning("  -- vLLM log tail --\n%s", log_tail)
            stop_vllm(proc)
            time.sleep(_VRAM_SETTLE_S)
            _record_failed_command(failed_path, fingerprint)
            failed_commands.add(fingerprint)
            return None

    proc: subprocess.Popen[str] | None = None

    if kv_search:
        search_lo = _KV_CACHE_MIN_STEP_MB  # 1 GB floor
        search_hi = kv_cache_sent_mb       # ceiling (80% of per-GPU VRAM)

        # Phase 2a: Probe floor and ceiling to bracket the binary search.
        #
        # The floor probe can fail for two distinct reasons:
        #   a) Model weights alone exceed GPU VRAM (truly doesn't fit).
        #   b) The model's native max_position_embeddings requires more KV
        #      cache than the floor — vLLM refuses to start because it
        #      cannot serve even one full-length request in the KV pool.
        #
        # To distinguish (a) from (b), probe the ceiling when the floor
        # fails.  If the ceiling works, the model fits but needs more KV
        # cache — binary-search downward from the ceiling to find the
        # minimum working KV size.
        logger.info("        Probing floor kv_cache=%s...", _format_kv_mb(search_lo))
        floor_proc = _try_start(search_lo)

        if floor_proc is not None:
            # Floor works — binary-search upward from floor to ceiling.
            stop_vllm(floor_proc)
            time.sleep(_VRAM_SETTLE_S)
            best_kv = search_lo

            while search_hi - search_lo >= _KV_CACHE_MIN_STEP_MB:
                mid = _round_up_gb((search_lo + search_hi) / 2.0)
                if mid <= search_lo:
                    break
                proc = _try_start(mid)
                if proc is not None:
                    best_kv = mid
                    stop_vllm(proc)
                    time.sleep(_VRAM_SETTLE_S)
                    proc = None
                    search_lo = mid
                else:
                    search_hi = mid - _KV_CACHE_MIN_STEP_MB
        else:
            # Floor failed — probe the ceiling before giving up.
            logger.info(
                "        Floor probe failed — probing ceiling kv_cache=%s "
                "to check if model fits with more KV cache...",
                _format_kv_mb(search_hi),
            )
            ceil_proc = _try_start(search_hi)
            if ceil_proc is None:
                partial.error = (
                    f"Model cannot start with floor KV cache "
                    f"{_format_kv_mb(_KV_CACHE_MIN_STEP_MB)} nor ceiling "
                    f"{_format_kv_mb(kv_cache_sent_mb)} on tp={tp}. "
                    f"Model weights likely exceed available GPU VRAM."
                )
                logger.warning("  ERROR: %s", partial.error)
                return partial

            # Ceiling works — binary-search downward to find the minimum
            # KV cache that satisfies the model's max_position_embeddings.
            stop_vllm(ceil_proc)
            time.sleep(_VRAM_SETTLE_S)
            best_kv = search_hi

            while search_hi - search_lo >= _KV_CACHE_MIN_STEP_MB:
                mid = _round_up_gb((search_lo + search_hi) / 2.0)
                if mid >= search_hi:
                    break
                proc = _try_start(mid)
                if proc is not None:
                    # Works at this size — try even lower
                    best_kv = mid
                    stop_vllm(proc)
                    time.sleep(_VRAM_SETTLE_S)
                    proc = None
                    search_hi = mid
                else:
                    # Too small — minimum is higher
                    search_lo = mid + _KV_CACHE_MIN_STEP_MB

        kv_cache_sent_mb = best_kv
        logger.info(
            "  KV cache search result: best_working=%.0f MB (search range exhausted, "
            "precision=%.0f MB)",
            best_kv, _KV_CACHE_MIN_STEP_MB,
        )

        # Start vLLM at the final KV size for measurement
        proc = _try_start(kv_cache_sent_mb)
        if proc is None:
            partial.error = (
                f"Model failed to start at final KV cache "
                f"{_format_kv_mb(kv_cache_sent_mb)} on tp={tp}"
            )
            logger.warning("  ERROR: %s", partial.error)
            return partial
    else:
        # Fixed KV cache — single attempt
        proc = _try_start(kv_cache_sent_mb)
        if proc is None:
            partial.error = (
                f"Model failed to start with KV cache "
                f"{_format_kv_mb(kv_cache_sent_mb)} on tp={tp}"
            )
            logger.warning("  ERROR: %s", partial.error)
            return partial

    partial.kv_cache_sent_mb = kv_cache_sent_mb

    try:
        # Phase 3 — Measure awake VRAM
        logger.info(
            "  [3/6] Measuring awake VRAM (settling %.0fs)...", _VRAM_SETTLE_S
        )
        time.sleep(_VRAM_SETTLE_S)
        try:
            awake_total_mb = sample_vram_mb(gpu_indices)
        except Exception as exc:
            partial.error = f"nvidia-smi awake failed: {exc}"
            logger.warning("  ERROR: %s", partial.error)
            return partial
        loaded_vram_mb = max(awake_total_mb - baseline_mb, 0.0)
        # base_residency_mb is the full loaded footprint (weights + KV).
        # The scheduler uses it directly — no separate KV addition on top.
        base_residency_mb = loaded_vram_mb
        logger.info(
            "        awake total = %.0f MB  →  loaded delta = %.0f MB",
            awake_total_mb,
            loaded_vram_mb,
        )
        logger.info(
            "        base_residency = %.0f MB  (= loaded, includes %.0f MB KV)",
            base_residency_mb,
            kv_cache_sent_mb,
        )

        # Phase 4 — Sleep the model
        logger.info("  [4/6] Sleeping model (level=%d)...", sleep_level)
        sleep_url = f"{base_url}/sleep?level={sleep_level}"
        status, _ = _post(sleep_url, timeout_s=_SLEEP_TIMEOUT_S)
        if status not in (200, 204):
            partial.error = f"/sleep returned HTTP {status}"
            logger.warning("  ERROR: %s", partial.error)
            return partial
        try:
            wait_sleep_state(base_url, True, _SLEEP_TIMEOUT_S)
        except TimeoutError as exc:
            partial.error = str(exc)
            logger.warning("  ERROR: %s", partial.error)
            return partial

        # Phase 5 — Measure sleeping VRAM (independent observation)
        logger.info(
            "  [5/6] Measuring sleeping VRAM (settling %.0fs)...", _VRAM_SETTLE_S
        )
        time.sleep(_VRAM_SETTLE_S)
        try:
            sleeping_total_mb = sample_vram_mb(gpu_indices)
        except Exception as exc:
            partial.error = f"nvidia-smi sleep failed: {exc}"
            logger.warning("  ERROR: %s", partial.error)
            return partial
        sleeping_residual_mb = max(sleeping_total_mb - baseline_mb, 0.0)
        logger.info(
            "        sleeping total = %.0f MB  →  sleeping delta = %.0f MB",
            sleeping_total_mb,
            sleeping_residual_mb,
        )

        logger.info("  Results:")
        logger.info(
            "    base_residency_mb    = %.0f MB  (= full loaded VRAM, weights + KV)",
            base_residency_mb,
        )
        logger.info(
            "    kv_budget_mb         = %.0f MB  (KV portion, for auditing)",
            kv_cache_sent_mb,
        )
        logger.info(
            "    sleeping_residual_mb = %.0f MB  (measured independently)",
            sleeping_residual_mb,
        )
        logger.info(
            "    Scheduler uses base_residency directly — no KV added on top",
        )

        return CalibrationResult(
            model=model,
            tensor_parallel_size=tp,
            gpu_devices=gpu_devices,
            kv_cache_sent_mb=kv_cache_sent_mb,
            success=True,
            loaded_vram_mb=loaded_vram_mb,
            sleeping_residual_mb=sleeping_residual_mb,
            base_residency_mb=base_residency_mb,
            calibrated_at=time.time(),
        )

    finally:
        logger.info("  Stopping vLLM...")
        stop_vllm(proc)
        # Let the GPU release memory before the next model
        logger.info("  Waiting %.0fs for GPU memory release...", _VRAM_SETTLE_S)
        time.sleep(_VRAM_SETTLE_S)


# ---------------------------------------------------------------------------
# Profile persistence (mirrors ModelProfileRegistry format)
# ---------------------------------------------------------------------------


def result_to_profile_dict(r: CalibrationResult) -> dict[str, Any]:
    """Build a profile dict compatible with ``ModelProfileRecord.to_dict()``.

    ``base_residency_mb`` is the full loaded VRAM (weights + KV cache).
    The planner uses it directly — no separate KV addition for calibrated profiles.
    ``kv_budget_mb`` is stored for auditing only.
    """
    return {
        "loaded_vram_mb": round(r.loaded_vram_mb, 1),
        "sleeping_residual_mb": round(r.sleeping_residual_mb, 1),
        "disk_size_bytes": None,
        "base_residency_mb": round(r.base_residency_mb, 1),
        "kv_budget_mb": round(r.kv_cache_sent_mb, 1),
        "engine": "vllm",
        "observed_gpu_memory_utilization": None,
        "min_gpu_memory_utilization_to_load": None,
        "tensor_parallel_size": r.tensor_parallel_size,
        "kv_per_token_bytes": None,
        "max_context_length": None,
        "measurement_count": 1,
        "last_measured_epoch": r.calibrated_at,
        "residency_source": "calibrated",
        # Not part of ModelProfileRecord but useful for auditing
        "_calibration_kv_cache_mb": round(r.kv_cache_sent_mb, 1),
        # Discovered KV cache size for use by the lane manager at runtime
        "calibration_kv_cache_memory_bytes": _format_kv_mb(r.kv_cache_sent_mb),
    }


def load_existing_profiles(profiles_path: Path) -> dict[str, Any]:
    if not profiles_path.exists():
        return {}
    try:
        with profiles_path.open() as f:
            data = yaml.safe_load(f) or {}
        return dict(data.get("model_profiles") or {})
    except Exception as exc:
        logger.warning(
            "Could not parse existing profiles (%s): %s", profiles_path, exc
        )
        return {}


def save_profiles(profiles_path: Path, profiles: dict[str, Any]) -> None:
    profiles_path.parent.mkdir(parents=True, exist_ok=True)
    with profiles_path.open("w") as f:
        yaml.safe_dump(
            {"model_profiles": profiles}, f, default_flow_style=False
        )


# ---------------------------------------------------------------------------
# Config parsing (mirrors models.py LogosConfig._parse_capabilities)
# ---------------------------------------------------------------------------


def plans_from_config(config_path: Path) -> list[dict[str, Any]]:
    """Read ``capabilities_models`` from *config.yml* and return calibration plans."""
    with config_path.open() as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}

    logos = raw.get("logos") or {}
    caps_raw = logos.get("capabilities_models") or []
    caps_overrides: dict[str, dict] = dict(
        logos.get("capabilities_overrides") or {}
    )
    vllm_model_overrides: dict[str, dict] = (
        (raw.get("engines") or {}).get("vllm") or {}
    ).get("model_overrides") or {}

    plans: list[dict[str, Any]] = []
    for entry in caps_raw:
        if isinstance(entry, str):
            plan: dict[str, Any] = {"model": entry}
        elif isinstance(entry, dict):
            plan = dict(entry)
            # config format: top-level key is the model name when no "model:" key
            if "model" not in plan:
                model_name = next(iter(plan), None)
                if model_name:
                    plan = {**plan, "model": model_name}
        else:
            continue

        model = plan.get("model", "")
        if not model:
            continue

        # Merge capabilities_overrides (don't override explicit plan values)
        for k, v in (caps_overrides.get(model) or {}).items():
            plan.setdefault(k, v)

        # Merge vllm model_overrides (quantization, disable_custom_all_reduce, etc.)
        for k, v in (vllm_model_overrides.get(model) or {}).items():
            # Only merge fields relevant to calibration (skip runtime-only flags)
            if k in (
                "quantization",
                "dtype",
                "enforce_eager",
                "max_model_len",
                "disable_custom_all_reduce",
            ):
                plan.setdefault(k, v)

        plans.append(plan)

    return plans


# ---------------------------------------------------------------------------
# High-level auto-calibration for use by main.py
# ---------------------------------------------------------------------------


def _max_tp_for_plan(plan: dict[str, Any], available_gpus: int) -> int:
    """Return the maximum tensor_parallel_size allowed for *plan*."""
    gpu_devices = str(plan.get("gpu_devices") or "").strip().lower()
    if not gpu_devices or gpu_devices == "all":
        return available_gpus
    return len([x for x in gpu_devices.split(",") if x.strip().isdigit()])


def _try_calibrate(
    plan: dict[str, Any],
    *,
    vllm_binary: str,
    port: int,
    log_dir: Path,
    sleep_level: int,
    ready_timeout_s: float,
    nccl_p2p_available: bool = False,
    hf_home: str | None = None,
) -> CalibrationResult:
    """Call ``calibrate_model`` with exception → failure conversion."""
    model_name = plan["model"]
    try:
        return calibrate_model(
            plan,
            vllm_binary=vllm_binary,
            port=port,
            log_dir=log_dir,
            sleep_level=sleep_level,
            ready_timeout_s=ready_timeout_s,
            nccl_p2p_available=nccl_p2p_available,
            hf_home=hf_home,
        )
    except Exception as exc:
        logger.warning("Calibration failed for %s: %s", model_name, exc)
        return CalibrationResult(
            model=model_name,
            tensor_parallel_size=int(plan.get("tensor_parallel_size", 1)),
            gpu_devices=str(plan.get("gpu_devices") or ""),
            kv_cache_sent_mb=0.0,
            success=False,
            error=str(exc),
        )


def auto_calibrate_models(
    uncalibrated: list[str],
    config_path: Path,
    state_dir: Path,
    *,
    vllm_binary: str = _DEFAULT_VLLM,
    port: int = _CALIBRATION_PORT,
    sleep_level: int = 1,
    ready_timeout_s: float = _READY_TIMEOUT_S,
    nccl_p2p_available: bool = False,
    model_cache: Any | None = None,
) -> dict[str, CalibrationResult]:
    """Calibrate a list of uncalibrated models and persist results.

    Returns a dict mapping model_name -> CalibrationResult.
    Only calibrates models in the *uncalibrated* list.

    Uses a **max-first strategy**: each model is first tested with the
    maximum available ``tensor_parallel_size`` to quickly verify it can
    run at all.  If that succeeds, a binary search finds the smallest
    tp that still works, saving GPU resources at runtime.
    """
    # Load plans from config
    if config_path.exists():
        all_plans = plans_from_config(config_path)
    else:
        all_plans = []

    # Build a lookup of plans by model name
    plan_by_model: dict[str, dict[str, Any]] = {}
    for p in all_plans:
        plan_by_model[p["model"]] = p

    # Filter to uncalibrated models only; create minimal plans for unknown ones
    plans: list[dict[str, Any]] = []
    for name in uncalibrated:
        if name in plan_by_model:
            plans.append(plan_by_model[name])
        else:
            plans.append({"model": name})

    if not plans:
        logger.info("No uncalibrated models to calibrate.")
        return {}

    # Detect available GPU count for tp escalation
    try:
        gpu_snap = query_gpu_vram()
        available_gpus = len(gpu_snap)
    except Exception:
        available_gpus = 1

    profiles_path = state_dir / _PROFILES_FILE
    existing_profiles = load_existing_profiles(profiles_path)
    log_dir = state_dir / "calibration_logs"

    logger.info(
        "Auto-calibration: %d model(s) to calibrate, %d GPU(s) available",
        len(plans), available_gpus,
    )
    for p in plans:
        logger.info(
            "  %s  tp=%s  gpu_devices=%s",
            p["model"],
            p.get("tensor_parallel_size", 1),
            p.get("gpu_devices") or "all",
        )

    cal_kwargs = dict(
        vllm_binary=vllm_binary,
        port=port,
        log_dir=log_dir,
        sleep_level=sleep_level,
        ready_timeout_s=ready_timeout_s,
        nccl_p2p_available=nccl_p2p_available,
    )

    results: dict[str, CalibrationResult] = {}

    for plan in plans:
        model_name = plan["model"]
        original_tp = int(plan.get("tensor_parallel_size", 1))
        max_tp = _max_tp_for_plan(plan, available_gpus)

        # Cache this model in tmpfs before calibration so vLLM loads from RAM.
        # Only one model is ever in the cache at a time — evict after calibration.
        hf_home: str | None = None
        if model_cache is not None and getattr(model_cache, "enabled", False):
            logger.info("  [RAM cache] Caching %s into tmpfs before calibration...", model_name)
            hf_home = model_cache.ensure_cached_sync(model_name) or None
            if hf_home:
                is_tmpfs_path = hasattr(model_cache, "_cache_hub") and hf_home == str(model_cache._cache_hub.parent)
                if is_tmpfs_path:
                    logger.info("  [RAM cache] %s → loading from tmpfs (calibration will be faster)", model_name)
                else:
                    logger.info("  [RAM cache] %s → loading from disk (tmpfs full or model not found)", model_name)
                    hf_home = None  # don't override HF_HOME if we're not using tmpfs

        model_cal_kwargs = {**cal_kwargs, "hf_home": hf_home}

        # ----------------------------------------------------------
        # Strategy: "max-first, then search down"
        #
        # 1. Try with max tp first to quickly verify whether the
        #    model can run at all.  A model that cannot even load
        #    with all GPUs available will never work — fail fast.
        # 2. If max tp succeeds, binary-search downward to find the
        #    smallest tp that still works (to save GPU resources at
        #    runtime).
        # 3. If max tp == original tp (only one option), just try it.
        # ----------------------------------------------------------

        tp = max_tp
        current_plan = {**plan, "tensor_parallel_size": tp}
        result = _try_calibrate(current_plan, **model_cal_kwargs)

        # Auto-retry with --trust-remote-code when vLLM demands it.
        _err = result.error or ""
        if not result.success and "trust_remote_code=True" in _err:
            logger.info(
                "  %s requires trust_remote_code — adding flag and retrying",
                model_name,
            )
            extra = list(plan.get("extra_args") or [])
            if "--trust-remote-code" not in extra:
                extra.append("--trust-remote-code")
            plan = {**plan, "extra_args": extra}
            current_plan = {**plan, "tensor_parallel_size": tp}
            result = _try_calibrate(current_plan, **model_cal_kwargs)

        # If even max tp fails, the model cannot run — skip it.
        _fatal = (
            "does not recognize this architecture" in (result.error or "")
            or "Cannot access gated repo" in (result.error or "")
        )
        if not result.success or _fatal:
            if tp > original_tp:
                logger.warning(
                    "  %s failed even with max tp=%d — skipping",
                    model_name, tp,
                )
            results[model_name] = result
            if not result.success:
                logger.warning(
                    "Calibration unsuccessful for %s: %s",
                    model_name,
                    result.error,
                )
            if model_cache is not None and getattr(model_cache, "enabled", False):
                logger.info("  [RAM cache] Evicting %s from tmpfs (calibration done)", model_name)
                model_cache.evict(model_name)
            continue

        # Max tp succeeded — now binary-search down to find minimum tp.
        if tp > original_tp:
            logger.info(
                "  %s works at tp=%d — searching for minimum tp (from %d)",
                model_name, tp, original_tp,
            )
        best_result = result
        best_tp = tp

        # Binary search: try progressively smaller tp values.
        # tp must be a power of 2 in vLLM, so we halve each step.
        low_tp = original_tp
        high_tp = tp
        while low_tp < high_tp:
            mid_tp = high_tp // 2
            if mid_tp < low_tp:
                break
            logger.info(
                "  %s trying tp=%d (search range %d–%d)",
                model_name, mid_tp, low_tp, high_tp,
            )
            mid_plan = {**plan, "tensor_parallel_size": mid_tp}
            mid_result = _try_calibrate(mid_plan, **model_cal_kwargs)
            if mid_result.success:
                best_result = mid_result
                best_tp = mid_tp
                high_tp = mid_tp
            else:
                low_tp = mid_tp * 2

        result = best_result
        tp = best_tp

        if tp != int(plan.get("tensor_parallel_size", 1)):
            logger.info(
                "  %s optimal tp=%d (configured=%d, max=%d)",
                model_name, tp, original_tp, max_tp,
            )

        results[model_name] = result

        if result.success:
            existing_profiles[model_name] = result_to_profile_dict(result)
            # Persist after every success so a later failure doesn't lose results
            save_profiles(profiles_path, existing_profiles)
            logger.info("  Saved profile for %s → %s", model_name, profiles_path)
        else:
            logger.warning(
                "Calibration unsuccessful for %s: %s",
                model_name,
                result.error,
            )

        if model_cache is not None and getattr(model_cache, "enabled", False):
            logger.info("  [RAM cache] Evicting %s from tmpfs (calibration done, freeing space)", model_name)
            model_cache.evict(model_name)

    ok = [r for r in results.values() if r.success]
    fail = [r for r in results.values() if not r.success]
    logger.info(
        "Auto-calibration complete: %d/%d succeeded", len(ok), len(ok) + len(fail)
    )
    if fail:
        for r in fail:
            logger.warning("  Failed: %s — %s", r.model, r.error)

    return results
