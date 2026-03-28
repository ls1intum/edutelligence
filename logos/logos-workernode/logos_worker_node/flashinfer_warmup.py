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

logger = logging.getLogger("logos_worker_node.flashinfer_warmup")


def warmup(cache_dir: str | None = None) -> bool:
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

    # Kernel configs for officially supported models.
    # FlashInfer JIT-compiles separate kernels per (num_qo_heads, num_kv_heads, head_dim, dtype).
    # Only full-attention layers need FlashInfer warmup — Qwen3.5 linear/GDN layers
    # use Triton/FLA on non-SM90 GPUs, not FlashInfer.
    # Each entry: (num_qo_heads, num_kv_heads, head_dim)
    _KERNEL_CONFIGS: list[tuple[int, int, int]] = [
        # deepseek-r1-distill-llama-8b-awq + Qwen3-Embedding-4B-AWQ: 32 qo, 8 kv, head_dim=128
        (32, 8, 128),
        # Qwen3-Coder-30B-A3B-AWQ (TP=1): 32 qo, 4 kv, head_dim=128
        (32, 4, 128),
        # Qwen3-Coder-30B-A3B-AWQ (TP=2): heads split across 2 GPUs
        (16, 2, 128),
        # Qwen3.5-9B-AWQ full-attention layers (TP=1): 16 qo, 4 kv, head_dim=256
        (16, 4, 256),
        # Qwen3.5-35B-A3B-AWQ full-attention layers (TP=1): 16 qo, 2 kv, head_dim=256
        (16, 2, 256),
        # Qwen3.5-35B-A3B-AWQ full-attention layers (TP=2): heads split across 2 GPUs
        (8, 1, 256),
    ]

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
        for num_qo_heads, num_kv_heads, head_dim in _KERNEL_CONFIGS:
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
        total_expected = len(_KERNEL_CONFIGS) * len(dtypes)
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
