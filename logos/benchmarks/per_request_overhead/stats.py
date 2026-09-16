"""Statistics helpers for the per-request overhead benchmark.

All latency values are integers in nanoseconds (``time.perf_counter_ns``).
The headline metric is the *median* of each run; the overhead is computed as
``median(logos) - median(direct baseline)`` — not the median of per-request
differences, because the two runs are separate blocks and comparing block
medians cancels common-mode drift (shared runner load affects both).
"""

from __future__ import annotations

import math
from typing import Dict, List, Sequence


def percentile(values: Sequence[float], pct: float) -> float:
    """Linear-interpolated percentile (pct in 0..100) of a non-empty sequence."""
    if not values:
        raise ValueError("percentile() of empty sequence")
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = (pct / 100.0) * (len(ordered) - 1)
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return float(ordered[lo])
    frac = rank - lo
    return ordered[lo] * (1.0 - frac) + ordered[hi] * frac


def summarize(values: Sequence[int]) -> Dict[str, float]:
    """Summary of a latency sample set (ns): n, min, mean, median, p50..p99, max."""
    if not values:
        return {"n": 0}
    return {
        "n": len(values),
        "min_ns": float(min(values)),
        "mean_ns": float(sum(values)) / len(values),
        "p50_ns": percentile(values, 50),
        "p90_ns": percentile(values, 90),
        "p95_ns": percentile(values, 95),
        "p99_ns": percentile(values, 99),
        "max_ns": float(max(values)),
    }


def overhead_ns(logos_ns: Sequence[int], direct_ns: Sequence[int]) -> Dict[str, float]:
    """Median-based overhead: median(Logos path) - median(direct baseline)."""
    if not logos_ns or not direct_ns:
        return {"overhead_ns": 0.0, "logos_median_ns": 0.0, "direct_median_ns": 0.0, "n_logos": 0, "n_direct": 0}
    logos_med = percentile(logos_ns, 50)
    direct_med = percentile(direct_ns, 50)
    return {
        "overhead_ns": logos_med - direct_med,
        "logos_median_ns": logos_med,
        "direct_median_ns": direct_med,
        "n_logos": len(logos_ns),
        "n_direct": len(direct_ns),
    }


def merge_phase_totals(
    per_request_phases: Sequence[Dict[str, Dict[str, int]]],
) -> Dict[str, Dict[str, float]]:
    """Aggregate per-request phase dicts into totals.

    Input: list of ``{phase_name: {"total_ns": int, "count": int}}`` (one per
    request trace). Output: ``{phase_name: {"total_ns": int, "count": int,
    "mean_ns": float, "p50_ns": float}}`` where p50 is the median of the
    *per-request* phase totals (0 for requests missing the phase).
    """
    totals: Dict[str, Dict[str, object]] = {}
    per_request: Dict[str, List[float]] = {}
    n_requests = len(per_request_phases)
    for phases in per_request_phases:
        for name, bucket in phases.items():
            entry = totals.setdefault(name, {"total_ns": 0, "count": 0})
            entry["total_ns"] = int(entry["total_ns"]) + int(bucket["total_ns"])
            entry["count"] = int(entry["count"]) + int(bucket["count"])
            per_request.setdefault(name, [0.0] * n_requests)
    for name, series in per_request.items():
        for idx, phases in enumerate(per_request_phases):
            if name in phases:
                series[idx] = float(phases[name]["total_ns"])
    result: Dict[str, Dict[str, float]] = {}
    for name, entry in totals.items():
        series = per_request[name]
        count = int(entry["count"])
        result[name] = {
            "total_ns": float(entry["total_ns"]),
            "count": float(count),
            "mean_ns": float(entry["total_ns"]) / count if count else 0.0,
            "p50_ns": percentile(series, 50),
        }
    return result
