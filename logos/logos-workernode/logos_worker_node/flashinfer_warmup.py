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

    # Kernel configs that match real model architectures.
    # FlashInfer JIT-compiles separate kernels per (num_qo_heads, num_kv_heads, head_dim, dtype).
    # Each entry: (num_qo_heads, num_kv_heads, head_dim)
    _KERNEL_CONFIGS: list[tuple[int, int, int]] = [
        # Qwen2.5-0.5B-Instruct: 14 attention heads, 2 KV heads (GQA), head_dim=64
        (14, 2, 64),
        # Qwen2.5-7B / Qwen2.5-Coder-7B: 28 attention heads, 4 KV heads (GQA), head_dim=128
        (28, 4, 128),
        # Qwen3-8B: 32 attention heads, 8 KV heads (GQA), head_dim=128
        (32, 8, 128),
        # Generic fallbacks for other models
        (32, 32, 128),  # non-GQA 7-8B class (e.g. Llama-7B)
        (8, 8, 128),    # smaller models with MHA
    ]

    t0 = time.monotonic()
    compiled = 0
    try:
        for num_qo_heads, num_kv_heads, head_dim in _KERNEL_CONFIGS:
            for dtype in (torch.float16, torch.bfloat16):
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
        logger.info("FlashInfer warmup completed in %.1fs (%d/%d kernels compiled)",
                     elapsed, compiled, len(_KERNEL_CONFIGS) * 2)
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
