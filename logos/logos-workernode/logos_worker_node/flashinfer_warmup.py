"""Pre-warm FlashInfer JIT kernels before vLLM starts.

Running this once (sequentially, single-process) compiles and caches
FlashInfer CUDA kernels.  Subsequent vLLM startups — including TP>1
multi-process launches — find cached .so files and skip JIT entirely,
avoiding the race condition where simultaneous compilation + NCCL init
can crash GPU drivers.

Usage:
    python -m logos_worker_node.flashinfer_warmup [--workspace-base /path]

The workspace base defaults to ``$FLASHINFER_WORKSPACE_BASE`` or ``$HOME``.
flashinfer 0.6.x reads ``FLASHINFER_WORKSPACE_BASE`` (see
``flashinfer/jit/env.py``) and writes its JIT cache to
``<workspace_base>/.cache/flashinfer/<version>/<arch>/cached_ops/``.  Pointing
this at a persistent volume keeps compiled kernels across container restarts.
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


def kernel_configs_for_models(
    model_names: Iterable[str] | None,
) -> list[tuple[int, int, int]]:
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
        if any(
            token in name
            for token in (
                "mistral-7b",
                "llama-8b",
                "deepseek-r1-distill-llama-8b",
                "qwen3-embedding-4b",
            )
        ):
            add((32, 8, 128))

    if not configs:
        return list(_DEFAULT_KERNEL_CONFIGS)
    return configs


def _count_so_files(root: str | None) -> int:
    """Count compiled .so files under *root* (recursive). Returns 0 if missing."""
    if not root or not os.path.isdir(root):
        return 0
    total = 0
    for _dir, _subdirs, files in os.walk(root):
        for f in files:
            if f.endswith(".so"):
                total += 1
    return total


def _warm_batch_prefill(head_dim: int, dtype, device) -> bool:
    """Trigger JIT compile of ``batch_prefill_with_kv_cache`` for paged-KV layout.

    vLLM uses this kernel for every prefill (and decode shares the same op
    in V1).  flashinfer caches it by ``(head_dim_qk, head_dim_vo, dtype, ...)``
    independent of ``num_qo_heads`` / ``num_kv_heads``, so one warmup call
    per ``(head_dim, dtype)`` covers every model that shares those.
    """
    import flashinfer
    import torch

    wrapper_cls = getattr(flashinfer, "BatchPrefillWithPagedKVCacheWrapper", None)
    if wrapper_cls is None:
        return False

    page_size = 16
    num_pages = 4
    seq_len = 128
    # num_qo_heads / num_kv_heads don't influence the cached kernel name; pick
    # a small symmetric pair to keep allocations cheap.
    num_qo_heads = 8
    num_kv_heads = 8

    workspace = torch.empty(128 * 1024 * 1024, dtype=torch.uint8, device=device)
    wrapper = wrapper_cls(workspace, kv_layout="NHD")

    qo_indptr = torch.tensor([0, seq_len], dtype=torch.int32, device=device)
    paged_kv_indptr = torch.tensor([0, num_pages], dtype=torch.int32, device=device)
    paged_kv_indices = torch.arange(num_pages, dtype=torch.int32, device=device)
    paged_kv_last_page_len = torch.tensor([page_size], dtype=torch.int32, device=device)

    wrapper.plan(
        qo_indptr,
        paged_kv_indptr,
        paged_kv_indices,
        paged_kv_last_page_len,
        num_qo_heads,
        num_kv_heads,
        head_dim,
        page_size,
        causal=True,
        q_data_type=dtype,
        kv_data_type=dtype,
    )
    q = torch.randn(seq_len, num_qo_heads, head_dim, dtype=dtype, device=device)
    kv_cache = torch.randn(
        num_pages,
        2,
        page_size,
        num_kv_heads,
        head_dim,
        dtype=dtype,
        device=device,
    )
    wrapper.run(q, kv_cache)
    torch.cuda.synchronize()

    del (
        workspace,
        q,
        kv_cache,
        qo_indptr,
        paged_kv_indptr,
        paged_kv_indices,
        paged_kv_last_page_len,
    )
    return True


def warmup(
    workspace_base: str | None = None,
    model_names: Iterable[str] | None = None,
) -> bool:
    """Trigger FlashInfer JIT compilation for common kernel configurations.

    Returns True if warmup succeeded (or FlashInfer not installed), False on error.

    *workspace_base* — set as ``FLASHINFER_WORKSPACE_BASE`` so flashinfer writes
    its JIT cache under ``<workspace_base>/.cache/flashinfer/``.  Should point at
    a persistent volume so compiled kernels survive container restarts.
    """
    cache_dir: str | None = None
    if workspace_base:
        # FLASHINFER_WORKSPACE_BASE is the env var flashinfer 0.6.x actually
        # honors (flashinfer/jit/env.py:52).  FLASHINFER_JIT_DIR is a Python
        # attribute on flashinfer.jit.env, not an env var read at runtime —
        # setting it has no effect.
        os.environ.setdefault("FLASHINFER_WORKSPACE_BASE", workspace_base)
        cache_dir = os.path.join(workspace_base, ".cache", "flashinfer")
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

    pre_count = _count_so_files(cache_dir)
    logger.info(
        "FlashInfer warmup: device=%s, compute=%d.%d, cache_dir=%s, " "pre_warmup_kernels=%d",
        torch.cuda.get_device_name(device),
        cap[0],
        cap[1],
        cache_dir or "<default>",
        pre_count,
    )

    # Only warm the kernel shapes used by the configured capability set.
    # FlashInfer JIT-compiles separate kernels per (head_dim, dtype, ...);
    # num_qo_heads / num_kv_heads do NOT vary the cached kernel.  Each entry
    # below is (num_qo_heads, num_kv_heads, head_dim) — the head counts are
    # only used to size the warmup tensors, not to key the cache.
    kernel_configs = kernel_configs_for_models(model_names)

    # BFloat16 requires Ampere+ (compute >= 8.0).  On Turing (7.x) and
    # older, FlashInfer BF16 kernels trigger cudaErrorLaunchFailure which
    # fatally corrupts the CUDA context and poisons subsequent GPU work.
    dtypes = [torch.float16]
    if cap[0] >= 8:
        dtypes.append(torch.bfloat16)
    else:
        logger.info(
            "Skipping bfloat16 warmup — compute %d.%d < 8.0 (Ampere required)",
            cap[0],
            cap[1],
        )

    t0 = time.monotonic()
    single_compiled = 0
    batch_compiled = 0
    single_total = len(kernel_configs) * len(dtypes)
    # batch_prefill caches by head_dim only; one warmup per unique head_dim.
    unique_head_dims = sorted({hd for _, _, hd in kernel_configs})
    batch_total = len(unique_head_dims) * len(dtypes)
    try:
        for num_qo_heads, num_kv_heads, head_dim in kernel_configs:
            for dtype in dtypes:
                logger.info(
                    "  warming single_prefill qo=%d kv=%d hdim=%d %s",
                    num_qo_heads,
                    num_kv_heads,
                    head_dim,
                    dtype,
                )
                seq_len = 128

                q = torch.randn(seq_len, num_qo_heads, head_dim, dtype=dtype, device=device)
                k = torch.randn(seq_len, num_kv_heads, head_dim, dtype=dtype, device=device)
                v = torch.randn(seq_len, num_kv_heads, head_dim, dtype=dtype, device=device)

                try:
                    flashinfer.single_prefill_with_kv_cache(q, k, v, causal=True)
                    single_compiled += 1
                except Exception as e:
                    logger.debug("single_prefill_with_kv_cache failed for config: %s", e)
                    try:
                        # Decode path: single query token
                        q_decode = torch.randn(1, num_qo_heads, head_dim, dtype=dtype, device=device)
                        flashinfer.single_decode_with_kv_cache(q_decode, k, v)
                        single_compiled += 1
                        del q_decode
                    except Exception as e2:
                        logger.debug("single_decode_with_kv_cache also failed: %s", e2)

                del q, k, v

        # batch_prefill_with_kv_cache is the kernel vLLM actually invokes at
        # runtime — without this pass, the first lane spawn pays a ~30s JIT
        # compile for it.  Pre-warming here moves that cost to worker boot.
        for head_dim in unique_head_dims:
            for dtype in dtypes:
                logger.info("  warming batch_prefill hdim=%d %s", head_dim, dtype)
                try:
                    if _warm_batch_prefill(head_dim, dtype, device):
                        batch_compiled += 1
                except Exception as e:
                    logger.debug(
                        "batch_prefill warmup failed for hdim=%d %s: %s",
                        head_dim,
                        dtype,
                        e,
                    )

        torch.cuda.synchronize()
        elapsed = time.monotonic() - t0
        post_count = _count_so_files(cache_dir)
        new_kernels = max(0, post_count - pre_count)
        logger.info(
            "FlashInfer warmup completed in %.1fs (single_prefill=%d/%d, "
            "batch_prefill=%d/%d, %d kernels resident on disk, +%d new this boot)",
            elapsed,
            single_compiled,
            single_total,
            batch_compiled,
            batch_total,
            post_count,
            new_kernels,
        )
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
    parser.add_argument(
        "--workspace-base",
        default=os.environ.get("FLASHINFER_WORKSPACE_BASE", ""),
        help="Path used as FLASHINFER_WORKSPACE_BASE (parent of .cache/flashinfer).",
    )
    args = parser.parse_args()
    ok = warmup(args.workspace_base or None)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
