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
import shutil
import sys
from pathlib import Path

from logos_worker_node.calibration import (
    CalibrationResult,
    _DEFAULT_VLLM,
    _HAS_YAML,
    _PROFILES_FILE,
    _READY_TIMEOUT_S,
    calibrate_model,
    load_existing_profiles,
    plans_from_config,
    result_to_profile_dict,
    save_profiles,
)

_DEFAULT_CONFIG = "/app/config.yml"
_DEFAULT_STATE_DIR = "/app/data"


def _sep() -> None:
    print("-" * 60)


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
        default=None,
        help=(
            "KV cache size passed to vLLM during calibration (default: 90 percent of available VRAM). "
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
