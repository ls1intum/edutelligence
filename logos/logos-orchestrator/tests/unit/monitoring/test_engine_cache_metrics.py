"""Tests for the per-(model, provider) engine-cache gauges (issue 819).

``update_engine_cache_metrics`` publishes the prefix-cache hit rate and the
MTP acceptance rate to Prometheus. The gauges are replaced with recording
fakes so the assertions are deterministic regardless of whether a stubbed
``prometheus_client`` is installed by the capacity test modules.
"""

from logos.monitoring import prometheus_metrics as prom


class _FakeLabeledGauge:
    """Mirrors the real prometheus_client API: values are set through
    ``.labels(**kwargs)`` children, while ``remove(*labelvalues)`` lives on
    the parent metric."""

    _labelnames = ("model", "provider")

    def __init__(self):
        self.values: dict[tuple[tuple[str, str], ...], float] = {}
        self.removed: list[tuple[tuple[str, str], ...]] = []

    def labels(self, **kwargs):
        return _FakeLabeledChild(self, tuple(sorted(kwargs.items())))

    def remove(self, *labelvalues):
        key = tuple(zip(self._labelnames, labelvalues))
        self.removed.append(key)
        self.values.pop(key, None)


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
