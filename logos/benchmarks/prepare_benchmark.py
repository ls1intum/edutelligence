#!/usr/bin/env python3
"""
Prepare GSM8K workload CSVs for the Logos benchmark.

Downloads openai/gsm8k from HuggingFace and produces two workload CSV files —
one for the 2-LLM configuration and one for the 5-LLM configuration — that
benchmark_logos.py can consume directly via --workload.

Models are assigned round-robin so each LLM receives an equal (±1) share of
the requests. The assignment is deterministic (same seed → same assignment).

Requirements:
    pip install datasets

Usage:
    # All 1319 test examples, 1 req/s arrival rate:
    python prepare_benchmark.py

    # First 200 examples, 0.5 req/s:
    python prepare_benchmark.py --num-samples 200 --rps 0.5

    # Train split, all examples, 2 req/s:
    python prepare_benchmark.py --split train --rps 2.0

    # No arrival offsets (use --sequential in benchmark_logos.py):
    python prepare_benchmark.py --rps 0

Output (in --output-dir):
    workload_gsm8k_2llm.csv   — requests using 2 LLMs
    workload_gsm8k_5llm.csv   — requests using 5 LLMs

Each CSV row contains:
    request_id, arrival_offset, mode, priority, body_json,
    question, answer, model_assigned

The body_json field holds the full OpenAI chat completions payload (with
model, messages, max_tokens) ready for benchmark_logos.py to send.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from pathlib import Path

try:
    from datasets import load_dataset
except ImportError:
    print(
        "Error: 'datasets' library not installed.\n" "       Run: pip install datasets",
        file=sys.stderr,
    )
    sys.exit(1)

# Import model config from the sibling file
try:
    from benchmark_config import GSM8K_MAX_TOKENS, GSM8K_SYSTEM_PROMPT, MODELS_2, MODELS_5
except ImportError as exc:
    print(f"Error: cannot import benchmark_config.py: {exc}", file=sys.stderr)
    sys.exit(1)


# ── Workload construction ─────────────────────────────────────────────────


def build_workload(
    examples: list[dict],
    models: list[str],
    rps: float,
    max_tokens: int | None,
    seed: int,
) -> list[dict]:
    """
    Assign models to requests reproducibly and compute uniform arrival offsets.

    Model assignment starts from a balanced round-robin list (so each model gets
    an exactly equal ±1 share) which is then shuffled with ``seed``. Same seed →
    identical request→model mapping, so a run is 1:1 reproducible; a different
    seed gives a different (still balanced) assignment for variance studies. The
    seed is recorded in the ``seed`` column of every row.

    rps = 0  →  all arrival offsets are 0 (use --sequential in benchmark).
    rps > 0  →  offset_i = i * (1000 / rps) ms.

    max_tokens is omitted from the request body when None/<=0 (no limit) so
    answers are never truncated — see benchmark_config.GSM8K_MAX_TOKENS.
    """
    interval_ms = (1000.0 / rps) if rps > 0 else 0.0
    rows = []

    # Balanced assignment, then a seeded shuffle for reproducible randomness.
    assignment = [models[i % len(models)] for i in range(len(examples))]
    random.Random(seed).shuffle(assignment)

    for i, ex in enumerate(examples):
        model = assignment[i]
        body: dict = {
            "model": model,
            "messages": [
                {"role": "system", "content": GSM8K_SYSTEM_PROMPT},
                {"role": "user", "content": ex["question"]},
            ],
        }
        if max_tokens is not None and max_tokens > 0:
            body["max_tokens"] = max_tokens
        rows.append(
            {
                "request_id": f"gsm8k-{i + 1:04d}",
                "arrival_offset": round(i * interval_ms, 3),  # ms
                "mode": "interactive",
                "priority": "mid",
                "body_json": json.dumps(body, ensure_ascii=False),
                # Reference columns (not used by benchmark_logos.py, but useful for
                # evaluating model accuracy after the benchmark run)
                "question": ex["question"],
                "answer": ex["answer"],
                "model_assigned": model,
                # Recorded so the benchmark can echo it into run_meta.json and the
                # exact request→model mapping is reproducible from seed alone.
                "seed": seed,
            }
        )
    return rows


_FIELDNAMES = [
    "request_id",
    "arrival_offset",
    "mode",
    "priority",
    "body_json",
    "question",
    "answer",
    "model_assigned",
    "seed",
]


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def print_distribution(rows: list[dict], models: list[str]) -> None:
    counts: dict[str, int] = {m: 0 for m in models}
    for r in rows:
        counts[r["model_assigned"]] += 1
    total = len(rows)
    for model, count in counts.items():
        bar = "█" * int(count / total * 40)
        print(f"    {model:<40} {count:>5}  ({count / total * 100:.1f}%)  {bar}")


# ── Main ──────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prepare GSM8K workload CSVs for the Logos benchmark.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--split",
        default="test",
        choices=["train", "test", "all"],
        help="GSM8K dataset split to use. 'test' has 1 319 examples, 'train' has 7 473, "
        "'all' concatenates train+test (8 792 examples).",
    )
    parser.add_argument(
        "--num-samples",
        type=int,
        default=1000,
        metavar="N",
        help="Limit to the first N examples. Default 1000 (a single shared load "
        "level across all scenarios). Pass 0 or a negative value for all examples.",
    )
    parser.add_argument(
        "--rps",
        type=float,
        default=0.5,
        metavar="RATE",
        help=(
            "Arrival rate in requests per second (one rate for all scenarios). "
            "Determines the arrival_offset column (offset_i = i * 1000/rps ms). "
            "Default 0.5. Set to 0 to give all requests offset=0 and use --sequential."
        ),
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Seed for the request→model assignment shuffle. Same seed → identical "
        "workload (recorded in the CSV's seed column for 1:1 reproducibility).",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=GSM8K_MAX_TOKENS,
        help="max_tokens written into each request's body_json. Omitted entirely "
        "when None/<=0 (the default) so responses are never truncated.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("workloads"),
        help="Directory where the workload CSVs will be written.",
    )
    args = parser.parse_args()

    # ── Download ──────────────────────────────────────────────────────────
    print(f"Downloading openai/gsm8k ({args.split} split) from HuggingFace...")
    if args.split == "all":
        # Concatenate train + test for the full GSM8K dataset.
        train = list(load_dataset("openai/gsm8k", "main", split="train"))
        test = list(load_dataset("openai/gsm8k", "main", split="test"))
        examples: list[dict] = train + test
        print(f"  Loaded train ({len(train)}) + test ({len(test)}) = {len(examples)} examples.")
    else:
        examples = list(load_dataset("openai/gsm8k", "main", split=args.split))

    total_available = len(examples)
    if args.num_samples and args.num_samples > 0:
        examples = examples[: args.num_samples]
        print(f"  Using first {len(examples)} of {total_available} examples.")
    else:
        print(f"  Using all {len(examples)} examples.")

    print(f"  Seed: {args.seed} (request→model assignment is reproducible from this).")

    if args.rps > 0:
        total_duration_s = (len(examples) - 1) * (1.0 / args.rps)
        print(f"  Arrival rate: {args.rps} req/s → workload spans {total_duration_s:.0f}s total.")
    else:
        print("  Arrival rate: 0 (all offsets = 0 — use --sequential in benchmark_logos.py).")

    print()

    # ── Build & write one CSV per LLM config ──────────────────────────────
    configs = [
        ("2llm", MODELS_2),
        ("5llm", MODELS_5),
    ]

    for label, models in configs:
        print(f"Config '{label}': {len(models)} model(s)")
        for m in models:
            print(f"    • {m}")

        rows = build_workload(examples, models, args.rps, args.max_tokens, args.seed)
        print(f"  Distribution ({len(rows)} requests):")
        print_distribution(rows, models)

        out_path = args.output_dir / f"workload_gsm8k_{label}.csv"
        write_csv(out_path, rows)
        print(f"  → Written: {out_path}")
        print()

    print("Done. Pass a workload to the benchmark with:")
    print(f"  python benchmark_logos.py --workload {args.output_dir}/workload_gsm8k_2llm.csv ...")
    print(f"  python benchmark_logos.py --workload {args.output_dir}/workload_gsm8k_5llm.csv ...")


if __name__ == "__main__":
    main()
