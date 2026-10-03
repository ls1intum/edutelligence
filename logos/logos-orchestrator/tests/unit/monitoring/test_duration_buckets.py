"""Latency percentiles must not be pinned to the top bucket.

`histogram_quantile` cannot report a value above the highest *finite* bucket:
anything beyond it falls into +Inf and the quantile is returned as that
boundary. With the buckets topping out at 120s, every high percentile read
exactly "2 minutes" — in production 5% of requests exceed 120s, so p95 sat on
the edge and p99 (really ~300s) was clamped outright. It looked like a
dashboard fault; it was the bucket layout.
"""

from __future__ import annotations

from logos.monitoring import prometheus_metrics as prom

# The longest a single request can legitimately take: the queue wait alone is
# bounded at 1200s (LOGOS_TIMEOUT_S / the scheduler's own default).
LONGEST_PLAUSIBLE_REQUEST_S = 1200.0


def _finite_buckets(metric_name: str) -> list[float]:
    """The bucket boundaries Prometheus actually scrapes.

    A labelled histogram emits nothing until a child exists, so this reads
    the buckets off a probe observation rather than the declaration — the
    same thing Grafana would see.
    """
    prom.REQUEST_DURATION_SECONDS.labels(
        model="__bucket_probe__",
        provider="__bucket_probe__",
        status="__bucket_probe__",
    ).observe(0.0)

    for metric in prom.registry.collect():
        if metric.name != metric_name:
            continue
        bounds = {
            float(sample.labels["le"])
            for sample in metric.samples
            if sample.name.endswith("_bucket") and sample.labels.get("le") not in (None, "+Inf")
        }
        return sorted(bounds)
    raise AssertionError(f"metric {metric_name} is not registered")


def test_request_duration_buckets_reach_past_the_longest_plausible_request():
    buckets = _finite_buckets("logos_request_duration_seconds")
    assert buckets, "no finite buckets found"
    assert max(buckets) >= LONGEST_PLAUSIBLE_REQUEST_S, (
        f"highest finite bucket is {max(buckets)}s — every percentile above that is "
        f"reported as exactly {max(buckets)}s, which is the '2 minute cap' this fixes"
    )


def test_the_range_that_used_to_be_invisible_is_now_resolved():
    """p99 in production is ~300s and the slowest requests run past 1600s.
    Those need distinguishable buckets, not one lump above 120s."""
    buckets = set(_finite_buckets("logos_request_duration_seconds"))
    for boundary in (300.0, 600.0, 1200.0):
        assert boundary in buckets, f"no bucket at {boundary}s"


def test_short_requests_keep_their_resolution():
    """Widening the top must not come at the cost of the common case."""
    buckets = _finite_buckets("logos_request_duration_seconds")
    assert len([b for b in buckets if b <= 10.0]) >= 6
