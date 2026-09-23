"""Statistics helpers for the gateway concurrency benchmark.

Self-contained (not imported from ``per_request_overhead``) so the two
benchmark tools stay independent — each was already built standalone, and a
cross-import would couple their release/refactor cycles for no real gain.
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


def summarize(values: Sequence[float]) -> Dict[str, float]:
    """Summary of a latency sample set (ms): n, min, mean, p50/p90/p95/p99, max."""
    if not values:
        return {"n": 0}
    return {
        "n": len(values),
        "min_ms": float(min(values)),
        "mean_ms": float(sum(values)) / len(values),
        "p50_ms": percentile(values, 50),
        "p90_ms": percentile(values, 90),
        "p95_ms": percentile(values, 95),
        "p99_ms": percentile(values, 99),
        "max_ms": float(max(values)),
    }


def overhead_ms(gateway_ms: Sequence[float], direct_ms: Sequence[float]) -> Dict[str, float]:
    """p50/p95 added latency: matching percentile(gateway) - percentile(direct).

    Not the percentile of per-request differences — the two series are
    separate interleaved runs, and comparing matching percentiles cancels
    common-mode runner drift the way per-request pairing cannot.
    """
    if not gateway_ms or not direct_ms:
        return {"overhead_p50_ms": 0.0, "overhead_p95_ms": 0.0, "n_gateway": 0, "n_direct": 0}
    return {
        "overhead_p50_ms": percentile(gateway_ms, 50) - percentile(direct_ms, 50),
        "overhead_p95_ms": percentile(gateway_ms, 95) - percentile(direct_ms, 95),
        "n_gateway": len(gateway_ms),
        "n_direct": len(direct_ms),
    }


def summarize_all(rows: List[Dict[str, float]], key: str) -> Dict[str, float]:
    """``summarize()`` over one numeric field of a list of result dicts."""
    return summarize([r[key] for r in rows if key in r])
