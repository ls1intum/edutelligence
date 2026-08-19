from types import SimpleNamespace

from logos import MonitoringRecorder
from logos.monitoring import recorder as recorder_module


def _dummy_db_factory(calls):
    class DummyDB:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def update_request_log_metrics(self, **kwargs):
            calls.append(kwargs)

    return lambda: DummyDB()


def _make_recorder(monkeypatch, model_names, provider_names):
    """Recorder with stubbed name caches (no DB lookups in unit tests)."""
    calls = []
    monkeypatch.setattr(
        recorder_module,
        "model_name_cache",
        SimpleNamespace(get=lambda model_id: model_names.get(model_id, str(model_id))),
    )
    monkeypatch.setattr(
        recorder_module,
        "provider_name_cache",
        SimpleNamespace(get=lambda provider_id: provider_names.get(provider_id, str(provider_id))),
    )
    return MonitoringRecorder(db_factory=_dummy_db_factory(calls)), calls


def _make_recording_metric(name):
    class _RecordingMetric:
        def __init__(self):
            self.name = name
            self.label_calls = []
            self.observations = []
            self.inc_calls = 0

        def labels(self, **kwargs):
            self.label_calls.append(kwargs)
            return self

        def observe(self, value):
            self.observations.append(value)

        def inc(self):
            self.inc_calls += 1

        def dec(self):
            pass

        def set(self, value):
            pass

    return _RecordingMetric()


def _patch_prom(monkeypatch):
    """Replace the recorder's prom module with label-recording fakes.

    Some test modules install a stubbed ``prometheus_client`` into
    sys.modules at import time, so asserting on the real registry would
    depend on test ordering — recording the .labels() calls is
    deterministic in both worlds.
    """
    fake = SimpleNamespace(
        REQUESTS_TOTAL=_make_recording_metric("logos_requests_total"),
        REQUESTS_IN_FLIGHT=_make_recording_metric("logos_requests_in_flight"),
        SCHEDULING_DECISIONS_TOTAL=_make_recording_metric("logos_scheduling_decisions_total"),
        REQUEST_DURATION_SECONDS=_make_recording_metric("logos_request_duration_seconds"),
        COLD_STARTS_TOTAL=_make_recording_metric("logos_cold_starts_total"),
        QUEUE_DEPTH=_make_recording_metric("logos_queue_depth"),
    )
    monkeypatch.setattr(recorder_module, "prom", fake)
    return fake


def test_recorder_updates_log_entry_metrics_by_request_id(monkeypatch):
    recorder, calls = _make_recorder(monkeypatch, {27: "test-model"}, {12: "test-provider"})
    _patch_prom(monkeypatch)

    recorder.record_enqueue(
        request_id="req-1",
        model_id=27,
        provider_id=12,
        initial_priority="normal",
        queue_depth=3,
        timeout_s=60,
    )
    recorder.record_scheduled(
        request_id="req-1",
        model_id=27,
        provider_id=12,
        priority_when_scheduled="normal",
        queue_depth_at_schedule=1,
        provider_metrics={"available_vram_mb": 1024},
    )
    recorder.record_complete(
        request_id="req-1",
        result_status="success",
        cold_start=False,
    )

    assert calls[0]["request_id"] == "req-1"
    assert calls[0]["initial_priority"] == "normal"
    assert calls[0]["queue_depth_at_enqueue"] == 3
    assert calls[0]["timeout_s"] == 60

    assert calls[1]["priority_when_scheduled"] == "normal"
    assert calls[1]["queue_depth_at_schedule"] == 1
    assert calls[1]["available_vram_mb"] == 1024

    assert calls[2]["result_status"] == "success"
    assert calls[2]["cold_start"] is False


# ---------------------------------------------------------------------------
# Prometheus label plumbing (issue 738)
# ---------------------------------------------------------------------------


