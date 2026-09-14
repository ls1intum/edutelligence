"""Forwarding a worker's raw vLLM /metrics into the orchestrator's own
Prometheus export (see logos.monitoring.prometheus_metrics._VLLMForwardedMetricsCollector
and LogosNodeRuntimeRegistry.on_vllm_metrics / peek_vllm_metrics)."""

from __future__ import annotations

import logos as _main
from logos.logosnode_registry import LogosNodeRuntimeRegistry, ProviderSession
from logos.monitoring.prometheus_metrics import _VLLMForwardedMetricsCollector
from logos.routers.logosnode import _MAX_VLLM_METRICS_BYTES, _validated_vllm_metrics_text

_TEXT = """# HELP vllm:num_requests_running desc
# TYPE vllm:num_requests_running gauge
vllm:num_requests_running{model_name="foo"} 3.0
"""


def _session(registry: LogosNodeRuntimeRegistry, provider_id: int, worker_id: str) -> None:
    registry._sessions[provider_id] = ProviderSession(  # noqa: SLF001
        provider_id=provider_id,
        worker_id=worker_id,
        websocket=object(),
    )


async def test_on_vllm_metrics_round_trips_through_peek() -> None:
    registry = LogosNodeRuntimeRegistry()
    _session(registry, 1, "worker-a")

    assert registry.peek_vllm_metrics(1) is None

    await registry.on_vllm_metrics(1, _TEXT)

    assert registry.peek_vllm_metrics(1) == ("worker-a", _TEXT)


async def test_peek_vllm_metrics_is_none_for_unknown_provider() -> None:
    registry = LogosNodeRuntimeRegistry()
    assert registry.peek_vllm_metrics(999) is None


async def test_on_vllm_metrics_ignores_unknown_provider() -> None:
    """A message for a provider with no live session (already disconnected,
    or racing detach_session) must not resurrect any state for it."""
    registry = LogosNodeRuntimeRegistry()
    await registry.on_vllm_metrics(42, _TEXT)
    assert registry.peek_vllm_metrics(42) is None


async def test_collector_merges_and_relabels_by_worker(monkeypatch) -> None:
    registry = LogosNodeRuntimeRegistry()
    _session(registry, 1, "worker-a")
    _session(registry, 2, "worker-b")
    await registry.on_vllm_metrics(1, _TEXT)
    await registry.on_vllm_metrics(2, _TEXT.replace("3.0", "5.0"))

    monkeypatch.setattr(_main, "_logosnode_registry", registry)

    families = list(_VLLMForwardedMetricsCollector().collect())

    assert [f.name for f in families] == ["vllm:num_requests_running"]
    by_worker = {s.labels["worker_id"]: s.value for s in families[0].samples}
    assert by_worker == {"worker-a": 3.0, "worker-b": 5.0}


async def test_collector_yields_nothing_without_any_metrics_pushed() -> None:
    families = list(_VLLMForwardedMetricsCollector().collect())
    assert families == []


async def test_empty_push_clears_a_stale_snapshot() -> None:
    """The last lane on a worker stopping must not leave its final metrics
    snapshot cached forever — the worker pushes an empty export precisely so
    this clears it."""
    registry = LogosNodeRuntimeRegistry()
    _session(registry, 1, "worker-a")
    await registry.on_vllm_metrics(1, _TEXT)
    assert registry.peek_vllm_metrics(1) is not None

    await registry.on_vllm_metrics(1, "")

    assert registry.peek_vllm_metrics(1) is None


def test_validated_vllm_metrics_text_accepts_a_plain_string() -> None:
    assert _validated_vllm_metrics_text(_TEXT, provider_id=1) == _TEXT


def test_validated_vllm_metrics_text_rejects_non_strings() -> None:
    assert _validated_vllm_metrics_text(123, provider_id=1) is None
    assert _validated_vllm_metrics_text({"not": "a string"}, provider_id=1) is None
    assert _validated_vllm_metrics_text(None, provider_id=1) is None


def test_validated_vllm_metrics_text_rejects_oversized_payloads() -> None:
    oversized = "x" * (_MAX_VLLM_METRICS_BYTES + 1)
    assert _validated_vllm_metrics_text(oversized, provider_id=1) is None


def test_validated_vllm_metrics_text_counts_lone_surrogates_as_real_bytes() -> None:
    """A string of lone surrogates must not sail under the cap for free —

    encoding with errors="ignore" would silently drop them (0 bytes for any
    count), letting an oversized payload bypass the limit entirely."""
    lone_surrogates = "\ud800" * (_MAX_VLLM_METRICS_BYTES + 1)
    assert _validated_vllm_metrics_text(lone_surrogates, provider_id=1) is None
