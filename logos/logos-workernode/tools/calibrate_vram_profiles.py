#!/usr/bin/env python3
"""Calibrate per-model VRAM profiles by actually loading each model.

Breaks the chicken-and-egg deadlock where inaccurate VRAM estimates prevent
models from ever loading, which in turn prevents auto-calibration from running.

The script loads each capabilities model via vLLM with an explicit
--kv-cache-memory-bytes, measures real VRAM in awake and sleeping states,
then writes the results to model_profiles.yml.  On the next worker startup
these calibrated values are used directly for placement decisions — bypassing
all heuristic estimation.

VRAM decomposition (exact, no guessing):
  base_residency_mb   = loaded_vram_mb - kv_cache_sent_mb
                        (model weights + CUDA runtime overhead, independent of KV size)
  sleeping_residual_mb = measured directly after sleep
                        (what vLLM retains — may be less than base_residency)
  kv_budget_mb        = configured by the operator per lane, not stored here

Because the KV budget is set explicitly, the worker can use any
kv_cache_memory_bytes it wants and predict the footprint exactly:
  expected_loaded_vram = base_residency_mb + kv_cache_memory_bytes

Usage (run while the worker is stopped, GPUs idle):
  python tools/calibrate_vram_profiles.py
  python tools/calibrate_vram_profiles.py --models Org/Model-A,Org/Model-B
  python tools/calibrate_vram_profiles.py --config /app/config.yml --state-dir /app/data
  python tools/calibrate_vram_profiles.py --kv-cache-memory-bytes 4G

Requirements:
  - vLLM with --enable-sleep-mode support (VLLM_SERVER_DEV_MODE=1 is set automatically)
  - nvidia-smi available on PATH
  - The worker must NOT be running (shared GPU, shared port range)
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
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

_DEFAULT_VLLM = "vllm"          # on PATH inside the container (/opt/venv/bin/vllm)
_DEFAULT_CONFIG = "/app/config.yml"
_DEFAULT_STATE_DIR = "/app/data"
_PROFILES_FILE = "model_profiles.yml"
# Default KV cache to allocate during calibration.  Small enough to not
# exhaust VRAM but large enough that vLLM accepts it.  Operators should
# override this to match the value their worker actually uses in production.
_DEFAULT_KV_CACHE = "2G"

_READY_TIMEOUT_S = 600.0
_SLEEP_TIMEOUT_S = 120.0
_VLLM_STOP_TIMEOUT_S = 30.0
_VRAM_SETTLE_S = 4.0       # seconds to wait for VRAM to stabilise after state change
_VRAM_SAMPLE_COUNT = 3     # median over N nvidia-smi readings
_VRAM_SAMPLE_INTERVAL_S = 1.0


def _parse_kv_to_mb(value: str) -> float:
    """'4G' → 4096.0, '512M' → 512.0, '1024' (bytes) → 0.000976..."""
    v = (value or "").strip().upper()
    if v.endswith("G"):
        return float(v[:-1]) * 1024.0
    if v.endswith("M"):
        return float(v[:-1])
    if v.endswith("K"):
        return float(v[:-1]) / 1024.0
    return float(v) / (1024.0 * 1024.0)  # raw bytes


# ---------------------------------------------------------------------------
# GPU VRAM helpers
# ---------------------------------------------------------------------------

def query_gpu_vram(gpu_indices: list[int] | None = None) -> dict[int, dict[str, float]]:
    """Return per-GPU VRAM snapshot. gpu_indices=None means all GPUs."""
    raw = subprocess.check_output(
        [
            "nvidia-smi",
            "--query-gpu=index,memory.total,memory.used,memory.free",
            "--format=csv,noheader,nounits",
        ],
        text=True,
        timeout=10,
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
    """Median VRAM used across target GPUs from N samples."""
    samples: list[float] = []
    for i in range(_VRAM_SAMPLE_COUNT):
        samples.append(_total_used_mb(query_gpu_vram(gpu_indices)))
        if i < _VRAM_SAMPLE_COUNT - 1:
            time.sleep(_VRAM_SAMPLE_INTERVAL_S)
    samples.sort()
    return samples[len(samples) // 2]


def parse_gpu_indices(gpu_devices: str) -> list[int] | None:
    """'0,1' → [0, 1]; '' or 'all' → None (measure all GPUs)."""
    gd = (gpu_devices or "").strip().lower()
    if not gd or gd == "all":
        return None
    return [int(x.strip()) for x in gd.split(",") if x.strip().isdigit()]


# ---------------------------------------------------------------------------
# HTTP helpers (stdlib only — no httpx dependency at calibration time)
# ---------------------------------------------------------------------------

def _http(method: str, url: str, body: dict | None = None, timeout_s: float = 30.0) -> tuple[int, Any]:
    payload = None
    headers: dict[str, str] = {"User-Agent": "logos-calibrate/1.0"}
    if body is not None:
        payload = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=payload, headers=headers, method=method)
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


def _post(url: str, body: dict | None = None, timeout_s: float = 30.0) -> tuple[int, Any]:
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

    # Match worker behaviour (vllm_process.py): when kv_cache_memory_bytes is set,
    # pass --gpu-memory-utilization 0.1 to satisfy vLLM's startup memory guard
    # while letting kv_cache_memory_bytes control actual KV pool allocation.
    # An explicit per-model override takes precedence.
    explicit_gmu = plan.get("gpu_memory_utilization")
    gmu = explicit_gmu if explicit_gmu is not None else 0.1

    cmd = [
        vllm_binary, "serve", model,
        "--host", host,
        "--port", str(port),
        "--tensor-parallel-size", str(tp),
        "--gpu-memory-utilization", str(gmu),
        "--dtype", dtype,
        "--kv-cache-memory-bytes", kv_bytes,
        "--enable-sleep-mode",
    ]
    if max_model_len:
        cmd.extend(["--max-model-len", str(int(max_model_len))])
    if quant:
        cmd.extend(["--quantization", quant])
    if enforce_eager:
        cmd.append("--enforce-eager")
    if disable_custom_all_reduce:
        cmd.append("--disable-custom-all-reduce")
    if disable_nccl_p2p:
        cmd.append("--disable-nccl-p2p")
    cmd.extend(extra_args)

    env = os.environ.copy()
    env["VLLM_SERVER_DEV_MODE"] = "1"
    # Keep venv tools (ninja etc.) visible even outside activated venv
    vllm_dir = str(Path(vllm_binary).resolve().parent)
    env["PATH"] = f"{vllm_dir}{os.pathsep}{env.get('PATH', '')}"

    gpu_devices = str(plan.get("gpu_devices") or "")
    if gpu_devices and gpu_devices.lower() not in ("all", ""):
        env["CUDA_VISIBLE_DEVICES"] = gpu_devices

    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = log_path.open("w", encoding="utf-8")
    try:
        proc = subprocess.Popen(cmd, env=env, stdout=log_file, stderr=subprocess.STDOUT, text=True)
    finally:
        log_file.close()

    print(f"  Spawned PID={proc.pid}  log={log_path}")
    print(f"  Command: {' '.join(cmd)}")
    return proc


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
    last_print = t_start - 25.0  # print at ~5s, then every 30s
    while time.perf_counter() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"vLLM exited before becoming ready (code={proc.poll()})")
        status, _ = _get(f"{base_url}/health", timeout_s=5.0)
        if status == 200:
            return
        now = time.perf_counter()
        if now - last_print >= 30.0:
            elapsed = now - t_start
            vram_str = ""
            try:
                used = _total_used_mb(query_gpu_vram(gpu_indices))
                vram_str = f"  VRAM={used:.0f} MB"
            except Exception:
                pass
            print(f"        {elapsed:.0f}s — weights loaded, waiting for CUDA graph warmup{vram_str}")
            last_print = now
        time.sleep(2.0)
    raise TimeoutError(f"vLLM not ready after {timeout_s:.0f}s")


def wait_sleep_state(base_url: str, target: bool, timeout_s: float) -> None:
    deadline = time.perf_counter() + timeout_s
    while time.perf_counter() < deadline:
        status, payload = _get(f"{base_url}/is_sleeping", timeout_s=5.0)
        if status == 200 and isinstance(payload, dict):
            if bool(payload.get("is_sleeping")) is target:
                return
        time.sleep(0.5)
    raise TimeoutError(f"/is_sleeping did not reach {target} within {timeout_s:.0f}s")


# ---------------------------------------------------------------------------
# Calibration logic
# ---------------------------------------------------------------------------

@dataclass
class CalibrationResult:
    model: str
    tensor_parallel_size: int
    gpu_devices: str
    kv_cache_sent_mb: float   # what we explicitly gave vLLM during calibration
    success: bool
    loaded_vram_mb: float = 0.0       # measured: total GPU delta while awake
    sleeping_residual_mb: float = 0.0  # measured: total GPU delta while sleeping (independent)
    base_residency_mb: float = 0.0    # derived: loaded_vram_mb - kv_cache_sent_mb
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
    kv_cache_memory_bytes: str,
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
        model=model, tensor_parallel_size=tp,
        gpu_devices=gpu_devices, kv_cache_sent_mb=kv_cache_sent_mb, success=False,
    )

    _sep()
    print(f"Calibrating: {model}")
    print(f"  tp={tp}  gpu_devices={gpu_devices or 'all'}  sleep_level={sleep_level}")
    print(f"  kv_cache_memory_bytes={kv_bytes_str} ({kv_cache_sent_mb:.0f} MB) — known, used to derive base_residency")
    _sep()

    # Baseline — measure before any model process exists
    print("  [1/5] Baseline VRAM...")
    try:
        baseline_mb = sample_vram_mb(gpu_indices)
    except Exception as exc:
        partial.error = f"nvidia-smi baseline failed: {exc}"
        print(f"  ERROR: {partial.error}")
        return partial
    print(f"        baseline = {baseline_mb:.0f} MB")

    proc = spawn_vllm(plan, vllm_binary, host, port, log_path, kv_cache_memory_bytes=kv_bytes_str)
    try:
        # Wait for readiness
        print(f"  [2/5] Waiting for vLLM ready (timeout={ready_timeout_s:.0f}s)...")
        t0 = time.perf_counter()
        try:
            wait_ready(base_url, ready_timeout_s, proc, gpu_indices)
        except (TimeoutError, RuntimeError) as exc:
            partial.error = str(exc)
            print(f"  ERROR: {partial.error}")
            return partial
        print(f"        Ready in {time.perf_counter() - t0:.1f}s")

        # Settle then measure awake VRAM
        print(f"  [3/5] Measuring awake VRAM (settling {_VRAM_SETTLE_S:.0f}s)...")
        time.sleep(_VRAM_SETTLE_S)
        try:
            awake_total_mb = sample_vram_mb(gpu_indices)
        except Exception as exc:
            partial.error = f"nvidia-smi awake failed: {exc}"
            print(f"  ERROR: {partial.error}")
            return partial
        loaded_vram_mb = max(awake_total_mb - baseline_mb, 0.0)
        # base_residency is exact because we know what KV we allocated
        base_residency_mb = max(loaded_vram_mb - kv_cache_sent_mb, 0.0)
        print(f"        awake total = {awake_total_mb:.0f} MB  →  loaded delta = {loaded_vram_mb:.0f} MB")
        print(f"        base_residency = {loaded_vram_mb:.0f} - {kv_cache_sent_mb:.0f} = {base_residency_mb:.0f} MB")

        # Sleep the model
        print(f"  [4/5] Sleeping model (level={sleep_level})...")
        sleep_url = f"{base_url}/sleep?{urllib.parse.urlencode({'level': str(sleep_level), 'mode': 'auto'})}"
        status, _ = _post(sleep_url, timeout_s=30.0)
        if status not in (200, 204):
            # Older vLLM: try without mode param
            sleep_url = f"{base_url}/sleep?level={sleep_level}"
            status, _ = _post(sleep_url, timeout_s=30.0)
        if status not in (200, 204):
            partial.error = f"/sleep returned HTTP {status}"
            print(f"  ERROR: {partial.error}")
            return partial
        try:
            wait_sleep_state(base_url, True, _SLEEP_TIMEOUT_S)
        except TimeoutError as exc:
            partial.error = str(exc)
            print(f"  ERROR: {partial.error}")
            return partial

        # Settle then measure sleeping VRAM — independent observation, not derived
        print(f"  [5/5] Measuring sleeping VRAM (settling {_VRAM_SETTLE_S:.0f}s)...")
        time.sleep(_VRAM_SETTLE_S)
        try:
            sleeping_total_mb = sample_vram_mb(gpu_indices)
        except Exception as exc:
            partial.error = f"nvidia-smi sleep failed: {exc}"
            print(f"  ERROR: {partial.error}")
            return partial
        sleeping_residual_mb = max(sleeping_total_mb - baseline_mb, 0.0)
        print(f"        sleeping total = {sleeping_total_mb:.0f} MB  →  sleeping delta = {sleeping_residual_mb:.0f} MB")

        print(f"\n  Results:")
        print(f"    loaded_vram_mb       = {loaded_vram_mb:.0f} MB  (measured)")
        print(f"    kv_cache_sent_mb     = {kv_cache_sent_mb:.0f} MB  (we set this)")
        print(f"    base_residency_mb    = {base_residency_mb:.0f} MB  (= loaded - kv_cache)")
        print(f"    sleeping_residual_mb = {sleeping_residual_mb:.0f} MB  (measured independently)")
        print(f"    Worker prediction: base({base_residency_mb:.0f}) + your_kv = total awake VRAM")

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
        print("  Stopping vLLM...")
        stop_vllm(proc)
        # Let the GPU release memory before the next model
        print(f"  Waiting {_VRAM_SETTLE_S:.0f}s for GPU memory release...")
        time.sleep(_VRAM_SETTLE_S)


# ---------------------------------------------------------------------------
# Profile persistence (mirrors ModelProfileRegistry format)
# ---------------------------------------------------------------------------

def result_to_profile_dict(r: CalibrationResult) -> dict[str, Any]:
    """Build a profile dict compatible with ModelProfileRecord.to_dict().

    kv_budget_mb is intentionally omitted — it is set by the operator per lane
    via kv_cache_memory_bytes and must not be fixed here.  The worker uses:
        expected_loaded = base_residency_mb + kv_cache_memory_bytes
    """
    return {
        "loaded_vram_mb": round(r.loaded_vram_mb, 1),
        "sleeping_residual_mb": round(r.sleeping_residual_mb, 1),
        "disk_size_bytes": None,
        "base_residency_mb": round(r.base_residency_mb, 1),
        # kv_budget_mb records the KV cache used during calibration.
        # The planner uses this to predict loaded VRAM: base_residency + kv_budget.
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
    }


def load_existing_profiles(profiles_path: Path) -> dict[str, Any]:
    if not profiles_path.exists():
        return {}
    try:
        with profiles_path.open() as f:
            data = yaml.safe_load(f) or {}
        return dict(data.get("model_profiles") or {})
    except Exception as exc:
        print(f"Warning: could not parse existing profiles ({profiles_path}): {exc}")
        return {}


def save_profiles(profiles_path: Path, profiles: dict[str, Any]) -> None:
    profiles_path.parent.mkdir(parents=True, exist_ok=True)
    with profiles_path.open("w") as f:
        yaml.safe_dump({"model_profiles": profiles}, f, default_flow_style=False)


# ---------------------------------------------------------------------------
# Config parsing (mirrors models.py LogosConfig._parse_capabilities)
# ---------------------------------------------------------------------------

def plans_from_config(config_path: Path) -> list[dict[str, Any]]:
    """Read capabilities_models from config.yml and return as calibration plans."""
    with config_path.open() as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}

    logos = raw.get("logos") or {}
    caps_raw = logos.get("capabilities_models") or []
    caps_overrides: dict[str, dict] = dict(logos.get("capabilities_overrides") or {})
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
            if k in ("quantization", "dtype", "enforce_eager", "max_model_len",
                     "disable_custom_all_reduce", "disable_nccl_p2p"):
                plan.setdefault(k, v)

        plans.append(plan)

    return plans


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _sep() -> None:
    print("-" * 60)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Calibrate real VRAM usage per model by loading each one via vLLM, "
            "measuring awake + sleeping VRAM, and persisting the results to "
            "model_profiles.yml for use by the worker node."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--config",
        default=_DEFAULT_CONFIG,
        help=f"Path to config.yml (default: {_DEFAULT_CONFIG})",
    )
    parser.add_argument(
        "--state-dir",
        default=_DEFAULT_STATE_DIR,
        help=f"State directory where model_profiles.yml is stored (default: {_DEFAULT_STATE_DIR})",
    )
    parser.add_argument(
        "--models",
        default="",
        help="Comma-separated model names to calibrate. Overrides config.yml capabilities list.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=11499,
        help="Port for the temporary vLLM server (default: 11499, outside normal worker range)",
    )
    parser.add_argument(
        "--vllm-binary",
        default=_DEFAULT_VLLM,
        help=f"Path to vLLM binary (default: {_DEFAULT_VLLM})",
    )
    parser.add_argument(
        "--sleep-level",
        type=int,
        default=1,
        choices=[1, 2],
        help=(
            "vLLM sleep level (default: 1, matches the worker). "
            "Level 1 frees KV cache blocks; level 2 also offloads weights to CPU."
        ),
    )
    parser.add_argument(
        "--ready-timeout",
        type=float,
        default=_READY_TIMEOUT_S,
        help=f"Seconds to wait for vLLM to become ready (default: {_READY_TIMEOUT_S:.0f})",
    )
    parser.add_argument(
        "--log-dir",
        default="calibration_logs",
        help="Directory for per-model vLLM stdout logs (default: calibration_logs/)",
    )
    parser.add_argument(
        "--kv-cache-memory-bytes",
        default=_DEFAULT_KV_CACHE,
        help=(
            f"KV cache size passed to vLLM during calibration (default: {_DEFAULT_KV_CACHE}). "
            "This must be a known value so base_residency_mb = loaded_vram - kv_cache. "
            "Use the same value your worker lanes use in production for the most accurate result. "
            "Accepts suffixes: G (GiB), M (MiB), K (KiB), or raw bytes."
        ),
    )
    parser.add_argument(
        "--gpu-memory-utilization",
        type=float,
        default=None,
        help=(
            "Override gpu_memory_utilization for all models during calibration. "
            "Affects model load phase; KV pool size is controlled by --kv-cache-memory-bytes."
        ),
    )
    args = parser.parse_args()

    if not _HAS_YAML:
        print("ERROR: PyYAML is required.  Install with:  pip install pyyaml")
        return 1

    # Resolve model plans
    if args.models:
        plans = [{"model": m.strip()} for m in args.models.split(",") if m.strip()]
    else:
        config_path = Path(args.config)
        if not config_path.exists():
            print(f"ERROR: config not found: {config_path}")
            return 1
        plans = plans_from_config(config_path)

    if not plans:
        print("No models to calibrate (empty capabilities list).")
        return 0

    # Apply global gpu_memory_utilization override
    if args.gpu_memory_utilization is not None:
        for p in plans:
            p["gpu_memory_utilization"] = args.gpu_memory_utilization

    vllm_binary = args.vllm_binary
    state_dir = Path(args.state_dir)
    log_dir = Path(args.log_dir)
    profiles_path = state_dir / _PROFILES_FILE

    print(f"Calibration plan ({len(plans)} model(s)):")
    for p in plans:
        print(
            f"  {p['model']}"
            f"  tp={p.get('tensor_parallel_size', 1)}"
            f"  gpu_devices={p.get('gpu_devices') or 'all'}"
        )
    print(f"  vllm binary : {vllm_binary}")
    print(f"  port        : {args.port}")
    print(f"  sleep level : {args.sleep_level}")
    print(f"  output      : {profiles_path}")

    import shutil
    if not Path(vllm_binary).exists() and not shutil.which(vllm_binary):
        print(f"ERROR: vLLM binary not found: {vllm_binary}")
        print("       Hint: pass --vllm-binary /opt/venv/bin/vllm or ensure it is on PATH")
        return 1

    existing_profiles = load_existing_profiles(profiles_path)
    results: list[CalibrationResult] = []

    for plan in plans:
        result = calibrate_model(
            plan,
            vllm_binary=vllm_binary,
            port=args.port,
            log_dir=log_dir,
            sleep_level=args.sleep_level,
            ready_timeout_s=args.ready_timeout,
            kv_cache_memory_bytes=args.kv_cache_memory_bytes,
        )
        results.append(result)

        if result.success:
            existing_profiles[result.model] = result_to_profile_dict(result)
            # Persist after every success so a later failure doesn't lose prior results
            save_profiles(profiles_path, existing_profiles)
            print(f"  Saved → {profiles_path}")

    # Summary
    _sep()
    print("CALIBRATION SUMMARY")
    _sep()
    ok = [r for r in results if r.success]
    fail = [r for r in results if not r.success]
    print(f"  {len(ok)}/{len(results)} succeeded\n")

    if ok:
        print("  Model                                    loaded   kv_sent   base     sleeping")
        print("  " + "-" * 78)
        for r in ok:
            print(
                f"  {r.model:<40} "
                f"{r.loaded_vram_mb:>6.0f}  "
                f"{r.kv_cache_sent_mb:>6.0f}    "
                f"{r.base_residency_mb:>6.0f}  "
                f"{r.sleeping_residual_mb:>6.0f}  MB"
            )
        print()
        print("  base_residency = loaded - kv_sent  (exact)")
        print("  sleeping_residual = measured independently  (may be < base_residency)")
        print("  Worker: expected_loaded = base_residency + your_kv_cache_memory_bytes")
        print()

    if fail:
        print("  Failed models:")
        for r in fail:
            print(f"    {r.model}: {r.error}")
        print()

    if ok:
        print(f"  Profiles written to: {profiles_path}")
        print("  Start the worker — it will load calibrated values and skip all VRAM estimation.")

    return 0 if not fail else 1


if __name__ == "__main__":
    sys.exit(main())
