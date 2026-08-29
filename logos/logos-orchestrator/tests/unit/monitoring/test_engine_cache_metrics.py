"""Tests for the per-(model, provider) engine-cache gauges (issue 819).

``update_engine_cache_metrics`` publishes the prefix-cache hit rate and the
MTP acceptance rate to Prometheus. The gauges are replaced with recording
fakes so the assertions are deterministic regardless of whether a stubbed
``prometheus_client`` is installed by the capacity test modules.
"""

import pytest

from logos.monitoring import prometheus_metrics as prom


class _FakeLabeledGauge:
    """Mirrors the real prometheus_client API strictly: values are set through
    ``.labels(**kwargs)`` children, while ``remove(*labelvalues)`` lives on
    the parent metric and raises ``KeyError`` for a label set that was never
    created (the real library does ``del self._metrics[labelvalues]``). A
    lenient ``pop(key, None)`` here would mask retire-path bugs that kill the
    capacity planner in production."""

    _labelnames = ("model", "provider")

    def __init__(self):
        self.values: dict[tuple[tuple[str, str], ...], float] = {}
        self.removed: list[tuple[tuple[str, str], ...]] = []

    def labels(self, **kwargs):
        return _FakeLabeledChild(self, tuple(sorted(kwargs.items())))

    def remove(self, *labelvalues):
        key = tuple(zip(self._labelnames, labelvalues))
        self.removed.append(key)
        del self.values[key]


class _FakeLabeledChild:
    def __init__(self, parent: _FakeLabeledGauge, key: tuple[tuple[str, str], ...]):
        self._parent = parent
        self._key = key

    def set(self, value):
        self._parent.values[self._key] = value


def _key(model: str, provider: str) -> tuple[tuple[str, str], ...]:
    return (("model", model), ("provider", provider))


def _patch_prom(monkeypatch):
    fake_prefix = _FakeLabeledGauge()
    fake_mtp = _FakeLabeledGauge()
    monkeypatch.setattr(prom, "PREFIX_CACHE_HIT_RATE", fake_prefix)
    monkeypatch.setattr(prom, "MTP_ACCEPTANCE_RATE", fake_mtp)
    monkeypatch.setattr(prom, "_PUBLISHED_ENGINE_METRIC_KEYS", set())
    return fake_prefix, fake_mtp


def test_publishes_rates_for_each_pair(monkeypatch):
    fake_prefix, fake_mtp = _patch_prom(monkeypatch)

    prom.update_engine_cache_metrics(
        [
            ("model-a", "node-1", 0.5, 0.3),
            ("model-b", "node-1", None, 0.8),
        ]
    )

    assert fake_prefix.values == {_key("model-a", "node-1"): 0.5}
    assert fake_mtp.values == {
        _key("model-a", "node-1"): 0.3,
        _key("model-b", "node-1"): 0.8,
    }
    assert fake_prefix.removed == []
    assert fake_mtp.removed == []


def test_none_rate_keeps_previous_value(monkeypatch):
    """A scrape failure (None rate) must not zero out or retire the pair."""
    fake_prefix, fake_mtp = _patch_prom(monkeypatch)

    prom.update_engine_cache_metrics([("model-a", "node-1", 0.5, 0.3)])
    prom.update_engine_cache_metrics([("model-a", "node-1", None, None)])

    assert fake_prefix.values == {_key("model-a", "node-1"): 0.5}
    assert fake_mtp.values == {_key("model-a", "node-1"): 0.3}
    assert fake_prefix.removed == []
    assert fake_mtp.removed == []


def test_stale_pairs_are_removed(monkeypatch):
    """Pairs whose lanes are gone lose their label sets on the next publish."""
    fake_prefix, fake_mtp = _patch_prom(monkeypatch)

    prom.update_engine_cache_metrics(
        [
            ("model-a", "node-1", 0.5, 0.3),
            ("model-b", "node-1", 0.2, None),
        ]
    )
    prom.update_engine_cache_metrics([("model-a", "node-1", 0.6, 0.4)])

    assert fake_prefix.values == {_key("model-a", "node-1"): 0.6}
    assert fake_mtp.values == {_key("model-a", "node-1"): 0.4}
    assert fake_prefix.removed == [_key("model-b", "node-1")]
    assert fake_mtp.removed == [_key("model-b", "node-1")]


