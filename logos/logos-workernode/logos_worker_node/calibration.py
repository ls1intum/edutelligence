"""Shared calibration engine for VRAM profiling.

Extracts the reusable calibration functions so they can be imported both by
the standalone CLI tool (``tools/calibrate_vram_profiles.py``) and by the
worker's startup flow (``main.py``).

The calibration process loads each model via vLLM with an explicit
``--kv-cache-memory-bytes``, measures real VRAM in awake and sleeping states,
and persists the results to ``model_profiles.yml``.

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
_DEFAULT_KV_CACHE = "4G"
_READY_TIMEOUT_S = 600.0
_SLEEP_TIMEOUT_S = 120.0
_VLLM_STOP_TIMEOUT_S = 30.0
_VRAM_SETTLE_S = 4.0
_VRAM_SAMPLE_COUNT = 3
_VRAM_SAMPLE_INTERVAL_S = 1.0
_PROFILES_FILE = "model_profiles.yml"
_CALIBRATION_PORT = 11499
_KV_CACHE_MIN_STEP_MB = 1024.0  # stop binary search when gap < 1 GB
_KV_CACHE_VRAM_CAP_RATIO = 0.8  # stop search when KV > 80% of total GPU VRAM

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


def spawn_vllm(
    plan: dict[str, Any],
    vllm_binary: str,
    host: str,
    port: int,
    log_path: Path,
    kv_cache_memory_bytes: str = _DEFAULT_KV_CACHE,
) -> subprocess.Popen[str]:
    model = plan["model"]
    tp = int(plan.get("tensor_parallel_size", 1))
    dtype = str(plan.get("dtype", "auto"))
    quant = str(plan.get("quantization") or "")
    max_model_len = plan.get("max_model_len")
    enforce_eager = bool(plan.get("enforce_eager", False))
    disable_custom_all_reduce = bool(plan.get("disable_custom_all_reduce", False))
    disable_nccl_p2p = bool(plan.get("disable_nccl_p2p", False))
    extra_args: list[str] = list(plan.get("extra_args") or [])
    # Per-model override for kv cache size (takes precedence over CLI default)
    kv_bytes = str(plan.get("kv_cache_memory_bytes") or kv_cache_memory_bytes)

    # When kv_cache_memory_bytes is set, omit --gpu-memory-utilization and let
    # vLLM default to 0.9. kv_cache_memory_bytes controls the KV pool size
    # directly; adding gpu_memory_utilization=0.1 caps total VRAM to 10% which
    # prevents the model weights from loading at all.
    # An explicit per-model override takes precedence.
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
    # disable_nccl_p2p is applied via NCCL_P2P_DISABLE env var below (not a vLLM CLI flag)
    cmd.extend(extra_args)

    env = os.environ.copy()
    env["VLLM_SERVER_DEV_MODE"] = "1"
    # Keep venv tools (ninja etc.) visible even outside activated venv
    vllm_dir = str(Path(vllm_binary).resolve().parent)
    env["PATH"] = f"{vllm_dir}{os.pathsep}{env.get('PATH', '')}"

    # For tensor-parallel calibration runs (tp > 1), mirror the NCCL env vars
    # used by regular vLLM lanes so calibration matches production behaviour.
    if tp > 1:
        env.setdefault("TORCH_NCCL_ASYNC_ERROR_HANDLING", "1")
        env.setdefault("NCCL_CUMEM_ENABLE", "0")   # unreliable in Docker without NUMA config
        env.setdefault("NCCL_TIMEOUT", "1800")
        if disable_nccl_p2p:
            env.setdefault("NCCL_P2P_DISABLE", "1")    # PCIe GPUs without NVLink hang on P2P init

    gpu_devices = str(plan.get("gpu_devices") or "")
    if gpu_devices and gpu_devices.lower() not in ("all", ""):
        env["CUDA_VISIBLE_DEVICES"] = gpu_devices

    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = log_path.open("w", encoding="utf-8")
    try:
        proc = subprocess.Popen(
            cmd, env=env, stdout=log_file, stderr=subprocess.STDOUT, text=True
        )
    finally:
        log_file.close()

    logger.info("  Spawned PID=%d  log=%s", proc.pid, log_path)
    logger.info("  Command: %s", " ".join(cmd))
    return proc


def _read_log_tail(log_path: Path, max_lines: int = 40) -> str:
    """Read the last *max_lines* of a vLLM log file, or '' on failure."""
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        tail = lines[-max_lines:] if len(lines) > max_lines else lines
        return "\n".join(tail)
    except Exception:
        return ""

def stop_vllm(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        return
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=_VLLM_STOP_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=10)


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
    kv_cache_memory_bytes: str = _DEFAULT_KV_CACHE,
) -> CalibrationResult:
    model = plan["model"]
    gpu_devices = str(plan.get("gpu_devices") or "")
    tp = int(plan.get("tensor_parallel_size", 1))
    gpu_indices = parse_gpu_indices(gpu_devices)
    host = "127.0.0.1"
    base_url = f"http://{host}:{port}"
    log_path = log_dir / f"{model.replace('/', '__')}.log"

    # The KV cache size we will allocate — per-model override or global default
    kv_bytes_str = str(plan.get("kv_cache_memory_bytes") or kv_cache_memory_bytes)
    kv_cache_sent_mb = _parse_kv_to_mb(kv_bytes_str)

    partial = CalibrationResult(
        model=model,
        tensor_parallel_size=tp,
        gpu_devices=gpu_devices,
        kv_cache_sent_mb=kv_cache_sent_mb,
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
    logger.info(
        "  kv_cache_memory_bytes=%s (%.0f MB) — known, used to derive base_residency",
        kv_bytes_str,
        kv_cache_sent_mb,
    )
    logger.info("-" * 60)

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

    # Compute VRAM cap for KV cache search (80% of total GPU VRAM)
    max_kv_mb = float("inf")
    try:
        gpu_snap = query_gpu_vram(gpu_indices)
        total_gpu_mb = sum(v["total_mb"] for v in gpu_snap.values())
        max_kv_mb = total_gpu_mb * _KV_CACHE_VRAM_CAP_RATIO
        logger.info(
            "  GPU total VRAM = %.0f MB, KV cache search cap (%.0f%%) = %.0f MB",
            total_gpu_mb, _KV_CACHE_VRAM_CAP_RATIO * 100, max_kv_mb,
        )
    except Exception as exc:
        logger.warning(
            "  Could not query GPU VRAM for KV cache cap: %s — no cap applied", exc,
        )

    # Phase 2 — Spawn vLLM and wait for readiness (with binary KV cache search)
    #
    # Binary search between current_kv_mb (low) and max_kv_mb (high).
    # On failure: move low up to midpoint.  On success: done.
    # Stops when the gap between low and high is < _KV_CACHE_MIN_STEP_MB,
    # at which point we try high (the cap) as a last resort.
    lo_mb = kv_cache_sent_mb
    hi_mb = max_kv_mb
    current_kv_mb = lo_mb

    while True:
        kv_bytes_str = _format_kv_mb(current_kv_mb)
        kv_cache_sent_mb = current_kv_mb
        partial.kv_cache_sent_mb = kv_cache_sent_mb

        proc = spawn_vllm(
            {**plan, "kv_cache_memory_bytes": kv_bytes_str},
            vllm_binary,
            host,
            port,
            log_path,
            kv_cache_memory_bytes=kv_bytes_str,
        )

        logger.info(
            "  [2/5] Waiting for vLLM ready (timeout=%.0fs, kv_cache=%s / %.0f MB)...",
            ready_timeout_s, kv_bytes_str, current_kv_mb,
        )
        t0 = time.perf_counter()
        try:
            wait_ready(base_url, ready_timeout_s, proc, gpu_indices)
            break  # vLLM is ready — proceed to measurement phases
        except RuntimeError as exc:
            # vLLM exited before becoming ready — log tail for visibility
            log_tail = _read_log_tail(log_path)
            logger.warning(
                "  vLLM startup failed with kv_cache=%s (%.0f MB): %s",
                kv_bytes_str, current_kv_mb, exc,
            )
            if log_tail:
                logger.warning("  ── vLLM log tail ──\n%s", log_tail)

            stop_vllm(proc)
            time.sleep(_VRAM_SETTLE_S)

            # Binary search: failed value becomes new lower bound
            lo_mb = current_kv_mb
            gap = hi_mb - lo_mb
            if gap < _KV_CACHE_MIN_STEP_MB:
                partial.error = (
                    f"KV cache search exhausted: {kv_bytes_str} failed, "
                    f"search range [{_format_kv_mb(lo_mb)}–{_format_kv_mb(hi_mb)}] "
                    f"narrower than {_KV_CACHE_MIN_STEP_MB:.0f} MB step "
                    f"({_KV_CACHE_VRAM_CAP_RATIO:.0%} VRAM cap = {max_kv_mb:.0f} MB)"
                )
                logger.warning("  %s", partial.error)
                return partial

            # Jump to midpoint (rounded up to nearest GB for clean values)
            mid = (lo_mb + hi_mb) / 2.0
            next_kv_mb = max(lo_mb + _KV_CACHE_MIN_STEP_MB, _round_up_gb(mid))
            next_kv_mb = min(next_kv_mb, hi_mb)  # never exceed cap

            logger.info(
                "  Binary search: [%.0f–%.0f MB] → trying %s (%.0f MB)...",
                lo_mb, hi_mb, _format_kv_mb(next_kv_mb), next_kv_mb,
            )
            current_kv_mb = next_kv_mb
            continue
        except TimeoutError as exc:
            # Timeout is NOT retried — the model loaded but warmup took too long
            partial.error = str(exc)
            logger.warning("  ERROR: %s", partial.error)
            stop_vllm(proc)
            time.sleep(_VRAM_SETTLE_S)
            return partial

    logger.info("        Ready in %.1fs (kv_cache=%s)", time.perf_counter() - t0, kv_bytes_str)

    try:
        # Phase 3 — Measure awake VRAM
        logger.info(
            "  [3/5] Measuring awake VRAM (settling %.0fs)...", _VRAM_SETTLE_S
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
        logger.info("  [4/5] Sleeping model (level=%d)...", sleep_level)
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
            "  [5/5] Measuring sleeping VRAM (settling %.0fs)...", _VRAM_SETTLE_S
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
                "disable_nccl_p2p",
            ):
                plan.setdefault(k, v)

        plans.append(plan)

    return plans


# ---------------------------------------------------------------------------
# High-level auto-calibration for use by main.py
# ---------------------------------------------------------------------------


def auto_calibrate_models(
    uncalibrated: list[str],
    config_path: Path,
    state_dir: Path,
    *,
    vllm_binary: str = _DEFAULT_VLLM,
    port: int = _CALIBRATION_PORT,
    sleep_level: int = 1,
    kv_cache_memory_bytes: str = _DEFAULT_KV_CACHE,
    ready_timeout_s: float = _READY_TIMEOUT_S,
) -> dict[str, CalibrationResult]:
    """Calibrate a list of uncalibrated models and persist results.

    Returns a dict mapping model_name -> CalibrationResult.
    Only calibrates models in the *uncalibrated* list.
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

    profiles_path = state_dir / _PROFILES_FILE
    existing_profiles = load_existing_profiles(profiles_path)
    log_dir = state_dir / "calibration_logs"

    logger.info(
        "Auto-calibration: %d model(s) to calibrate", len(plans)
    )
    for p in plans:
        logger.info(
            "  %s  tp=%s  gpu_devices=%s",
            p["model"],
            p.get("tensor_parallel_size", 1),
            p.get("gpu_devices") or "all",
        )

    results: dict[str, CalibrationResult] = {}

    for plan in plans:
        model_name = plan["model"]
        try:
            result = calibrate_model(
                plan,
                vllm_binary=vllm_binary,
                port=port,
                log_dir=log_dir,
                sleep_level=sleep_level,
                ready_timeout_s=ready_timeout_s,
                kv_cache_memory_bytes=kv_cache_memory_bytes,
            )
        except Exception as exc:
            logger.warning(
                "Calibration failed for %s: %s", model_name, exc
            )
            results[model_name] = CalibrationResult(
                model=model_name,
                tensor_parallel_size=int(
                    plan.get("tensor_parallel_size", 1)
                ),
                gpu_devices=str(plan.get("gpu_devices") or ""),
                kv_cache_sent_mb=0.0,
                success=False,
                error=str(exc),
            )
            continue

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

    ok = [r for r in results.values() if r.success]
    fail = [r for r in results.values() if not r.success]
    logger.info(
        "Auto-calibration complete: %d/%d succeeded", len(ok), len(ok) + len(fail)
    )
    if fail:
        for r in fail:
            logger.warning("  Failed: %s — %s", r.model, r.error)

    return results