def test_record_complete_labels_duration_with_model_and_provider(monkeypatch):
    recorder, _ = _make_recorder(monkeypatch, {27: "Qwen/Qwen3-8B"}, {12: "local-node"})
    fake = _patch_prom(monkeypatch)

    recorder.record_enqueue(
        request_id="req-738-duration",
        model_id=27,
        provider_id=12,
        initial_priority="normal",
        queue_depth=0,
    )
    recorder.record_scheduled(
        request_id="req-738-duration",
        model_id=27,
        provider_id=12,
        priority_when_scheduled="normal",
        queue_depth_at_schedule=0,
    )
    recorder.record_complete(request_id="req-738-duration", result_status="success")

    duration = fake.REQUEST_DURATION_SECONDS
    assert duration.label_calls == [{"model": "Qwen/Qwen3-8B", "provider": "local-node", "status": "success"}]
    assert len(duration.observations) == 1


def test_record_scheduled_overwrites_enqueue_labels(monkeypatch):
    """The actually selected model/provider wins over the enqueue-time guess."""
    recorder, _ = _make_recorder(monkeypatch, {27: "model-a", 28: "model-b"}, {12: "provider-a", 13: "provider-b"})
    fake = _patch_prom(monkeypatch)

    recorder.record_enqueue(
        request_id="req-738-override",
        model_id=27,
        provider_id=12,
        initial_priority="normal",
        queue_depth=0,
    )
    # Scheduling picked a different model/provider than the top candidate.
    recorder.record_scheduled(
        request_id="req-738-override",
        model_id=28,
        provider_id=13,
        priority_when_scheduled="high",
        queue_depth_at_schedule=0,
    )
    recorder.record_complete(request_id="req-738-override", result_status="success")

    duration = fake.REQUEST_DURATION_SECONDS
    assert duration.label_calls == [{"model": "model-b", "provider": "provider-b", "status": "success"}]
    # The enqueue-time guess must not produce its own observation.
    assert {"model": "model-a", "provider": "provider-a", "status": "success"} not in duration.label_calls


def test_unresolved_request_falls_back_to_unknown_labels(monkeypatch):
    """Requests that fail before a model/provider is selected keep 'unknown'."""
    recorder, _ = _make_recorder(monkeypatch, {}, {})
    fake = _patch_prom(monkeypatch)

    recorder.record_enqueue(
        request_id="req-738-unresolved",
        model_id=None,
        provider_id=None,
        initial_priority="normal",
        queue_depth=0,
    )
    recorder.record_complete(
        request_id="req-738-unresolved",
        result_status="error",
        error_message="no capacity",
    )

    duration = fake.REQUEST_DURATION_SECONDS
    assert duration.label_calls == [{"model": "unknown", "provider": "unknown", "status": "error"}]
    assert len(duration.observations) == 1


def test_cold_starts_total_labeled_with_model(monkeypatch):
    recorder, _ = _make_recorder(monkeypatch, {27: "cold-model"}, {12: "local-node"})
    fake = _patch_prom(monkeypatch)

    recorder.record_enqueue(
        request_id="req-738-cold",
        model_id=27,
        provider_id=12,
        initial_priority="normal",
        queue_depth=0,
    )
    recorder.record_scheduled(
        request_id="req-738-cold",
        model_id=27,
        provider_id=12,
        priority_when_scheduled="normal",
        queue_depth_at_schedule=0,
    )
    recorder.record_complete(request_id="req-738-cold", result_status="success", cold_start=True)

    assert fake.COLD_STARTS_TOTAL.label_calls == [{"model": "cold-model"}]
    assert fake.COLD_STARTS_TOTAL.inc_calls == 1


def test_complete_without_enqueue_records_no_duration(monkeypatch):
    """A completion without any recorded start time observes nothing (old behaviour)."""
    recorder, _ = _make_recorder(monkeypatch, {}, {})
    fake = _patch_prom(monkeypatch)

    recorder.record_complete(request_id="req-738-ghost", result_status="error")

    assert fake.REQUEST_DURATION_SECONDS.label_calls == []
    assert fake.REQUEST_DURATION_SECONDS.observations == []