def test_empty_entries_retire_all_published_pairs(monkeypatch):
    fake_prefix, fake_mtp = _patch_prom(monkeypatch)

    prom.update_engine_cache_metrics([("model-a", "node-1", 0.5, 0.3)])
    prom.update_engine_cache_metrics([])

    assert fake_prefix.values == {}
    assert fake_mtp.values == {}
    assert fake_prefix.removed == [_key("model-a", "node-1")]
    assert fake_mtp.removed == [_key("model-a", "node-1")]


# ---------------------------------------------------------------------------
# Retire path with a missing series (the planner-killing KeyError)
# ---------------------------------------------------------------------------


def test_retiring_pair_without_mtp_series_does_not_raise(monkeypatch):
    """A model without speculative decoding never published an MTP child, so
    its MTP remove raises KeyError in the real library. Retiring the pair must
    still succeed — an escape here kills the capacity planner cycle and the
    tracked-key state freezes, re-raising on every cycle afterwards."""
    fake_prefix, fake_mtp = _patch_prom(monkeypatch)

    prom.update_engine_cache_metrics([("qwen", "w1", 0.5, None)])
    prom.update_engine_cache_metrics([])

    assert fake_prefix.values == {}
    assert fake_mtp.values == {}
    assert fake_prefix.removed == [_key("qwen", "w1")]
    # The MTP remove was attempted and its KeyError swallowed by production
    # code, not masked by a lenient fake.
    assert fake_mtp.removed == [_key("qwen", "w1")]


def test_retiring_pair_without_prefix_series_does_not_raise(monkeypatch):
    """Symmetric case: a lane that reported no prefix data has no prefix child."""
    fake_prefix, fake_mtp = _patch_prom(monkeypatch)

    prom.update_engine_cache_metrics([("qwen", "w1", None, 0.4)])
    prom.update_engine_cache_metrics([])

    assert fake_prefix.values == {}
    assert fake_mtp.values == {}
    assert fake_prefix.removed == [_key("qwen", "w1")]
    assert fake_mtp.removed == [_key("qwen", "w1")]


def test_retiring_pair_never_published_either_series_does_not_raise(monkeypatch):
    """A pair seen only with two None rates (scrape failure) has no child on
    either gauge."""
    fake_prefix, fake_mtp = _patch_prom(monkeypatch)

    prom.update_engine_cache_metrics([("qwen", "w1", None, None)])
    prom.update_engine_cache_metrics([])

    assert fake_prefix.values == {}
    assert fake_mtp.values == {}
    assert fake_prefix.removed == [_key("qwen", "w1")]
    assert fake_mtp.removed == [_key("qwen", "w1")]


def test_tracked_state_refreshes_even_when_retirement_raises(monkeypatch):
    """A failure during retirement must not freeze the tracked-key state: a
    stale diff set would re-raise on every subsequent call and keep the
    planner cycle dead. The ``finally`` refresh guarantees the next call sees
    the up-to-date set of live pairs."""
    fake_prefix, fake_mtp = _patch_prom(monkeypatch)

    prom.update_engine_cache_metrics(
        [
            ("model-a", "node-1", 0.5, 0.3),
            ("model-b", "node-1", 0.2, 0.1),
        ]
    )

    real_mtp_remove = fake_mtp.remove

    def _explode(*labelvalues):
        raise RuntimeError("boom")

    fake_mtp.remove = _explode
    with pytest.raises(RuntimeError, match="boom"):
        prom.update_engine_cache_metrics([("model-a", "node-1", 0.6, 0.4)])

    # Round 3 must diff against {model-a} only — model-b was dropped from the
    # tracked state despite round 2's failure. With a frozen state, model-b's
    # MTP remove would be attempted again here.
    fake_mtp.remove = real_mtp_remove
    prom.update_engine_cache_metrics([])

    assert fake_prefix.removed == [
        _key("model-b", "node-1"),  # round 2, before the failure
        _key("model-a", "node-1"),  # round 3
    ]
    assert fake_mtp.removed == [_key("model-a", "node-1")]  # round 3 only
