"""Timestamp selection in _build_live_local_provider_sample.

The sample timestamp is the freshest of ``runtime.timestamp`` (Pydantic-
serialized, ``Z`` suffix) and ``last_heartbeat`` (``isoformat()``,
``+00:00`` suffix). Those are instants, not comparable strings — and a
candidate that fails to parse (or is naive) must be skipped, not crash the
comparison.
"""

import datetime

from logos.logosnode_snapshot import _build_live_local_provider_sample


def _snapshot(runtime_ts, heartbeat_ts):
    return {
        "last_heartbeat": heartbeat_ts,
        "runtime": {
            "timestamp": runtime_ts,
            "lanes": [],
            "devices": {"used_memory_mb": 100},
        },
    }


def test_prefers_freshest_instant_across_mixed_iso_suffixes():
    # Pin the heartbeat's fractional part so the bug is deterministic:
    # lexicographically "...:05Z" > "...:05.500000+00:00" ('Z' > '.'), so a
    # string max() picks the *older* runtime timestamp.
    now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=500000)
    heartbeat = now.isoformat()
    runtime_ts = (now - datetime.timedelta(milliseconds=500)).strftime("%Y-%m-%dT%H:%M:%SZ")

    sample = _build_live_local_provider_sample({}, _snapshot(runtime_ts, heartbeat))

    assert sample is not None
    assert sample["timestamp"] == heartbeat


def test_tolerates_naive_runtime_timestamp():
    # A naive candidate (no suffix at all) must be treated as UTC instead of
    # making max() raise TypeError against the aware heartbeat.
    heartbeat = datetime.datetime.now(datetime.timezone.utc).isoformat()

    sample = _build_live_local_provider_sample({}, _snapshot("2026-01-01T00:00:00", heartbeat))

    assert sample is not None
    assert sample["timestamp"] == heartbeat


def test_ignores_unparseable_runtime_timestamp():
    # (The now-fallback in the builder is only reachable when last_heartbeat
    # itself is unusable — which _logosnode_snapshot_is_connected already
    # rejects — so this pins the useful half: a garbage runtime timestamp is
    # skipped, and the valid heartbeat wins.)
    heartbeat = datetime.datetime.now(datetime.timezone.utc).isoformat()

    sample = _build_live_local_provider_sample({}, _snapshot("not-a-timestamp", heartbeat))

    assert sample is not None
    assert sample["timestamp"] == heartbeat


def test_scheduler_signals_carry_gpu_index_health_and_faults():
    from logos.logosnode_snapshot import _build_logosnode_scheduler_signals

    signals = _build_logosnode_scheduler_signals(
        {
            "lanes": [],
            "devices": {
                "gpu_faults": ["gpu0 (GPU-aaa): GPU requires reset"],
                "devices": [
                    {
                        "device_id": "GPU-aaa",
                        "memory_used_mb": 82989,
                        "memory_total_mb": 97887,
                        "health": "faulted",
                        "health_reason": "GPU requires reset",
                        "extra": {"index": 0},
                    },
                    {"device_id": "GPU-ccc", "memory_total_mb": 97887, "extra": {"index": 2}},
                ],
            },
        }
    )

    provider = signals["provider"]
    assert provider["gpu_faults"] == ["gpu0 (GPU-aaa): GPU requires reset"]
    assert [(d["index"], d["health"], d["health_reason"]) for d in provider["devices"]] == [
        (0, "faulted", "GPU requires reset"),
        (2, "ok", ""),
    ]
