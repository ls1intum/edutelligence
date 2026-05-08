"""Analyze ECCS ablation benchmark results.

Reads decision logs (JSON-lines from ECCS_DECISION_LOG) and optionally
joins with benchmark detailed CSVs (from run_api_workload.py) to compute:

1. Correction hit rate — how often ECCS changed the classification top pick
2. Tier distribution — infrastructure state of selected candidates
3. Conditional speedup — TTFT/latency when correction changed vs didn't
4. Side-by-side comparison — ECCS on vs off (when two runs provided)

Usage:
    # Single run analysis (decision log only):
    python3 tests/performance/analyze_eccs_ablation.py \\
        --decision-log results/eccs_decisions.jsonl

    # Single run with benchmark metrics:
    python3 tests/performance/analyze_eccs_ablation.py \\
        --decision-log results/eccs_decisions.jsonl \\
        --benchmark-csv results/detailed.csv

    # Side-by-side: ECCS on vs off:
    python3 tests/performance/analyze_eccs_ablation.py \\
        --decision-log results/eccs_on/decisions.jsonl \\
        --benchmark-csv results/eccs_on/detailed.csv \\
        --baseline-log results/eccs_off/decisions.jsonl \\
        --baseline-csv results/eccs_off/detailed.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class DecisionRecord:
    request_id: str
    ts: float
    ettft_enabled: bool
    weight_overrides_active: bool
    candidates: list[dict]
    selected_model_id: int | None
    selected_provider_id: int | None
    classification_top_model_id: int | None
    correction_changed: bool
    was_queued: bool


@dataclass
class BenchmarkRecord:
    request_id: str
    model_name: str
    provider_name: str
    ttft_ms: float | None
    total_latency_ms: float | None
    queue_wait_ms: float | None
    cold_start: bool


@dataclass
class RunStats:
    """Aggregated statistics for one benchmark run."""
    label: str
    total_decisions: int = 0
    correction_changed_count: int = 0
    queued_count: int = 0
    tier_counts: dict[str, int] = field(default_factory=Counter)
    # Conditional latencies (split by correction_changed)
    ttft_changed: list[float] = field(default_factory=list)
    ttft_unchanged: list[float] = field(default_factory=list)
    latency_changed: list[float] = field(default_factory=list)
    latency_unchanged: list[float] = field(default_factory=list)
    queue_wait_changed: list[float] = field(default_factory=list)
    queue_wait_unchanged: list[float] = field(default_factory=list)
    # All latencies
    all_ttft: list[float] = field(default_factory=list)
    all_latency: list[float] = field(default_factory=list)


def load_decision_log(path: Path) -> list[DecisionRecord]:
    records = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            records.append(DecisionRecord(
                request_id=d["request_id"],
                ts=d["ts"],
                ettft_enabled=d["ettft_enabled"],
                weight_overrides_active=d.get("weight_overrides_active", False),
                candidates=d.get("candidates", []),
                selected_model_id=d.get("selected_model_id"),
                selected_provider_id=d.get("selected_provider_id"),
                classification_top_model_id=d.get("classification_top_model_id"),
                correction_changed=d.get("correction_changed", False),
                was_queued=d.get("was_queued", False),
            ))
    return records


def load_benchmark_csv(path: Path) -> dict[str, BenchmarkRecord]:
    """Load detailed benchmark CSV and index by request_id."""
    records = {}
    with path.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            rid = row.get("request_id", "").strip()
            if not rid:
                continue

            def _float(val: str) -> float | None:
                val = val.strip()
                if not val:
                    return None
                try:
                    v = float(val)
                    return v if not math.isnan(v) else None
                except (ValueError, TypeError):
                    return None

            records[rid] = BenchmarkRecord(
                request_id=rid,
                model_name=row.get("model_name", ""),
                provider_name=row.get("provider_name", ""),
                ttft_ms=_float(row.get("ttft_ms", "")),
                total_latency_ms=_float(row.get("total_latency_ms", "")),
                queue_wait_ms=_float(row.get("queue_wait_ms", "")),
                cold_start=row.get("cold_start", "").strip().lower() in ("true", "1", "yes"),
            )
    return records


def compute_stats(
    decisions: list[DecisionRecord],
    benchmarks: dict[str, BenchmarkRecord] | None,
    label: str,
) -> RunStats:
    stats = RunStats(label=label)

    for dec in decisions:
        stats.total_decisions += 1
        if dec.correction_changed:
            stats.correction_changed_count += 1
        if dec.was_queued:
            stats.queued_count += 1

        # Tier of selected candidate
        if dec.selected_model_id is not None and dec.candidates:
            selected_entry = next(
                (c for c in dec.candidates
                 if c["model_id"] == dec.selected_model_id
                 and c.get("provider_id") == dec.selected_provider_id),
                None,
            )
            if selected_entry:
                stats.tier_counts[selected_entry.get("tier", "unknown")] += 1

        # Join with benchmark data
        if benchmarks is not None:
            bench = benchmarks.get(dec.request_id)
            if bench:
                if bench.ttft_ms is not None:
                    stats.all_ttft.append(bench.ttft_ms)
                    if dec.correction_changed:
                        stats.ttft_changed.append(bench.ttft_ms)
                    else:
                        stats.ttft_unchanged.append(bench.ttft_ms)

                if bench.total_latency_ms is not None:
                    stats.all_latency.append(bench.total_latency_ms)
                    if dec.correction_changed:
                        stats.latency_changed.append(bench.total_latency_ms)
                    else:
                        stats.latency_unchanged.append(bench.total_latency_ms)

                if bench.queue_wait_ms is not None:
                    if dec.correction_changed:
                        stats.queue_wait_changed.append(bench.queue_wait_ms)
                    else:
                        stats.queue_wait_unchanged.append(bench.queue_wait_ms)

    return stats


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return float("nan")
    s = sorted(values)
    idx = (len(s) - 1) * p / 100.0
    lo = int(idx)
    hi = min(lo + 1, len(s) - 1)
    frac = idx - lo
    return s[lo] * (1 - frac) + s[hi] * frac


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else float("nan")


def _fmt(v: float, decimals: int = 1) -> str:
    if math.isnan(v):
        return "n/a"
    return f"{v:.{decimals}f}"


def print_run_stats(stats: RunStats) -> None:
    print(f"\n{'='*60}")
    print(f"  {stats.label}")
    print(f"{'='*60}")

    total = stats.total_decisions
    changed = stats.correction_changed_count
    hit_rate = (changed / total * 100) if total > 0 else 0.0

    print(f"\n  Decisions:          {total}")
    print(f"  Correction changed: {changed} ({hit_rate:.1f}%)")
    print(f"  Queued:             {stats.queued_count} ({stats.queued_count/max(1,total)*100:.1f}%)")

    # Tier distribution
    print(f"\n  Tier distribution (selected candidates):")
    for tier, count in sorted(stats.tier_counts.items(), key=lambda x: -x[1]):
        pct = count / max(1, total) * 100
        bar = "#" * int(pct / 2)
        print(f"    {tier:<20s} {count:>4d} ({pct:>5.1f}%) {bar}")

    # Latency analysis
    if stats.all_ttft:
        print(f"\n  TTFT (all requests):")
        print(f"    Mean:   {_fmt(_mean(stats.all_ttft))} ms")
        print(f"    P50:    {_fmt(_percentile(stats.all_ttft, 50))} ms")
        print(f"    P95:    {_fmt(_percentile(stats.all_ttft, 95))} ms")

    if stats.ttft_changed and stats.ttft_unchanged:
        print(f"\n  TTFT split by correction:")
        print(f"    Changed  (n={len(stats.ttft_changed):>3d}): "
              f"mean={_fmt(_mean(stats.ttft_changed))} ms, "
              f"p50={_fmt(_percentile(stats.ttft_changed, 50))} ms, "
              f"p95={_fmt(_percentile(stats.ttft_changed, 95))} ms")
        print(f"    Unchanged(n={len(stats.ttft_unchanged):>3d}): "
              f"mean={_fmt(_mean(stats.ttft_unchanged))} ms, "
              f"p50={_fmt(_percentile(stats.ttft_unchanged, 50))} ms, "
              f"p95={_fmt(_percentile(stats.ttft_unchanged, 95))} ms")

        mean_changed = _mean(stats.ttft_changed)
        mean_unchanged = _mean(stats.ttft_unchanged)
        if not math.isnan(mean_changed) and not math.isnan(mean_unchanged) and mean_changed > 0:
            delta_pct = (mean_unchanged - mean_changed) / mean_unchanged * 100
            print(f"    Delta: {_fmt(delta_pct)}% {'faster' if delta_pct > 0 else 'slower'} when corrected")

    if stats.all_latency:
        print(f"\n  Total latency (all requests):")
        print(f"    Mean:   {_fmt(_mean(stats.all_latency))} ms")
        print(f"    P50:    {_fmt(_percentile(stats.all_latency, 50))} ms")
        print(f"    P95:    {_fmt(_percentile(stats.all_latency, 95))} ms")


def print_comparison(eccs_stats: RunStats, baseline_stats: RunStats) -> None:
    print(f"\n{'='*60}")
    print(f"  COMPARISON: {eccs_stats.label} vs {baseline_stats.label}")
    print(f"{'='*60}")

    if eccs_stats.all_ttft and baseline_stats.all_ttft:
        eccs_p50 = _percentile(eccs_stats.all_ttft, 50)
        base_p50 = _percentile(baseline_stats.all_ttft, 50)
        eccs_p95 = _percentile(eccs_stats.all_ttft, 95)
        base_p95 = _percentile(baseline_stats.all_ttft, 95)

        print(f"\n  {'Metric':<25s} {'ECCS On':>12s} {'ECCS Off':>12s} {'Speedup':>10s}")
        print(f"  {'-'*25} {'-'*12} {'-'*12} {'-'*10}")

        for name, ev, bv in [
            ("TTFT P50 (ms)", eccs_p50, base_p50),
            ("TTFT P95 (ms)", eccs_p95, base_p95),
            ("TTFT Mean (ms)", _mean(eccs_stats.all_ttft), _mean(baseline_stats.all_ttft)),
            ("Latency P50 (ms)", _percentile(eccs_stats.all_latency, 50), _percentile(baseline_stats.all_latency, 50)),
            ("Latency P95 (ms)", _percentile(eccs_stats.all_latency, 95), _percentile(baseline_stats.all_latency, 95)),
        ]:
            speedup = bv / ev if ev > 0 and not math.isnan(ev) and not math.isnan(bv) else float("nan")
            print(f"  {name:<25s} {_fmt(ev):>12s} {_fmt(bv):>12s} {_fmt(speedup, 2):>9s}x")

    print(f"\n  Correction hit rate:")
    print(f"    ECCS On:  {eccs_stats.correction_changed_count}/{eccs_stats.total_decisions} "
          f"({eccs_stats.correction_changed_count/max(1,eccs_stats.total_decisions)*100:.1f}%)")
    print(f"    ECCS Off: {baseline_stats.correction_changed_count}/{baseline_stats.total_decisions} "
          f"({baseline_stats.correction_changed_count/max(1,baseline_stats.total_decisions)*100:.1f}%)")


def export_csv(stats: RunStats, path: Path) -> None:
    """Export key metrics to CSV for further processing."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["metric", "value"])
        writer.writerow(["label", stats.label])
        writer.writerow(["total_decisions", stats.total_decisions])
        writer.writerow(["correction_changed", stats.correction_changed_count])
        writer.writerow(["correction_hit_rate_pct",
                         f"{stats.correction_changed_count/max(1,stats.total_decisions)*100:.2f}"])
        writer.writerow(["queued_count", stats.queued_count])
        for tier, count in sorted(stats.tier_counts.items()):
            writer.writerow([f"tier_{tier}", count])
        if stats.all_ttft:
            writer.writerow(["ttft_mean_ms", f"{_mean(stats.all_ttft):.2f}"])
            writer.writerow(["ttft_p50_ms", f"{_percentile(stats.all_ttft, 50):.2f}"])
            writer.writerow(["ttft_p95_ms", f"{_percentile(stats.all_ttft, 95):.2f}"])
        if stats.all_latency:
            writer.writerow(["latency_mean_ms", f"{_mean(stats.all_latency):.2f}"])
            writer.writerow(["latency_p50_ms", f"{_percentile(stats.all_latency, 50):.2f}"])
            writer.writerow(["latency_p95_ms", f"{_percentile(stats.all_latency, 95):.2f}"])


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Analyze ECCS ablation benchmark results.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--decision-log", required=True, type=Path,
                        help="Path to ECCS decision log (JSON-lines)")
    parser.add_argument("--benchmark-csv", type=Path, default=None,
                        help="Path to benchmark detailed CSV (optional)")
    parser.add_argument("--baseline-log", type=Path, default=None,
                        help="Path to baseline (ECCS off) decision log for comparison")
    parser.add_argument("--baseline-csv", type=Path, default=None,
                        help="Path to baseline benchmark detailed CSV")
    parser.add_argument("--export-csv", type=Path, default=None,
                        help="Export summary metrics to CSV")
    args = parser.parse_args()

    # Load primary run
    decisions = load_decision_log(args.decision_log)
    if not decisions:
        print(f"No decisions found in {args.decision_log}", file=sys.stderr)
        return 1

    benchmarks = None
    if args.benchmark_csv:
        benchmarks = load_benchmark_csv(args.benchmark_csv)

    label = "ECCS On" if decisions[0].ettft_enabled else "ECCS Off"
    stats = compute_stats(decisions, benchmarks, label)
    print_run_stats(stats)

    if args.export_csv:
        export_csv(stats, args.export_csv)
        print(f"\nExported metrics to {args.export_csv}")

    # Load baseline for comparison
    if args.baseline_log:
        baseline_decisions = load_decision_log(args.baseline_log)
        baseline_benchmarks = None
        if args.baseline_csv:
            baseline_benchmarks = load_benchmark_csv(args.baseline_csv)

        bl_label = "ECCS Off" if baseline_decisions and not baseline_decisions[0].ettft_enabled else "Baseline"
        baseline_stats = compute_stats(baseline_decisions, baseline_benchmarks, bl_label)
        print_run_stats(baseline_stats)
        print_comparison(stats, baseline_stats)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
