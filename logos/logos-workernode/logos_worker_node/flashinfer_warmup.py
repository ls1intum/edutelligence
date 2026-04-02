"""Pre-warm FlashInfer JIT kernels before vLLM starts.

Running this once (sequentially, single-process) compiles and caches
FlashInfer CUDA kernels.  Subsequent vLLM startups — including TP>1
multi-process launches — find cached .so files and skip JIT entirely,
avoiding the race condition where simultaneous compilation + NCCL init
can crash GPU drivers.

Usage:
    python -m logos_worker_node.flashinfer_warmup [--cache-dir /path/to/cache]

The cache directory defaults to $FLASHINFER_JIT_DIR or /tmp/flashinfer_cache.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from collections.abc import Iterable

logger = logging.getLogger("logos_worker_node.flashinfer_warmup")

_DEFAULT_KERNEL_CONFIGS: tuple[tuple[int, int, int], ...] = (
    # Mistral / Llama 8B / Qwen3-Embedding-4B style attention
    (32, 8, 128),
    # Qwen2.5 7B / 7B Coder
    (28, 4, 128),
    # Qwen2.5 14B / 14B Coder
    (40, 8, 128),
)


def kernel_configs_for_models(model_names: Iterable[str] | None) -> list[tuple[int, int, int]]:
    """Return the FlashInfer kernel shapes needed for the configured capability set."""
    configs: list[tuple[int, int, int]] = []

    def add(config: tuple[int, int, int]) -> None:
        if config not in configs:
            configs.append(config)

    for raw_name in model_names or ():
        name = (raw_name or "").strip().lower()
        if not name:
            continue
        if "qwen2.5" in name and "14b" in name:
            add((40, 8, 128))
            continue
        if "qwen2.5" in name and "7b" in name:
            add((28, 4, 128))
            continue
        if any(token in name for token in (
            "mistral-7b",
            "llama-8b",
            "deepseek-r1-distill-llama-8b",
            "qwen3-embedding-4b",
        )):
            add((32, 8, 128))

    if not configs:
        return list(_DEFAULT_KERNEL_CONFIGS)
    return configs


def warmup(cache_dir: str | None = None, model_names: Iterable[str] | None = None) -> bool:
    """Trigger FlashInfer JIT compilation for common kernel configurations.

    Returns True if warmup succeeded (or FlashInfer not installed), False on error.
    """
    if cache_dir:
        os.environ.setdefault("FLASHINFER_JIT_DIR", cache_dir)
        os.makedirs(cache_dir, exist_ok=True)

    try:
        import torch
    except ImportError:
        logger.info("PyTorch not available — skipping FlashInfer warmup")
        return True

    if not torch.cuda.is_available():
        logger.info("No CUDA device — skipping FlashInfer warmup")
        return True

    try:
        import flashinfer  # noqa: F401
    except ImportError:
        logger.info("FlashInfer not installed — skipping warmup")
        return True

    device = torch.device("cuda:0")
    cap = torch.cuda.get_device_capability(device)
    logger.info(
        "FlashInfer warmup: device=%s, compute=%d.%d, cache_dir=%s",
        torch.cuda.get_device_name(device), cap[0], cap[1],
        os.environ.get("FLASHINFER_JIT_DIR", "<default>"),
    )

    # Only warm the kernel shapes used by the configured capability set.
    # FlashInfer JIT-compiles separate kernels per (num_qo_heads, num_kv_heads, head_dim, dtype).
    # Each entry: (num_qo_heads, num_kv_heads, head_dim)
    kernel_configs = kernel_configs_for_models(model_names)

    # BFloat16 requires Ampere+ (compute >= 8.0).  On Turing (7.x) and
    # older, FlashInfer BF16 kernels trigger cudaErrorLaunchFailure which
    # fatally corrupts the CUDA context and poisons subsequent GPU work.
    dtypes = [torch.float16]
    if cap[0] >= 8:
        dtypes.append(torch.bfloat16)
    else:
        logger.info("Skipping bfloat16 warmup — compute %d.%d < 8.0 (Ampere required)", cap[0], cap[1])

    t0 = time.monotonic()
    compiled = 0
    try:
        for num_qo_heads, num_kv_heads, head_dim in kernel_configs:
            for dtype in dtypes:
                logger.info(
                    "  warming qo=%d kv=%d hdim=%d %s",
                    num_qo_heads, num_kv_heads, head_dim, dtype,
                )
                seq_len = 128

                q = torch.randn(seq_len, num_qo_heads, head_dim, dtype=dtype, device=device)
                k = torch.randn(seq_len, num_kv_heads, head_dim, dtype=dtype, device=device)
                v = torch.randn(seq_len, num_kv_heads, head_dim, dtype=dtype, device=device)

                try:
                    flashinfer.single_prefill_with_kv_cache(q, k, v, causal=True)
                    compiled += 1
                except Exception as e:
                    logger.debug("single_prefill_with_kv_cache failed for config: %s", e)
                    try:
                        # Decode path: single query token
                        q_decode = torch.randn(1, num_qo_heads, head_dim, dtype=dtype, device=device)
                        flashinfer.single_decode_with_kv_cache(q_decode, k, v)
                        compiled += 1
                        del q_decode
                    except Exception as e2:
                        logger.debug("single_decode_with_kv_cache also failed: %s", e2)

                del q, k, v

        torch.cuda.synchronize()
        elapsed = time.monotonic() - t0
        total_expected = len(kernel_configs) * len(dtypes)
        logger.info("FlashInfer warmup completed in %.1fs (%d/%d kernels compiled)",
                     elapsed, compiled, total_expected)
        return True
    except Exception as exc:
        elapsed = time.monotonic() - t0
        logger.warning("FlashInfer warmup failed after %.1fs: %s", elapsed, exc)
        return False
    finally:
        try:
            torch.cuda.empty_cache()
        except Exception as exc:  # noqa: BLE001
            logger.warning("FlashInfer warmup cleanup failed: %s", exc)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Pre-warm FlashInfer JIT kernels")
    parser.add_argument("--cache-dir", default=os.environ.get("FLASHINFER_JIT_DIR", ""))
    args = parser.parse_args()
    ok = warmup(args.cache_dir or None)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
