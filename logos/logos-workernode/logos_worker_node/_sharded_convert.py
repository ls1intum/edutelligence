#!/usr/bin/env python3
"""Standalone vLLM sharded-state checkpoint converter (run as a subprocess).

This script is intentionally free of any ``logos_worker_node`` imports so it can
be executed by whichever Python interpreter has vLLM installed — which is not
necessarily the interpreter running the worker process (vLLM frequently lives
in a dedicated venv such as ``/opt/venv``). It is therefore invoked by file
path, e.g. ``/opt/venv/bin/python _sharded_convert.py --model ... --output ...``.

It mirrors vLLM's official ``examples/features/sharded_state/
save_sharded_state_offline.py`` (pinned to the vLLM version in the worker
image), adding HuggingFace resolution so a bare model id can be converted
without a pre-resolved local path.

Usage::

    python _sharded_convert.py \\
        --model <hf-id-or-local-dir> \\
        --tensor-parallel-size N \\
        --output /path/to/sharded/dir \\
        [--dtype auto] [--quantization awq] [--trust-remote-code] \\
        [--max-file-size BYTES] [--file-pattern PATTERN]

On success it prints a confirmation line and exits 0; the caller writes the
completion marker once it sees a clean exit and shard files on disk.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

_WEIGHT_SUFFIXES = (".bin", ".pt", ".safetensors")


def _resolve_local_model_dir(model: str) -> str:
    """Return a local directory for ``model``, downloading from HF if needed."""
    if Path(model).is_dir():
        return model
    from huggingface_hub import snapshot_download  # noqa: PLC0415

    # Respects HF_HOME / HF_TOKEN from the environment, which the caller sets.
    return snapshot_download(model, token=os.environ.get("HF_TOKEN") or None)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert a model checkpoint to a vLLM sharded_state checkpoint.")
    parser.add_argument("--model", required=True)
    parser.add_argument("--tensor-parallel-size", type=int, required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--dtype", default="auto")
    parser.add_argument("--quantization", default="")
    parser.add_argument("--trust-remote-code", action="store_true")
    parser.add_argument("--max-file-size", type=int, default=5 * 1024**3)
    parser.add_argument("--file-pattern", default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    from vllm import LLM, EngineArgs  # noqa: PLC0415
    from vllm.model_executor.model_loader import ShardedStateLoader  # noqa: PLC0415

    model_path = _resolve_local_model_dir(args.model)
    if not Path(model_path).is_dir():
        print(
            f"[sharded-convert] model path is not a local directory: {model_path}",
            file=sys.stderr,
        )
        return 2

    pattern = args.file_pattern or ShardedStateLoader.DEFAULT_PATTERN

    engine_args = EngineArgs(
        model=model_path,
        tensor_parallel_size=args.tensor_parallel_size,
        dtype=args.dtype,
        quantization=(args.quantization or None),
        trust_remote_code=args.trust_remote_code,
    )

    # Loads the full checkpoint across ``tensor_parallel_size`` ranks on GPU.
    llm = LLM.from_engine_args(engine_args)

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    # Dump each rank's shard directly to the output directory.
    llm.llm_engine.engine_core.save_sharded_state(path=str(out), pattern=pattern, max_size=args.max_file_size)

    # Copy metadata (config.json, tokenizer, generation config, …) — everything
    # that is not a raw weight file — so the output is a self-contained model
    # directory vLLM can serve with --load-format sharded_state.
    for name in os.listdir(model_path):
        if os.path.splitext(name)[1] in _WEIGHT_SUFFIXES:
            continue
        src = os.path.join(model_path, name)
        dst = os.path.join(str(out), name)
        if os.path.isdir(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy(src, dst)

    print(f"[sharded-convert] wrote sharded checkpoint to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
